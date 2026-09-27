"""The three-step agent pipeline: extract -> review -> draft.

Step 3 is gated. `run_draft` re-checks the gate itself rather than trusting the
UI to have disabled the button, so a UI bug cannot produce an ungated draft.
"""
import json
import re
from dataclasses import dataclass

from agent import prompts
from agent.evidence import quote_supports
from agent.gaps import (GateBlockedError, detect_evidence_gaps, detect_structural_gaps,
                        merge_with_deterministic, normalize_evidence_severity,
                        open_blocking)
from agent.llm_client import LLMClient, LLMError
from agent.schemas import (
    ActionItem,
    Decision,
    Gap,
    GapTriage,
    GapType,
    MeetingContext,
    MeetingExtraction,
    ReviewResult,
    TriageResult,
    TriageVerdict,
    normalize_optional_text,
)


@dataclass
class ExtractionOutcome:
    extraction: MeetingExtraction
    raw: str
    tokens: int
    latency_ms: int


def build_extract_user(notes: str, context: MeetingContext,
                       feedback: list[str] | None = None) -> str:
    """Assemble the extraction user message.

    An empty context with no feedback returns exactly the string this function
    replaced, so a first-ever meeting behaves identically to the previous
    pipeline. `context.owner_hints` is deliberately NOT read here — owner hints
    must never reach a model.
    """
    parts = []
    if context.prior_commitments:
        lines = [f"- {c.task} — {c.owner}, due {c.deadline} "
                 f"({c.meeting_title}, {c.meeting_date})"
                 for c in context.prior_commitments]
        parts.append("BACKGROUND — commitments from earlier meetings. Context for\n"
                     "understanding shorthand only; not facts about today's meeting.\n"
                     "No completion tracking exists, so these may already be done.\n\n"
                     + "\n".join(lines))
    if feedback:
        parts.append("MISSED — a reviewer believes you overlooked these. Include each\n"
                     "one only if the quote genuinely supports it.\n\n"
                     + "\n".join(f"- {f}" for f in feedback))
    parts.append(f"Meeting notes:\n\n{notes}")
    return "\n\n".join(parts)


def run_extract(notes: str, client: LLMClient, *,
                context: MeetingContext | None = None,
                feedback: list[str] | None = None) -> ExtractionOutcome:
    """Step 1 — notes to structure. Full autonomy."""
    user = build_extract_user(notes, context or MeetingContext(), feedback)
    result = client.parse(prompts.EXTRACT_SYSTEM, user,
                          MeetingExtraction, temperature=0.1)
    return ExtractionOutcome(extraction=result.value, raw=result.raw,
                             tokens=result.tokens, latency_ms=result.latency_ms)


@dataclass
class ReviewOutcome:
    review: ReviewResult
    raw: str
    tokens: int
    latency_ms: int
    failed: bool = False     # the model call failed; `review` is the structural fallback


def _extraction_digest(extraction: MeetingExtraction) -> str:
    """Compact view of the extraction, so the reviewer sees ids alongside content."""
    return json.dumps({
        "decisions": [{"id": d.id, "decision": d.decision,
                       "source_quote": d.source_quote} for d in extraction.decisions],
        "action_items": [{"id": a.id, "task": a.task, "owner": a.owner,
                          "deadline": a.deadline, "source_quote": a.source_quote}
                         for a in extraction.action_items],
        "risks": [r.model_dump() for r in extraction.risks],
        "dependencies": [d.model_dump() for d in extraction.dependencies],
        "learnings": [l.model_dump() for l in extraction.learnings],
    }, indent=2)


