"""Presentation logic for gaps. Pure functions, no Streamlit."""
from agent.gaps import is_blocked, open_blocking
from agent.schemas import (Gap, GapType, OwnerHint, PriorCommitment, Severity,
                           normalize_optional_text)

_LABELS = {
    GapType.MISSING_OWNER: "🔴 No owner",
    GapType.MISSING_DEADLINE: "🔴 No deadline",
    GapType.CONFLICTING_DECISION: "🔴 Conflicting decision",
    GapType.AMBIGUOUS_TASK: "🟡 Vague wording",
    GapType.UNRESOLVED_QUESTION: "🟡 Open question",
    GapType.UNSUPPORTED_EVIDENCE: "🔎 Quote not found in notes",
}


def badge(gap: Gap) -> str:
    return _LABELS[gap.type]


def gate_message(open_gaps: list[Gap]) -> str:
    count = len(open_gaps)
    if count == 0:
        return ""
    noun = "detail needs" if count == 1 else "details need"
    return f"{count} {noun} your input before I can draft the follow-up."


def gaps_for_item(gaps: list[Gap], item_id: str) -> list[Gap]:
    return [g for g in gaps if g.target_id == item_id]


def sort_items_gaps_first(items: list[dict], gaps: list[Gap],
                          resolved_ids: set[str] = frozenset()) -> list[dict]:
    """Stable sort putting items with unresolved blocking gaps at the top."""
    blocked = {g.target_id for g in gaps
               if g.severity is Severity.BLOCKING and g.id not in resolved_ids}
    return sorted(items, key=lambda i: i["id"] not in blocked)


# The only gap types an edit to the data can ever discharge. Everything else —
# a contradiction between two decisions, above all — is a judgement call the
# data cannot express, so the human has to say it is settled.
DATA_FIXABLE_TYPES: frozenset[GapType] = frozenset({
    GapType.MISSING_OWNER,
    GapType.MISSING_DEADLINE,
})


def gap_is_satisfied(gap: Gap, owner: str | None, deadline: str | None) -> bool:
    """Whether the data now satisfies this gap. Moved out of the view: it decides
    whether a badge shows, so it needs tests."""
    if gap.type is GapType.MISSING_OWNER:
        return normalize_optional_text(owner) is not None
    if gap.type is GapType.MISSING_DEADLINE:
        return normalize_optional_text(deadline) is not None
    return False  # not data-fixable — see needs_manual_resolution


def needs_manual_resolution(gap: Gap) -> bool:
    """True when no edit to the data could ever satisfy this gap.

    `gap_is_satisfied` returns True only for DATA_FIXABLE_TYPES, and
    `db.resolve_gap` is otherwise reached only from the action-item Save/Delete
    handlers. So a blocking gap of any other type — CONFLICTING_DECISION above
    all, which is in `agent.gaps.BLOCKING_TYPES` — has no route into
    `resolved_ids` at all unless the view renders an explicit control for it.
    This predicate is what tells the view to render one, and it is what keeps
    the two halves in step if a new blocking type is ever added.
    """
    return gap.type not in DATA_FIXABLE_TYPES


def unresolved_manual_gaps(gaps: list[Gap], target_id: str,
                           resolved_ids: set[str]) -> list[Gap]:
    """Open blocking gaps on this target that only a human statement can discharge."""
    return [g for g in open_blocking(gaps, resolved_ids)
            if g.target_id == target_id and needs_manual_resolution(g)]


def items_missing_fields(items: list[dict]) -> list[dict]:
    """Items run_draft would reject regardless of gaps — blank owner or deadline.

    Mirrors the data check in agent.pipeline.run_draft. The UI must gate on the
    same condition, or it shows an enabled button that raises on click.
    """
    return [i for i in items
            if normalize_optional_text(i.get("owner")) is None
            or normalize_optional_text(i.get("deadline")) is None]


