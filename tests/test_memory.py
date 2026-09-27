import pytest

from agent.schemas import ActionItem, MeetingExtraction, ReviewResult
from storage import db, memory


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    yield connection
    connection.close()


def _extraction(items):
    return MeetingExtraction(summary="s", participants=["Priya"], decisions=[],
                             action_items=items)


_EMPTY_REVIEW = ReviewResult(gaps=[], overall_confidence=0.9, reviewer_notes="")


def _meeting(conn, title, date, items):
    meeting_id = db.save_meeting(conn, title=title, meeting_date=date, raw_notes="n")
    db.save_extraction(conn, meeting_id, _extraction(items), _EMPTY_REVIEW,
                       model="m", prompt_version="v2", tokens_used=1, latency_ms=1,
                       raw_response="{}")
    return meeting_id


def test_owner_hints_finds_a_human_supplied_owner(conn):
    """The agent left it blank; a human filled it in. That is the signal."""
    item = ActionItem(id="a1", task="Add error alerting", owner=None, deadline=None,
                      source_quote="q", confidence=0.7)
    meeting_id = _meeting(conn, "Sprint 23", "2026-09-01", [item])
    db.update_action_item(conn, f"{meeting_id}:item:a1", owner="Dan")

    hints = memory.owner_hints(conn, exclude_meeting_id="other")
    assert len(hints) == 1
    assert hints[0]["owner"] == "Dan"
    assert hints[0]["times_assigned"] == 1
    assert hints[0]["example_task"] == "Add error alerting"


def test_owner_hints_ignores_owners_the_agent_found_itself(conn):
    """If the agent got it right, it is not a correction and teaches nothing."""
    item = ActionItem(id="a1", task="Write the plan", owner="Sam",
                      deadline="2026-09-12", source_quote="q", confidence=0.9)
    _meeting(conn, "Sprint 23", "2026-09-01", [item])
    assert memory.owner_hints(conn, exclude_meeting_id="other") == []


def test_owner_hints_excludes_the_current_meeting(conn):
    item = ActionItem(id="a1", task="t", owner=None, deadline=None,
                      source_quote="q", confidence=0.7)
    meeting_id = _meeting(conn, "Sprint 23", "2026-09-01", [item])
    db.update_action_item(conn, f"{meeting_id}:item:a1", owner="Dan")
    assert memory.owner_hints(conn, exclude_meeting_id=meeting_id) == []


def test_owner_hints_counts_repeats(conn):
    for n, date in enumerate(("2026-09-01", "2026-09-08"), start=1):
        item = ActionItem(id="a1", task=f"Task {n}", owner=None, deadline=None,
                          source_quote="q", confidence=0.7)
        meeting_id = _meeting(conn, f"Sprint {n}", date, [item])
        db.update_action_item(conn, f"{meeting_id}:item:a1", owner="Dan")

    hints = memory.owner_hints(conn, exclude_meeting_id="other")
    assert hints[0]["times_assigned"] == 2


def test_owner_hints_ignores_items_a_human_added_from_scratch(conn):
    """A human-added item also has ai_owner NULL and an owner set, so only the
    origin clause keeps it out. Without it, work the agent never saw would look
    like a correction of the agent."""
    agent_item = ActionItem(id="a1", task="Add error alerting", owner=None,
                            deadline=None, source_quote="q", confidence=0.7)
    meeting_id = _meeting(conn, "Sprint 23", "2026-09-01", [agent_item])
    db.update_action_item(conn, f"{meeting_id}:item:a1", owner="Dan")
    db.add_action_item(conn, meeting_id, task="Book the room", owner="Marcus",
                       deadline="2026-09-20")

    hints = memory.owner_hints(conn, exclude_meeting_id="other")
    assert [h["owner"] for h in hints] == ["Dan"], (
        "a human-added item leaked in as a correction")


def test_prior_commitments_needs_both_owner_and_deadline(conn):
    complete = ActionItem(id="a1", task="Write the plan", owner="Sam",
                          deadline="2026-09-12", source_quote="q", confidence=0.9)
    partial = ActionItem(id="a2", task="Book the room", owner="Sam",
                         deadline=None, source_quote="q", confidence=0.9)
    _meeting(conn, "Sprint 23", "2026-09-01", [complete, partial])

    commitments = memory.prior_commitments(conn, exclude_meeting_id="other")
    assert [c["task"] for c in commitments] == ["Write the plan"]
    assert commitments[0]["meeting_title"] == "Sprint 23"