def run_review(notes: str, extraction: MeetingExtraction,
               client: LLMClient) -> ReviewOutcome:
    """Step 2 — the agent critiques its own extraction.

    The deterministic backstop runs whatever the model says, so a reviewer that
    approves everything cannot unblock the gate.
    """
    structural = detect_structural_gaps(extraction)
    evidence = detect_evidence_gaps(extraction, notes)
    user = (f"Original meeting notes:\n\n{notes}\n\n"
            f"Extraction to review:\n\n{_extraction_digest(extraction)}")
    failed = False
    try:
        result = client.parse(prompts.REVIEW_SYSTEM, user, ReviewResult, temperature=0.0)
        model_review: ReviewResult = result.value
        raw, tokens, latency_ms = result.raw, result.tokens, result.latency_ms
        notes_text = model_review.reviewer_notes
        confidence = model_review.overall_confidence
        model_gaps = model_review.gaps
    except LLMError as exc:
        model_gaps, raw, tokens, latency_ms = [], "", 0, 0
        confidence = 0.0
        failed = True
        notes_text = (f"Reviewer step failed ({exc}); using deterministic gap "
                      f"detection as a fallback. Warnings may be missing.")

    model_gaps = normalize_evidence_severity(model_gaps, extraction)
    merged = merge_with_deterministic(model_gaps, structural, evidence)
    return ReviewOutcome(
        review=ReviewResult(gaps=merged, overall_confidence=confidence,
                            reviewer_notes=notes_text),
        raw=raw, tokens=tokens, latency_ms=latency_ms, failed=failed)


@dataclass
class DraftOutcome:
    text: str
    tokens: int
    latency_ms: int


def run_draft(*, meeting_title: str, decisions: list[Decision],
              action_items: list[ActionItem], gaps: list[Gap],
              resolved_ids: set[str], client: LLMClient) -> DraftOutcome:
    """Step 3 — the follow-up message. Gated on human resolution of blocking gaps.

    The gate is re-checked here even though the UI disables the button, so a UI
    bug cannot produce a draft that skips human confirmation.
    """
    blocking = open_blocking(gaps, resolved_ids)
    if blocking:
        summary = "; ".join(f"{g.type.value} on {g.target_id}" for g in blocking)
        raise GateBlockedError(
            f"Cannot draft: {len(blocking)} unresolved blocking gap(s) — {summary}")

    # The gap bookkeeping above is the caller's; this is ours. An item can have
    # its gap marked resolved while the field itself is still empty (or be added
    # by a human after gap detection ran), and DRAFT_SYSTEM promises the model
    # every item has a confirmed owner and deadline. Verify that directly.
    incomplete = [a for a in action_items
                  if normalize_optional_text(a.owner) is None
                  or normalize_optional_text(a.deadline) is None]
    if incomplete:
        summary = "; ".join(f"{a.task!r} (owner={a.owner!r}, deadline={a.deadline!r})"
                            for a in incomplete)
        raise GateBlockedError(
            f"Cannot draft: {len(incomplete)} action item(s) still missing an owner "
            f"or deadline — {summary}")

    lines = [f"Meeting: {meeting_title}", "", "Decisions:"]
    lines += [f"- {d.decision}" for d in decisions] or ["- (none recorded)"]
    lines += ["", "Approved action items:"]
    lines += [f"- {a.task} — owner: {a.owner}, due: {a.deadline}"
              for a in action_items] or ["- (none recorded)"]
    user = "\n".join(lines)

    result = client.complete(prompts.DRAFT_SYSTEM, user, temperature=0.4)
    return DraftOutcome(text=result.value, tokens=result.tokens,
                        latency_ms=result.latency_ms)


_NAME = re.compile(r"\b[A-Z][a-z]{1,}\b")


def notes_name_someone(notes: str) -> bool:
    """Whether the notes contain any capitalised word that could be a person.

    Deliberately crude and deliberately generous: this decides only whether it
    is worth ASKING the model if an owner is recoverable. A false positive
    costs one model call; a false negative sends a gap to a human, which is
    the outcome the product prefers anyway.
    """
    return _NAME.search(notes) is not None


