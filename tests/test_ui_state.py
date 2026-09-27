import pytest

from ui.state import (DRAFT_SESSION_KEYS, MEETING_SESSION_KEYS, MIN_NOTES_CHARS, Stage,
                      can_analyze, clear_draft, clear_meeting_state, notes_warning,
                      parse_deadline)


def test_cannot_analyze_empty_notes():
    assert can_analyze("") is False


def test_cannot_analyze_notes_below_the_minimum():
    assert can_analyze("too short") is False


def test_can_analyze_sufficient_notes():
    assert can_analyze("x" * MIN_NOTES_CHARS) is True


def test_whitespace_does_not_count_toward_the_minimum():
    assert can_analyze(" " * 200) is False


def test_long_notes_produce_a_truncation_warning():
    """PRD §5.6: warn above 10,000 words rather than failing at the context limit."""
    warning = notes_warning("word " * 10_001)
    assert warning is not None
    assert "10,000" in warning


def test_normal_notes_produce_no_warning():
    assert notes_warning("word " * 500) is None


def test_stages_are_ordered_input_review_export():
    """The meeting workflow keeps its order; Ask meetings sits outside it."""
    assert list(Stage) == [Stage.INPUT, Stage.REVIEW, Stage.EXPORT, Stage.QUERY]


def test_parse_deadline_accepts_iso():
    assert parse_deadline("2026-10-02") == "2026-10-02"


def test_parse_deadline_treats_blank_as_none():
    assert parse_deadline("") is None
    assert parse_deadline("   ") is None


def test_parse_deadline_rejects_prose():
    with pytest.raises(ValueError, match="not a date"):
        parse_deadline("next Friday")


def test_parse_deadline_rejects_wrong_format():
    with pytest.raises(ValueError, match="not a date"):
        parse_deadline("02/10/2026")


def test_clear_draft_removes_every_draft_attempt_key():
    """The draft and the draft error belong to one attempt and must go together:
    a stale draft_error left behind would suppress Approve/Download on the next
    meeting."""
    session = {"draft": "text", "draft_error": "boom", "stage": "export"}
    clear_draft(session)
    assert session == {"stage": "export"}


def test_clear_draft_is_safe_when_nothing_was_drafted():
    session = {"stage": "input"}
    clear_draft(session)
    assert session == {"stage": "input"}


def test_clear_meeting_state_drops_every_per_meeting_key():
    session = {"draft": "d", "draft_error": "e", "loop_notes": ["n"],
              "corrected_item_ids": {"x"}, "owner_hints": (),
              "prior_commitments": (), "meeting_id": "m1"}
    clear_meeting_state(session)
    assert set(session) == {"meeting_id"}, "a per-meeting key survived the switch"


def test_clear_meeting_state_is_safe_when_nothing_is_set():
    session = {}
    clear_meeting_state(session)
    assert session == {}


def test_clear_draft_still_only_touches_draft_keys():
    """Resetting the draft on the SAME meeting must not wipe the loop's notes."""
    session = {"draft": "d", "draft_error": "e", "loop_notes": ["n"]}
    clear_draft(session)
    assert session == {"loop_notes": ["n"]}


def test_every_draft_key_is_also_cleared_on_a_meeting_switch():
    """The asymmetry that must hold in one direction only.

    A draft key that was not also a per-meeting key would survive a meeting
    switch and render against a meeting it did not come from. Deriving the
    tuple makes that unrepresentable; this pins it so a future edit that
    un-derives them fails here rather than in the UI.
    """
    assert set(DRAFT_SESSION_KEYS) <= set(MEETING_SESSION_KEYS)


def test_meeting_keys_have_no_duplicates():
    assert len(MEETING_SESSION_KEYS) == len(set(MEETING_SESSION_KEYS))