def draft_blocked(items: list[dict], gaps: list[Gap], resolved_ids: set[str]) -> bool:
    """The single source of truth for the Draft button's disabled state."""
    return is_blocked(gaps, resolved_ids) or bool(items_missing_fields(items))


def unattached_gaps(gaps: list[Gap], item_ids: set[str], decision_ids: set[str],
                    resolved_ids: set[str], *, risk_ids: set[str] = frozenset(),
                    dependency_ids: set[str] = frozenset(),
                    learning_ids: set[str] = frozenset()) -> list[Gap]:
    """Unresolved gaps whose target_id matches no rendered record.

    The extraction prompt asks the model for a real id but nothing validates
    it, so a hallucinated or malformed target_id ("d1,d2", "", a task string)
    otherwise has no location on screen. Blocking gaps need a resolution path;
    warnings still need to remain visible even though they do not affect the
    draft gate. This helper is display-only and deliberately does not call
    `open_blocking`.

    `risk_ids`/`dependency_ids`/`learning_ids` are keyword-only so every
    existing positional call (`unattached_gaps(gaps, items, decisions,
    resolved)`) keeps working unchanged. Without them, a gap targeting a
    risk/dependency/learning row that IS rendered on screen would still be
    reported here as "unattached", duplicating its control.
    """
    known = set(item_ids) | set(decision_ids) | set(risk_ids) | set(dependency_ids) | set(learning_ids)
    return [g for g in gaps
            if g.id not in resolved_ids and g.target_id not in known]


def owner_suggestion(hints: tuple[OwnerHint, ...], item: dict) -> str | None:
    """A hint for a blank owner field, drawn from past human corrections.

    A suggestion, never a value. The field stays blank and stays blocking —
    memory informs the manager's decision; it does not make it. Nothing here
    is ever sent to a model.

    The copy claims only what the data supports, which is very little: this
    function ignores `item` except to check the owner is blank, always renders
    `hints[0]`, and `hints` is ordered by raw assignment count. There is no
    similarity computation anywhere in this codebase, so the caption cannot say
    "similar work" — every blank owner on the screen gets the same caption, and
    saying otherwise would be exactly the overclaiming this product refuses
    everywhere else.

    `OwnerHint.example_task` is deliberately NOT rendered. It is SQL `MIN(task)`
    — alphabetically first, not most recent and not most relevant — so shown as
    "e.g." beside a name it reads as evidence of a match that was never
    computed. It stays on the dataclass as the query's own output; it is not
    fit to be presented to a manager as a reason.
    """
    if not hints or normalize_optional_text(item.get("owner")) is not None:
        return None
    top = hints[0]
    times = "once" if top.times_assigned == 1 else f"{top.times_assigned} times"
    return (f"You have previously assigned work to **{top.owner}** ({times}). "
            f"Confirm or type someone else.")


# Shown verbatim beneath the prior-commitments list. Every clause is a limitation
# the query cannot back up, and the manager needs all three to read a remembered
# name correctly — above all that these were given to the agent, which is what
# makes "where did that suggestion come from?" answerable on screen.
PRIOR_COMMITMENTS_CAPTION = (
    "These are commitments from earlier meetings, not from today's notes. There is "
    "no completion tracking, so some may already be done. The agent was given them "
    "as background when it read today's notes."
)


def format_prior_commitment(commitment: PriorCommitment) -> str:
    """One remembered commitment, as a single line for the review screen.

    Pure so it can be tested; the view is left as wiring. The meeting title and
    date are not decoration — they are how a manager tells a suggested name that
    came from last week's meeting apart from one today's notes actually stated.
    """
    return (f"{commitment.task} — {commitment.owner}, due {commitment.deadline} "
            f"({commitment.meeting_title}, {commitment.meeting_date})")


def prior_commitment_lines(commitments: tuple[PriorCommitment, ...]) -> list[str]:
    """Every remembered commitment, in the order memory returned them."""
    return [format_prior_commitment(c) for c in commitments]