def owner_gap_is_hopeless(gap: Gap, notes: str) -> bool:
    """A MISSING_OWNER gap the notes cannot possibly answer.

    Spec §4.1: such a gap is NEEDS_HUMAN by definition, without consulting the
    model at all. Without this, a model can 'resolve' a missing owner by
    copying a name out of the BACKGROUND block of prior commitments — a name
    that appears nowhere in today's notes and that no human confirmed.
    """
    return gap.type is GapType.MISSING_OWNER and not notes_name_someone(notes)


@dataclass
class TriageOutcome:
    triages: list[GapTriage]
    raw: str
    tokens: int
    latency_ms: int


def run_triage(notes: str, extraction: MeetingExtraction, gaps: list[Gap],
               client: LLMClient) -> TriageOutcome:
    """Step 3 — decide, per gap, whether another extraction pass would help.

    Two deterministic checks bracket the model. Before it: a MISSING_OWNER gap
    whose notes name nobody at all is NEEDS_HUMAN by definition and never
    reaches the model (`owner_gap_is_hopeless`). After it: every
    `self_resolvable` verdict is verified against the notes before it is
    believed. A failure here degrades to "everything needs a human", which is
    exactly today's behaviour — never to "no gaps".
    """
    if not gaps:
        return TriageOutcome(triages=[], raw="", tokens=0, latency_ms=0)

    # Spec §4.1, the unconditional half: a missing owner the notes cannot answer
    # is settled here, before the model is consulted at all. Deciding it first
    # also means it cannot be talked out of by a quote that is verbatim but
    # answers nothing — the bypass that let a name from the BACKGROUND block of
    # prior commitments become an owner nobody confirmed.
    hopeless = [g for g in gaps if owner_gap_is_hopeless(g, notes)]
    remaining = [g for g in gaps if not owner_gap_is_hopeless(g, notes)]
    predetermined = [
        GapTriage(gap_id=g.id, verdict=TriageVerdict.NEEDS_HUMAN,
                  supporting_quote=None,
                  reasoning="No candidate name appears anywhere in the notes.")
        for g in hopeless]

    def _all_human(reason: str) -> TriageOutcome:
        return TriageOutcome(
            triages=predetermined + [
                GapTriage(gap_id=g.id, verdict=TriageVerdict.NEEDS_HUMAN,
                          supporting_quote=None, reasoning=reason)
                for g in remaining],
            raw="", tokens=0, latency_ms=0)

    # Every gap was settled deterministically. Spending a model call here would
    # buy nothing that could change a verdict.
    if not remaining:
        return TriageOutcome(triages=predetermined, raw="", tokens=0, latency_ms=0)

    gap_digest = json.dumps(
        [{"gap_id": g.id, "type": g.type.value, "target_id": g.target_id,
          "explanation": g.explanation} for g in remaining], indent=2)
    user = (f"Original meeting notes:\n\n{notes}\n\n"
            f"Extraction:\n\n{_extraction_digest(extraction)}\n\n"
            f"Gaps to triage:\n\n{gap_digest}")

    try:
        result = client.parse(prompts.TRIAGE_SYSTEM, user, TriageResult,
                              temperature=0.0)
    except LLMError as exc:
        return _all_human(f"Triage step failed ({exc}); treating as human-only.")

    # Only a verdict on a gap the model was actually shown counts, and only the
    # first per gap. An invented gap_id, or one for a gap already settled above,
    # would otherwise feed its quote into a second pass all the same.
    asked = {g.id for g in remaining}
    verified: list[GapTriage] = []
    for triage in result.value.triages:
        if triage.gap_id not in asked:
            continue
        asked.discard(triage.gap_id)
        if (triage.verdict is TriageVerdict.SELF_RESOLVABLE
                and not quote_supports(triage.supporting_quote, notes)):
            verified.append(triage.model_copy(update={
                "verdict": TriageVerdict.NEEDS_HUMAN,
                "reasoning": ("Claimed self-resolvable, but the supporting quote "
                              "is not in the notes."),
            }))
        else:
            verified.append(triage)
    return TriageOutcome(triages=predetermined + verified, raw=result.raw,
                         tokens=result.tokens, latency_ms=result.latency_ms)
