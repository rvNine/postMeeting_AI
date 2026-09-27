import re
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from agent.llm_client import LLMError
from query.models import AnswerDraft, QueryFilters
from storage import db
from storage.meeting_knowledge import is_fixture_meeting
from ui.state import (MEETING_SESSION_KEYS, QUERY_SESSION_KEYS, Stage, build_query_filters,
                      clear_query_state, open_query_citation)


ROOT = Path(__file__).resolve().parents[1]


def test_query_view_does_not_access_sql_directly():
    source = (ROOT / "ui/query_view.py").read_text()
    assert "import sqlite3" not in source
    assert "conn.execute(" not in source


def test_query_view_calls_no_mutating_storage_helpers():
    source = (ROOT / "ui/query_view.py").read_text()
    assert not re.search(r"\bdb\.(save|add|update|delete|resolve|mark)_", source)


def test_query_state_clears_and_citation_opens_review():
    session = {"query_result": "old", "query_question": "old"}
    clear_query_state(session)
    assert "query_result" not in session
    open_query_citation(session, "fx-rollout-readiness")
    assert session["meeting_id"] == "fx-rollout-readiness"
    assert session["stage"] is Stage.REVIEW


def test_clear_query_state_removes_every_query_key():
    session = {key: "old" for key in QUERY_SESSION_KEYS} | {"meeting_id": "keep"}
    clear_query_state(session)
    assert session == {"meeting_id": "keep"}
    assert set(QUERY_SESSION_KEYS) >= {"query_question", "query_filters", "query_result", "query_error"}


def test_opening_a_citation_drops_the_previous_meetings_state():
    session = {key: "stale" for key in MEETING_SESSION_KEYS} | {"query_result": "old"}
    open_query_citation(session, "fx-kickoff")
    assert not set(MEETING_SESSION_KEYS) & set(session)
    assert "query_result" not in session


def test_build_query_filters_sets_all_eight_fields():
    filters = build_query_filters(
        date_range=(date(2026, 9, 1), date(2026, 9, 30)), meeting_id="fx-kickoff",
        participant="Mira Vale", owner="Sia Moss", record_type="risks",
        severity="high", program_phase="design",
    )
    assert filters == QueryFilters(
        date_from="2026-09-01", date_to="2026-09-30", meeting_id="fx-kickoff",
        participant="Mira Vale", owner="Sia Moss", record_type="risks",
        severity="high", program_phase="design",
    )


def test_build_query_filters_treats_unset_choices_as_no_filter():
    assert build_query_filters() == QueryFilters()
    assert build_query_filters(date_range=(), meeting_id=None, participant="") == QueryFilters()


def test_build_query_filters_with_a_half_picked_range_filters_from_that_day():
    assert build_query_filters(date_range=(date(2026, 10, 1),)) == QueryFilters(date_from="2026-10-01")


def test_fixture_meetings_are_identified_and_user_meetings_are_not(seeded_conn):
    user_id = db.save_meeting(seeded_conn, title="User meeting", meeting_date="2026-09-26", raw_notes="user")
    assert is_fixture_meeting(seeded_conn, "fx-kickoff") is True
    assert is_fixture_meeting(seeded_conn, user_id) is False
    assert is_fixture_meeting(seeded_conn, "missing") is False


# --- Rendered behaviour (Streamlit AppTest; the script runs the real views) ---

def _query_app(conn, vector, llm):
    from ui import query_view

    query_view.render(conn, vector, llm=llm)


def _ask(indexed_conn, vector, client, question):
    at = AppTest.from_function(_query_app, args=(indexed_conn, vector, client), default_timeout=30)
    at.run()
    at.text_input(key="query_question_input").input(question)
    at.run()  # typing reruns the script, which is what enables Ask in a browser
    at.button(key="query_ask").click()
    at.run()
    return at


def test_query_view_does_not_call_the_model_until_ask_is_pressed(indexed_conn, vector, stub_client):
    client = stub_client([])
    at = AppTest.from_function(_query_app, args=(indexed_conn, vector, client), default_timeout=30)
    at.run()
    assert not at.exception
    assert client.calls == []


