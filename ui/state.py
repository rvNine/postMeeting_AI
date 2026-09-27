"""Pure UI decision logic. No Streamlit imports — that is what makes it testable."""
from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from query.models import QueryFilters

MIN_NOTES_CHARS = 50
MAX_NOTES_WORDS = 10_000


class Stage(StrEnum):
    INPUT = "input"
    REVIEW = "review"
    EXPORT = "export"
    QUERY = "query"


# Session keys belonging to one draft attempt. They are cleared together whenever
# the app moves to another meeting, so a stale draft — or a stale draft error —
# is never shown against a meeting it did not come from.
DRAFT_SESSION_KEYS = ("draft", "draft_error")


def clear_draft(session) -> None:
    """Drop every draft-attempt key from a session-state-like mapping.

    Takes the mapping rather than importing Streamlit: this module stays
    import-free of the UI framework so it can be unit tested with a plain dict.
    """
    for key in DRAFT_SESSION_KEYS:
        session.pop(key, None)


# Session keys scoped to ONE meeting. All of them must be cleared when the user
# switches meetings, or state from meeting A renders under meeting B — which is
# why this list exists rather than a bare pop of "draft".
#
# DERIVED from DRAFT_SESSION_KEYS, not restated. Every draft key is by definition
# also a per-meeting key, and when the two tuples were written out independently
# they already repeated "draft" and "draft_error" — so adding a third draft key
# to DRAFT_SESSION_KEYS alone would have left it silently surviving a meeting
# switch, which is the exact bug clear_meeting_state exists to prevent. The
# converse does NOT hold and must not: resetting the draft on the SAME meeting
# leaves the loop's notes and the memory context alone.
MEETING_SESSION_KEYS = DRAFT_SESSION_KEYS + ("loop_notes", "corrected_item_ids",
                                             "owner_hints", "prior_commitments")


def clear_meeting_state(session) -> None:
    """Drop every per-meeting key. Safe to call when none are set."""
    for key in MEETING_SESSION_KEYS:
        session.pop(key, None)


# Session keys owned by the Ask meetings view. Cleared whenever the user leaves
# it for a meeting, so an old answer never reappears against a new context.
QUERY_SESSION_KEYS = ("query_question", "query_filters", "query_result", "query_error")


def clear_query_state(session) -> None:
    """Drop every Ask meetings key. Safe to call when none are set."""
    for key in QUERY_SESSION_KEYS:
        session.pop(key, None)


def open_query_citation(session, meeting_id: str) -> None:
    """Route from a citation to that meeting's Review, as a meeting switch.

    Per-meeting state is cleared too, exactly as the sidebar does, so a draft
    from whichever meeting was open before never renders under this one.
    """
    clear_query_state(session)
    clear_meeting_state(session)
    session["meeting_id"] = meeting_id
    session["stage"] = Stage.REVIEW


def build_query_filters(*, date_range: Sequence[date] = (), meeting_id: str | None = None,
                        participant: str | None = None, owner: str | None = None,
                        record_type: str | None = None, severity: str | None = None,
                        program_phase: str | None = None) -> QueryFilters:
    """Turn the view's widget values into QueryFilters; unset choices filter nothing.

    A half-picked date range (start chosen, end not yet) filters from that day.
    """
    def chosen(value: str | None) -> str | None:
        return (value or "").strip() or None

    dates = tuple(date_range or ())
    return QueryFilters(
        date_from=dates[0].isoformat() if dates else None,
        date_to=dates[1].isoformat() if len(dates) > 1 else None,
        meeting_id=chosen(meeting_id), participant=chosen(participant), owner=chosen(owner),
        record_type=chosen(record_type), severity=chosen(severity),
        program_phase=chosen(program_phase),
    )


def can_analyze(notes: str) -> bool:
    return len(notes.strip()) >= MIN_NOTES_CHARS


def notes_warning(notes: str) -> str | None:
    word_count = len(notes.split())
    if word_count > MAX_NOTES_WORDS:
        return (f"These notes are {word_count:,} words. Anything over 10,000 words may "
                f"exceed the model's context window; only the first 10,000 will be sent.")
    return None


def truncate_notes(notes: str) -> str:
    words = notes.split()
    return " ".join(words[:MAX_NOTES_WORDS]) if len(words) > MAX_NOTES_WORDS else notes


def parse_deadline(text: str) -> str | None:
    """Normalise a typed deadline to ISO-8601, or None if blank.

    Raises ValueError on anything else — the caller shows the message inline.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(f"{text!r} is not a date. Use YYYY-MM-DD, e.g. 2026-10-02.") from None
