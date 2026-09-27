"""The agent loop: observe → decide → act → evaluate → exit.

The pipeline's three steps each do one thing; this module decides how many
times to run them and what to do with the results. It holds no prompts and
makes no model calls of its own — it sequences `agent.pipeline`.

Layer note: this module takes a `MeetingContext` by parameter. It never reads a
database, and `agent/` never imports `storage/`.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

import config
from agent.gaps import (
    detect_evidence_gaps, detect_structural_gaps, merge_gaps, merge_with_deterministic,
    normalize_evidence_severity,
)
from agent.llm_client import LLMClient, LLMError
from agent.pipeline import run_extract, run_review, run_triage
from agent.schemas import (
    GapType, MeetingContext, MeetingExtraction, ReviewResult, TriageVerdict,
)

T = TypeVar("T", bound=BaseModel)

# The gap types the deterministic backstop produces (`detect_structural_gaps`
# and `detect_evidence_gaps`), and so can always recompute from the final
# extraction. A carried-over one would be stale — or, for evidence, a model
# copy that could win the merge tie and downgrade a blocking gap.
_DETERMINISTIC_TYPES = frozenset({
    GapType.MISSING_OWNER, GapType.MISSING_DEADLINE, GapType.UNSUPPORTED_EVIDENCE,
})


@dataclass
class LoopOutcome:
    extraction: MeetingExtraction
    review: ReviewResult
    passes: int
    tokens: int
    latency_ms: int
    raw: str = ""            # the FINAL pass's untouched model response, kept for audit
    notes_for_manager: list[str] = field(default_factory=list)
    corrected_item_ids: set[str] = field(default_factory=set)
    # Pass 1 exactly as the model returned it, so the eval can measure what the
    # corrective pass changed without paying for (and diffing) a separate run.
    first_extraction: MeetingExtraction | None = None


def _norm(text: str) -> str:
    """Casefold and collapse whitespace, so a re-read that differs only in
    spacing or case still recognises the same item."""
    return " ".join(text.split()).casefold().rstrip(".!")


def _differs(a: BaseModel, b: BaseModel) -> bool:
    """Whether two items say different things. Ids are the model's numbering and
    confidence is its mood; neither is content a manager would call a revision."""
    ignore = {"id", "confidence"}
    return a.model_dump(exclude=ignore) != b.model_dump(exclude=ignore)


def _fresh_id(prefix: str, taken: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def _merge_items(first: list[T], second: list[T], text_of: Callable[[T], str],
                 prefix: str, taken: set[str]) -> tuple[list[T], set[str]]:
    """Fold `second` into `first`, matching on content rather than id.

    Ids cannot be trusted across passes: the extract prompt numbers items from
    `a1` on every run, so pass 2's `a1` is whatever it listed first — not
    necessarily pass 1's `a1`. A pass-2 item matches a pass-1 item when it
    states the same text, or when it reuses the id AND quotes the same source
    (a genuine correction that rephrased the text).

    A match keeps the pass-1 id — gaps, human edits, and UI state all refer to
    it. An unmatched item is new, and gets a fresh id if its own is taken.
    `taken` is shared across all record lists, so no two records ever share an
    id. Returns the merged list and the ids added or changed.
    """
    merged = {x.id: x for x in first}
    unclaimed = dict(merged)
    by_text = {_norm(text_of(x)): x.id for x in first}
    changed: set[str] = set()

    for x in second:
        match_id = by_text.get(_norm(text_of(x)))
        if match_id not in unclaimed:
            same = unclaimed.get(x.id)
            match_id = (x.id if same is not None
                        and _norm(same.source_quote) == _norm(x.source_quote) else None)
        if match_id is not None:
            del unclaimed[match_id]
            if _differs(merged[match_id], x):
                merged[match_id] = x.model_copy(update={"id": match_id})
                changed.add(match_id)
            continue
        new_id = x.id if x.id not in taken else _fresh_id(prefix, taken)
        taken.add(new_id)
        merged[new_id] = x.model_copy(update={"id": new_id})
        changed.add(new_id)

    return list(merged.values()), changed


def merge_extractions(first: MeetingExtraction,
                      second: MeetingExtraction) -> tuple[MeetingExtraction, set[str]]:
    """Fold a corrective second pass into the first.

    Adds new items, updates matching ones, and NEVER drops an item the first
    pass found — a human may already have edited it, and losing their work to a
    model's second opinion is not a correction.

    Decisions get the same treatment, and for the same reason: a human may have
    edited one, and they flow straight into the drafted message.

    Returns the merged extraction and the action-item ids the second pass added
    or changed, so the UI can mark them.
    """
    taken = {
        record.id
        for records in (
            first.action_items,
            first.decisions,
            first.risks,
            first.dependencies,
            first.learnings,
        )
        for record in records
    }
    action_items, corrected = _merge_items(
        first.action_items, second.action_items, lambda a: a.task, "a", taken)
    decisions, _ = _merge_items(
        first.decisions, second.decisions, lambda d: d.decision, "d", taken)
    risks, _ = _merge_items(
        first.risks, second.risks, lambda risk: risk.description, "r", taken)
    dependencies, _ = _merge_items(
        first.dependencies, second.dependencies,
        lambda dependency: dependency.description, "dep", taken)
    learnings, _ = _merge_items(
        first.learnings, second.learnings, lambda learning: learning.lesson, "l", taken)

    return (
        MeetingExtraction(
            summary=second.summary or first.summary,
            participants=second.participants or first.participants,
            decisions=decisions,
            action_items=action_items,
            risks=risks,
            dependencies=dependencies,
            learnings=learnings,
        ),
        corrected,
    )


# Record lists in the order ids are claimed, with each kind's id prefix. The
# order matches `merge_extractions`; the first occurrence of an id keeps it.
_RECORD_KINDS = (
    ("action_items", "a"),
    ("decisions", "d"),
    ("risks", "r"),
    ("dependencies", "dep"),
    ("learnings", "l"),
)


def make_ids_unique(extraction: MeetingExtraction) -> MeetingExtraction:
    """Give every record an id no other record in the extraction uses.

    Gaps, human edits, and UI state all refer to a record by id alone, and gaps
    dedupe on (target_id, type) — so a decision and a dependency both called
    `d1` share one evidence gap, and one of them escapes the check. The prompt
    asks for unique ids; this makes it true regardless of what the model did.

    The first occurrence keeps its id; each later duplicate gets a fresh id
    with its own kind's prefix, chosen to avoid every id already present.
    """
    taken = {record.id for field_name, _ in _RECORD_KINDS
             for record in getattr(extraction, field_name)}
    seen: set[str] = set()
    update: dict[str, list] = {}
    for field_name, prefix in _RECORD_KINDS:
        records = []
        for record in getattr(extraction, field_name):
            if record.id in seen:
                new_id = _fresh_id(prefix, taken)
                taken.add(new_id)
                record = record.model_copy(update={"id": new_id})
            seen.add(record.id)
            records.append(record)
        update[field_name] = records
    return extraction.model_copy(update=update)


def run_agent_loop(notes: str, client: LLMClient, *,
                   context: MeetingContext | None = None,
                   max_passes: int | None = None) -> LoopOutcome:
    """Extract, evaluate, decide whether another pass would help, exit.

    Exhausting the budget is a normal outcome, not an error: it produces the
    same gated review screen with a note that the agent tried and could not
    resolve the remainder.

    Honest note on the budget: the two-pass cap is structural, not arithmetic.
    This function has no loop construct — it reads `budget` exactly once, at
    `if budget > 1`, so the constant only gates whether the corrective pass is
    attempted at all. Setting `MAX_PASSES = 3` would change nothing; anything
    above 1 behaves identically to 2. Raising the cap for real means writing
    the loop, not editing the constant.
    """
    context = context or MeetingContext()
    budget = max_passes if max_passes is not None else config.MAX_PASSES

    extract = run_extract(notes, client, context=context)
    raw = extract.raw
    # Before anything refers to a record by id: review, gaps, triage, merge.
    extraction = make_ids_unique(extract.extraction)
    review = run_review(notes, extraction, client)
    tokens = extract.tokens + review.tokens
    latency = extract.latency_ms + review.latency_ms

    review_result = review.review
    notes_for_manager: list[str] = []
    corrected: set[str] = set()
    passes = 1

    if budget > 1 and review_result.gaps:
        triage = run_triage(notes, extraction, review_result.gaps, client)
        tokens += triage.tokens
        latency += triage.latency_ms
        feedback = [t.supporting_quote for t in triage.triages
                    if t.verdict is TriageVerdict.SELF_RESOLVABLE and t.supporting_quote]

        if feedback:
            try:
                second = run_extract(notes, client, context=context, feedback=feedback)
            except LLMError as exc:
                notes_for_manager.append(
                    f"The agent tried a second pass to resolve {len(feedback)} gap(s) "
                    f"but it failed ({exc}). The first pass is shown unchanged.")
            else:
                passes = 2
                tokens += second.tokens
                latency += second.latency_ms
                extraction, corrected = merge_extractions(extraction, second.extraction)
                raw = second.raw
                re_review = run_review(notes, extraction, client)
                tokens += re_review.tokens
                latency += re_review.latency_ms
                if re_review.failed:
                    # Keep what the first review found. The fallback carries only
                    # structural gaps, so taking it as-is would silently drop a
                    # CONFLICT or ambiguity warning that had been blocking the
                    # draft. Deterministic types are skipped: the backstop below
                    # recomputes them against the merged extraction, and a stale
                    # one would re-flag an owner or quote pass 2 just fixed.
                    kept = [g for g in review_result.gaps
                            if g.type not in _DETERMINISTIC_TYPES]
                    review_result = ReviewResult(
                        gaps=merge_gaps(kept, re_review.review.gaps),
                        overall_confidence=review_result.overall_confidence,
                        reviewer_notes=re_review.review.reviewer_notes,
                    )
                    notes_for_manager.append(
                        "The re-check after the second pass failed, so the first "
                        "review's warnings are shown.")
                else:
                    review_result = re_review.review
                if corrected:
                    notes_for_manager.append(
                        f"The agent re-read the notes and revised {len(corrected)} item(s).")
                else:
                    notes_for_manager.append(
                        "The agent re-read the notes but found nothing further to change.")
        else:
            notes_for_manager.append(
                "The agent judged every remaining gap to need a person, so it did "
                "not spend a second pass.")

    # The backstop runs on whatever the final pass produced. Belt and braces:
    # run_review already merges it, but the merge above can change any record.
    review_result = ReviewResult(
        gaps=merge_with_deterministic(
            normalize_evidence_severity(review_result.gaps, extraction),
            detect_structural_gaps(extraction),
            detect_evidence_gaps(extraction, notes),
        ),
        overall_confidence=review_result.overall_confidence,
        reviewer_notes=review_result.reviewer_notes,
    )

    return LoopOutcome(extraction=extraction, review=review_result, passes=passes,
                       tokens=tokens, latency_ms=latency, raw=raw,
                       notes_for_manager=notes_for_manager,
                       corrected_item_ids=corrected,
                       first_extraction=extract.extraction)