def test_query_view_exposes_every_filter(indexed_conn, vector, stub_client):
    at = AppTest.from_function(_query_app, args=(indexed_conn, vector, stub_client([])), default_timeout=30)
    at.run()
    assert at.date_input(key="query_dates") is not None
    for key in ("query_meeting", "query_participant", "query_owner", "query_record_type",
                "query_severity", "query_phase"):
        assert at.selectbox(key=key) is not None, key
    assert "Sia Moss" in at.selectbox(key="query_owner").options
    assert "rollout_readiness" in at.selectbox(key="query_phase").options


def test_answered_query_renders_answer_citation_quote_and_review_link(indexed_conn, vector, stub_client):
    client = stub_client([AnswerDraft(status="answered", answer="Use explicit schema_rev.", citation_ids=["c1"])])
    at = _ask(indexed_conn, vector, client, "explicit schema_rev")
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Use explicit schema_rev." in page
    assert "c1" in page
    assert "schema_rev" in " ".join(c.value for c in at.caption) + page
    assert at.button(key="query_open_c1") is not None


def test_opening_a_citation_routes_to_that_meetings_review(indexed_conn, vector, stub_client):
    client = stub_client([AnswerDraft(status="answered", answer="Use explicit schema_rev.", citation_ids=["c1"])])
    at = _ask(indexed_conn, vector, client, "explicit schema_rev")
    at.button(key="query_open_c1").click()
    at.run()
    assert at.session_state["stage"] == Stage.REVIEW
    assert at.session_state["meeting_id"].startswith("fx-")
    assert "query_result" not in at.session_state


def test_not_found_query_says_so_and_suggests_filters(indexed_conn, vector, stub_client):
    client = stub_client([])
    at = _ask(indexed_conn, vector, client, "database migration deadline")
    assert not at.exception
    messages = " ".join(i.value for i in at.info)
    assert "No evidence" in messages
    assert "record type" in messages.lower()
    assert client.calls == []


def test_provider_error_is_shown_as_an_error_not_as_not_found(indexed_conn, vector, stub_client):
    client = stub_client([LLMError("Model call failed: Timeout")])
    at = _ask(indexed_conn, vector, client, "explicit schema_rev")
    assert "Timeout" in " ".join(e.value for e in at.error)
    assert not at.info


def test_query_view_never_changes_the_database(indexed_conn, vector, stub_client):
    before = indexed_conn.total_changes
    client = stub_client([AnswerDraft(status="answered", answer="x", citation_ids=["c1"])])
    _ask(indexed_conn, vector, client, "explicit schema_rev")
    assert indexed_conn.total_changes == before


def _review_app(conn, meeting_id):
    import streamlit as st

    from ui import review_view

    st.session_state["meeting_id"] = meeting_id
    review_view.render(conn)


EDIT_LABELS = {"Save", "Delete", "Mark resolved", "Add", "Add risk", "Add dependency",
               "Add learning", "Draft follow-up message"}


def test_fixture_meeting_review_is_read_only(indexed_conn):
    at = AppTest.from_function(_review_app, args=(indexed_conn, "fx-rollout-readiness"), default_timeout=30)
    at.run()
    assert not at.exception
    assert not {b.label for b in at.button} & EDIT_LABELS
    assert not at.text_input and not at.text_area
    page = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Approve a staged rollout to internal consumers first" in page
    assert "External consumers may have untested version negotiation" in page


def test_user_meeting_review_keeps_its_edit_controls(conn):
    meeting_id = db.save_meeting(conn, title="User meeting", meeting_date="2026-09-26", raw_notes="user notes")
    db.add_action_item(conn, meeting_id, task="Send the minutes", owner="Ana", deadline="2026-10-01")
    at = AppTest.from_function(_review_app, args=(conn, meeting_id), default_timeout=30)
    at.run()
    assert not at.exception
    labels = {b.label for b in at.button}
    assert {"Save", "Delete", "Draft follow-up message"} <= labels
