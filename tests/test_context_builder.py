import sqlite3

import pytest

from agent.schemas import ActionItem, MeetingContext, MeetingExtraction, ReviewResult
from storage import db
from ui.context_builder import build_context


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    yield connection
    connection.close()


_EMPTY_REVIEW = ReviewResult(gaps=[], overall_confidence=0.9, reviewer_notes="")


def test_build_context_is_empty_on_a_fresh_database(conn):
    """The first meeting ever. Must be the no-op case, not a crash."""
    ctx = build_context(conn, exclude_meeting_id="m1")
    assert isinstance(ctx, MeetingContext)
    assert ctx.is_empty is True


def test_build_context_carries_both_halves(conn):
    item = ActionItem(id="a1", task="Add error alerting", owner=None, deadline=None,
                      source_quote="q", confidence=0.7)
    done = ActionItem(id="a2", task="Write the plan", owner="Sam",
                      deadline="2026-09-12", source_quote="q", confidence=0.9)
    meeting_id = db.save_meeting(conn, title="Sprint 23", meeting_date="2026-09-01",
                                 raw_notes="n")
    db.save_extraction(conn, meeting_id,
                       MeetingExtraction(summary="s", participants=[], decisions=[],
                                         action_items=[item, done]),
                       _EMPTY_REVIEW, model="m", prompt_version="v2",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.update_action_item(conn, f"{meeting_id}:item:a1", owner="Dan")

    ctx = build_context(conn, exclude_meeting_id="other")
    assert [h.owner for h in ctx.owner_hints] == ["Dan"]
    assert [c.task for c in ctx.prior_commitments] == ["Write the plan"]
    assert ctx.is_empty is False


def test_a_failing_memory_query_yields_an_empty_context(conn, monkeypatch):
    """Memory is an enhancement, never a dependency — a broken query must not
    take down the analysis before a single model call is made."""
    from storage import memory

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("no such table: action_items")

    monkeypatch.setattr(memory, "owner_hints", boom)
    assert build_context(conn, exclude_meeting_id="m1").is_empty is True


def test_a_human_supplied_owner_never_becomes_background(conn):
    """The row that teaches owner_hints must not also reach the model.

    An item the agent left ownerless and a human then filled in appears in
    owner_hints by design. If prior_commitments returned it too, the human's
    own correction would be fed back to the model as background — the exact
    round-trip the owner-hint rule exists to prevent.
    """
    item = ActionItem(id="a1", task="Add error alerting", owner=None, deadline=None,
                      source_quote="q", confidence=0.7)
    meeting_id = db.save_meeting(conn, title="Ops sync", meeting_date="2026-08-28",
                                 raw_notes="n")
    db.save_extraction(conn, meeting_id,
                       MeetingExtraction(summary="s", participants=[], decisions=[],
                                         action_items=[item]),
                       _EMPTY_REVIEW, model="m", prompt_version="v2",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.update_action_item(conn, f"{meeting_id}:item:a1", owner="Dan",
                          deadline="2026-09-01")

    ctx = build_context(conn, exclude_meeting_id="other")
    assert [h.owner for h in ctx.owner_hints] == ["Dan"]
    assert ctx.prior_commitments == (), "a human's correction leaked into background"