def test_prior_commitments_excludes_the_current_meeting(conn):
    item = ActionItem(id="a1", task="Write the plan", owner="Sam",
                      deadline="2026-09-12", source_quote="q", confidence=0.9)
    meeting_id = _meeting(conn, "Sprint 23", "2026-09-01", [item])
    assert memory.prior_commitments(conn, exclude_meeting_id=meeting_id) == []


def test_prior_commitments_excludes_deleted_items(conn):
    item = ActionItem(id="a1", task="Write the plan", owner="Sam",
                      deadline="2026-09-12", source_quote="q", confidence=0.9)
    meeting_id = _meeting(conn, "Sprint 23", "2026-09-01", [item])
    db.delete_action_item(conn, f"{meeting_id}:item:a1")
    assert memory.prior_commitments(conn, exclude_meeting_id="other") == []


def test_both_queries_are_empty_on_a_fresh_database(conn):
    """The first meeting ever has no memory. This must not raise."""
    assert memory.owner_hints(conn, exclude_meeting_id="m1") == []
    assert memory.prior_commitments(conn, exclude_meeting_id="m1") == []


def test_prior_commitments_excludes_an_owner_a_human_supplied(conn):
    """The ai_owner clause, at the query. A row the agent left ownerless and a
    human filled in is what owner_hints is for; it must not also become the
    BACKGROUND block a model reads."""
    human_filled = ActionItem(id="a1", task="Add error alerting", owner=None,
                              deadline=None, source_quote="q", confidence=0.7)
    agent_read = ActionItem(id="a2", task="Write the plan", owner="Sam",
                            deadline="2026-09-12", source_quote="q", confidence=0.9)
    meeting_id = _meeting(conn, "Sprint 23", "2026-09-01", [human_filled, agent_read])
    db.update_action_item(conn, f"{meeting_id}:item:a1", owner="Dan",
                          deadline="2026-09-01")

    commitments = memory.prior_commitments(conn, exclude_meeting_id="other")
    assert [c["task"] for c in commitments] == ["Write the plan"]
    assert "Dan" not in {c["owner"] for c in commitments}


def test_prior_commitments_excludes_an_item_a_human_added_from_scratch(conn):
    """A human-added item has ai_owner NULL too — the agent never saw the work
    at all, so it is nobody's background."""
    agent_read = ActionItem(id="a1", task="Write the plan", owner="Sam",
                            deadline="2026-09-12", source_quote="q", confidence=0.9)
    meeting_id = _meeting(conn, "Sprint 23", "2026-09-01", [agent_read])
    db.add_action_item(conn, meeting_id, task="Book the room", owner="Marcus",
                       deadline="2026-09-20")

    commitments = memory.prior_commitments(conn, exclude_meeting_id="other")
    assert [c["task"] for c in commitments] == ["Write the plan"]


def test_a_corrected_owner_never_becomes_background(conn):
    """A human's correction of an owner the agent DID read must not round-trip.

    The row is gated on the frozen ai_owner, so it qualifies — but what gets
    emitted must be what the agent read, never what the human typed over it.
    """
    item = ActionItem(id="a1", task="Add error alerting", owner="Sam",
                      deadline="2026-09-01", source_quote="q", confidence=0.9)
    meeting_id = _meeting(conn, "Ops sync", "2026-08-28", [item])
    db.update_action_item(conn, f"{meeting_id}:item:a1", owner="Dan")

    commitments = memory.prior_commitments(conn, exclude_meeting_id="other")
    assert [c["owner"] for c in commitments] == ["Sam"], (
        "a human's corrected owner leaked into background")


def test_a_human_supplied_deadline_never_becomes_background(conn):
    """There is no deadline_hints half of memory, so this has no other guard."""
    item = ActionItem(id="a1", task="Add error alerting", owner="Sam",
                      deadline=None, source_quote="q", confidence=0.9)
    meeting_id = _meeting(conn, "Ops sync", "2026-08-28", [item])
    db.update_action_item(conn, f"{meeting_id}:item:a1", deadline="2026-09-30")

    assert memory.prior_commitments(conn, exclude_meeting_id="other") == [], (
        "a row the agent never dated qualified as a commitment"
    )


def test_a_corrected_task_never_becomes_background(conn):
    item = ActionItem(id="a1", task="Add error alerting", owner="Sam",
                      deadline="2026-09-01", source_quote="q", confidence=0.9)
    meeting_id = _meeting(conn, "Ops sync", "2026-08-28", [item])
    db.update_action_item(conn, f"{meeting_id}:item:a1", task="Rewrite the alerting rules")

    commitments = memory.prior_commitments(conn, exclude_meeting_id="other")
    assert [c["task"] for c in commitments] == ["Add error alerting"]
