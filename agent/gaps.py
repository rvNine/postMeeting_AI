"""Gap taxonomy and the human-in-the-loop gate.

The model is asked to find gaps, but it is never trusted to be the only thing
that finds them. `detect_structural_gaps` runs unconditionally after the review
step and re-flags anything mechanically detectable, so a reviewer that rubber-
stamps its own extraction cannot unblock the gate.
"""
from agent.evidence import quote_supports
from agent.schemas import Gap, GapType, MeetingExtraction, Severity, normalize_optional_text

BLOCKING_TYPES: frozenset[GapType] = frozenset({
    GapType.MISSING_OWNER,
    GapType.MISSING_DEADLINE,
    GapType.CONFLICTING_DECISION,
})


class GateBlockedError(Exception):
    """Raised when drafting is attempted with blocking gaps still open."""


def _is_blank(value: str | None) -> bool:
    return normalize_optional_text(value) is None


def _structural_id(target_id: str, gap_type: GapType) -> str:
    """Stable id, so resolving a gap survives a re-render."""
    return f"struct::{target_id}::{gap_type.value}"


def detect_structural_gaps(extraction: MeetingExtraction) -> list[Gap]:
    """Deterministic backstop. Runs regardless of what the reviewer returned."""
    gaps: list[Gap] = []
    for item in extraction.action_items:
        if _is_blank(item.owner):
            gaps.append(Gap(
                id=_structural_id(item.id, GapType.MISSING_OWNER),
                type=GapType.MISSING_OWNER,
                severity=Severity.BLOCKING,
                target_id=item.id,
                explanation=f"No owner is stated in the notes for: {item.task!r}",
                suggested_question=f"Who is taking this on: {item.task}?",
            ))
        if _is_blank(item.deadline):
            gaps.append(Gap(
                id=_structural_id(item.id, GapType.MISSING_DEADLINE),
                type=GapType.MISSING_DEADLINE,
                severity=Severity.BLOCKING,
                target_id=item.id,
                explanation=f"No deadline is stated in the notes for: {item.task!r}",
                suggested_question=f"When does this need to be done: {item.task}?",
            ))
    return gaps


def detect_evidence_gaps(extraction: MeetingExtraction, notes: str) -> list[Gap]:
    """Return gaps for empty or unsupported record source quotes."""
    gaps: list[Gap] = []
    record_groups = (
        ("decision", extraction.decisions, Severity.BLOCKING),
        ("action_item", extraction.action_items, Severity.BLOCKING),
        ("risk", extraction.risks, Severity.WARNING),
        ("dependency", extraction.dependencies, Severity.WARNING),
        ("learning", extraction.learnings, Severity.WARNING),
    )
    for record_kind, records, severity in record_groups:
        for record in records:
            if quote_supports(record.source_quote, notes):
                continue
            gaps.append(Gap(
                id=f"evidence::{record_kind}::{record.id}",
                type=GapType.UNSUPPORTED_EVIDENCE,
                severity=severity,
                target_id=record.id,
                explanation=(
                    f"The source quote for {record_kind} {record.id!r} is not "
                    "supported by the meeting notes."
                ),
                suggested_question=(
                    f"What in the meeting notes supports this {record_kind}?"
                ),
            ))
    return gaps


def merge_gaps(model_gaps: list[Gap], structural_gaps: list[Gap]) -> list[Gap]:
    """Union the two sources, deduplicating on (target_id, type).

    The model's wording is richer, so when both sources flag the same thing the
    model's Gap is kept. Structural gaps the model missed are always added.
    """
    merged: dict[tuple[str, GapType], Gap] = {
        (g.target_id, g.type): g for g in model_gaps
    }
    for gap in structural_gaps:
        merged.setdefault((gap.target_id, gap.type), gap)
    return list(merged.values())


def normalize_evidence_severity(gaps: list[Gap],
                                extraction: MeetingExtraction) -> list[Gap]:
    """Make record kind authoritative for every unsupported-evidence gap.

    Deterministic quote matching catches missing/non-verbatim quotes, but the
    reviewer can also flag a quote that appears verbatim while being irrelevant
    to the extracted claim. Such a model-only gap has no deterministic collision,
    so its model-supplied severity must still be normalized here.
    """
    blocking_ids = ({decision.id for decision in extraction.decisions}
                    | {item.id for item in extraction.action_items})
    warning_ids = ({risk.id for risk in extraction.risks}
                   | {dependency.id for dependency in extraction.dependencies}
                   | {learning.id for learning in extraction.learnings})
    normalized: list[Gap] = []
    for gap in gaps:
        severity = None
        if gap.type is GapType.UNSUPPORTED_EVIDENCE:
            if gap.target_id in blocking_ids:
                severity = Severity.BLOCKING
            elif gap.target_id in warning_ids:
                severity = Severity.WARNING
        if severity is not None and gap.severity is not severity:
            gap = gap.model_copy(update={"severity": severity})
        normalized.append(gap)
    return normalized


def merge_with_deterministic(model_gaps: list[Gap], structural: list[Gap],
                             evidence: list[Gap]) -> list[Gap]:
    """Merge model gaps with the deterministic backstop, evidence first.

    `merge_gaps` lets the model's Gap win a (target_id, type) tie for its
    wording. For evidence that tie is a downgrade route: a model WARNING on a
    decision's unsupported quote would replace the deterministic BLOCKING gap
    and open the gate. So model gaps colliding with a deterministic evidence
    gap are dropped before merging — the deterministic check is authoritative.
    """
    evidence_keys = {(gap.target_id, gap.type) for gap in evidence}
    kept = [gap for gap in model_gaps if (gap.target_id, gap.type) not in evidence_keys]
    return merge_gaps(kept, structural + evidence)


def open_blocking(gaps: list[Gap], resolved_ids: set[str]) -> list[Gap]:
    """Filter to unresolved gaps that are blocking.

    A gap is blocking if its severity is BLOCKING or its type is in BLOCKING_TYPES.
    The OR exists because a model can emit a gap with a blocking type but warning
    severity, attempting to downgrade it. The taxonomy wins — we ask the human.
    """
    return [g for g in gaps
            if (g.severity is Severity.BLOCKING or g.type in BLOCKING_TYPES)
            and g.id not in resolved_ids]


def is_blocked(gaps: list[Gap], resolved_ids: set[str]) -> bool:
    """Single source of truth for whether step 3 may run."""
    return bool(open_blocking(gaps, resolved_ids))
