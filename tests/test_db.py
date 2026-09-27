import json

import pytest

from agent.schemas import (ActionItem, Decision, Gap, GapType, MeetingExtraction,
                           ReviewResult, Severity, TechnicalDependency, TechnicalLearning,
                           TechnicalRisk)
from storage import db
from ui.gap_display import gaps_for_item


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def extraction():
    return MeetingExtraction(
        summary="We discussed the migration.",
        participants=["Priya", "Sam"],
        decisions=[Decision(id="d1", decision="Use Postgres", rationale="better JSON",
                            source_quote="going with postgres", confidence=0.9)],
        action_items=[
            ActionItem(id="a1", task="Benchmark Postgres", owner="Sam",
                       deadline="2026-10-02", source_quote="Sam to benchmark", confidence=0.95),
            ActionItem(id="a2", task="Draft the migration doc", owner=None,
                       deadline=None, source_quote="someone should write it up", confidence=0.6),
        ],
    )


@pytest.fixture
def review():
    return ReviewResult(
        gaps=[Gap(id="struct::a2::missing_owner", type=GapType.MISSING_OWNER,
                  severity=Severity.BLOCKING, target_id="a2",
                  explanation="No owner stated.", suggested_question="Who writes it?")],
        overall_confidence=0.75,
        reviewer_notes="One item lacks an owner.",
    )


def test_init_db_is_idempotent(tmp_path):
    connection = db.connect(tmp_path / "t.db")
    db.init_db(connection)
    db.init_db(connection)  # must not raise
    connection.close()


def test_init_db_migrates_legacy_extractions_with_default_processing_pass(tmp_path):
    connection = db.connect(tmp_path / "legacy.db")
    try:
        connection.execute("""
            CREATE TABLE extractions (
                id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                participants TEXT NOT NULL,
                reviewer_notes TEXT,
                overall_confidence REAL,
                raw_response TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                model TEXT NOT NULL,
                tokens_used INTEGER,
                latency_ms INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("e1", "m1", "summary", "[]", "reviewed", 0.8, "{}", "v3",
             "model", 10, 20, "2026-09-24T00:00:00+00:00"),
        )
        connection.commit()

        db.init_db(connection)

        columns = {row["name"] for row in connection.execute(
            "PRAGMA table_info(extractions)").fetchall()}
        assert "processing_pass" in columns
        row = connection.execute(
            "SELECT processing_pass FROM extractions WHERE id = 'e1'").fetchone()
        assert row["processing_pass"] == 1
    finally:
        connection.close()


def test_save_and_load_round_trip(conn, extraction, review):
    meeting_id = db.save_meeting(conn, title="Sprint review",
                                 meeting_date="2026-09-15", raw_notes="notes here")
    db.save_extraction(conn, meeting_id, extraction, review, model="gpt-4o-mini",
                       prompt_version="v1", tokens_used=900, latency_ms=4200,
                       raw_response="{}")
    items = db.load_action_items(conn, meeting_id)
    assert len(items) == 2
    assert {i["task"] for i in items} == {"Benchmark Postgres", "Draft the migration doc"}


def test_ai_values_are_frozen_on_save(conn, extraction, review):
    """PRD F15 depends on the agent's original values surviving human edits."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.update_action_item(conn, f"{meeting_id}:item:a2", owner="Priya", deadline="2026-10-09")
    item = next(i for i in db.load_action_items(conn, meeting_id)
                if i["id"] == f"{meeting_id}:item:a2")
    assert item["owner"] == "Priya"
    assert item["ai_owner"] is None       # frozen: the agent found none
    assert item["ai_deadline"] is None


def test_human_edits_reports_only_changed_fields(conn, extraction, review):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.update_action_item(conn, f"{meeting_id}:item:a2", owner="Priya")
    edits = db.human_edits(conn, meeting_id)
    assert len(edits) == 1
    assert edits[0] == {"item_id": f"{meeting_id}:item:a2", "field": "owner",
                        "ai_value": None, "human_value": "Priya"}


def test_added_items_are_marked_human_origin(conn, extraction, review):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    new_id = db.add_action_item(conn, meeting_id, task="Book the room",
                                owner="Priya", deadline="2026-09-20")
    item = next(i for i in db.load_action_items(conn, meeting_id) if i["id"] == new_id)
    assert item["origin"] == "human"


def test_deleted_items_are_hidden_but_retained(conn, extraction, review):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.delete_action_item(conn, f"{meeting_id}:item:a1")
    assert len(db.load_action_items(conn, meeting_id)) == 1
    row = conn.execute("SELECT deleted FROM action_items WHERE id = ?",
                       (f"{meeting_id}:item:a1",)).fetchone()
    assert row["deleted"] == 1


def test_resolving_a_gap_is_persisted(conn, extraction, review):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    assert db.resolved_gap_ids(conn, meeting_id) == set()
    db.resolve_gap(conn, f"{meeting_id}:gap:struct::a2::missing_owner")
    assert db.resolved_gap_ids(conn, meeting_id) == {f"{meeting_id}:gap:struct::a2::missing_owner"}


def test_a_resolved_gap_can_be_reopened(conn, extraction, review):
    """If a human clears a field again, its gap must come back."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    gap_id = f"{meeting_id}:gap:struct::a2::missing_owner"
    db.resolve_gap(conn, gap_id)
    assert gap_id in db.resolved_gap_ids(conn, meeting_id)
    db.resolve_gap(conn, gap_id, False)
    assert gap_id not in db.resolved_gap_ids(conn, meeting_id)


def test_extraction_meta_returns_summary_and_provenance(conn, extraction, review):
    """PRD F3 displays the summary; the model/prompt version prove provenance."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="gpt-4o-mini",
                       prompt_version="v1", tokens_used=900, latency_ms=4200,
                       raw_response="{}")
    meta = db.load_extraction_meta(conn, meeting_id)
    assert meta["summary"] == "We discussed the migration."
    assert json.loads(meta["participants"]) == ["Priya", "Sam"]
    assert meta["model"] == "gpt-4o-mini"
    assert meta["prompt_version"] == "v1"


def test_extraction_meta_persists_corrective_processing_pass(conn, extraction, review):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(
        conn, meeting_id, extraction, review, model="m", prompt_version="v3",
        processing_pass=2, tokens_used=1, latency_ms=1, raw_response="{}",
    )
    assert db.load_extraction_meta(conn, meeting_id)["processing_pass"] == 2


def test_extraction_meta_is_none_for_an_unanalysed_meeting(conn):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    assert db.load_extraction_meta(conn, meeting_id) is None


def test_approval_sets_meeting_status(conn, extraction, review):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.save_approval(conn, meeting_id, draft_text="draft", final_text="final")
    meeting = next(m for m in db.list_meetings(conn) if m["id"] == meeting_id)
    assert meeting["status"] == "approved"


def test_update_can_clear_an_owner(conn, extraction, review):
    """A human must be able to blank a field the agent filled in, not just overwrite it."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.update_action_item(conn, f"{meeting_id}:item:a1", owner=None)
    item = next(i for i in db.load_action_items(conn, meeting_id)
                if i["id"] == f"{meeting_id}:item:a1")
    assert item["owner"] is None


def test_deleted_decisions_are_hidden_but_retained(conn, extraction, review):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.delete_decision(conn, f"{meeting_id}:decision:d1")
    assert db.load_decisions(conn, meeting_id) == []
    row = conn.execute("SELECT deleted FROM decisions WHERE id = ?",
                       (f"{meeting_id}:decision:d1",)).fetchone()
    assert row["deleted"] == 1


def test_failed_extraction_write_leaves_no_partial_rows(conn, extraction, review):
    """PRD §5.6: a failure must never silently produce a partial result."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    # Force a failure partway through the action-item loop: NOT NULL on task.
    extraction.action_items[1].task = None
    with pytest.raises(Exception):
        db.save_extraction(conn, meeting_id, extraction, review, model="m",
                           prompt_version="v1", tokens_used=1, latency_ms=1,
                           raw_response="{}")
    # Nothing from the failed write may survive, even after a later unrelated commit.
    db.save_meeting(conn, title="later", meeting_date="2026-09-16", raw_notes="n2")
    assert db.load_action_items(conn, meeting_id) == []
    assert conn.execute("SELECT COUNT(*) c FROM extractions WHERE meeting_id = ?",
                        (meeting_id,)).fetchone()["c"] == 0


def test_failed_technical_record_write_leaves_no_partial_rows(conn, extraction, review):
    """Same all-or-nothing rule for the technical tables: a failure while writing
    the second risk must roll back the extraction, its action items, decisions,
    the first risk, and everything after it."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    extraction.risks = [
        TechnicalRisk(id="r1", description="Cache saturation", impact=None,
                      likelihood=None, severity=None, mitigation=None, owner=None,
                      source_quote="cache saturation", confidence=0.8),
        TechnicalRisk(id="r2", description="Queue backlog", impact=None,
                      likelihood=None, severity=None, mitigation=None, owner=None,
                      source_quote="queue backlog", confidence=0.8),
    ]
    extraction.dependencies = [TechnicalDependency(
        id="dep1", description="Wait for API contract", depends_on=None,
        blocked_by=None, owner=None, source_quote="api contract", confidence=0.8)]
    extraction.learnings = [TechnicalLearning(
        id="l1", lesson="Use smaller batches", technical_area=None,
        validation_status=None, follow_up_experiment=None,
        source_quote="smaller batches", confidence=0.8)]
    # Force a failure partway through the risk loop: NOT NULL on description.
    extraction.risks[1].description = None
    with pytest.raises(Exception):
        db.save_extraction(conn, meeting_id, extraction, review, model="m",
                           prompt_version="v1", tokens_used=1, latency_ms=1,
                           raw_response="{}")
    # A later unrelated commit must not flush anything from the failed write.
    db.save_meeting(conn, title="later", meeting_date="2026-09-16", raw_notes="n2")
    for table in ("extractions", "action_items", "decisions", "risks",
                  "dependencies", "learnings", "gaps"):
        count = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE meeting_id = ?",
                             (meeting_id,)).fetchone()["c"]
        assert count == 0, f"{table} kept {count} row(s) from a failed write"


def test_human_added_items_are_excluded_from_the_edit_diff(conn, extraction, review):
    """A human-added item has NULL ai_* columns; it is not an edit of anything."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.add_action_item(conn, meeting_id, task="Book the room", owner="Priya",
                       deadline="2026-09-20")
    assert db.human_edits(conn, meeting_id) == []


def test_two_meetings_with_the_same_model_ids_both_save(conn, extraction, review):
    """The model reuses `a1`/`d1` on every meeting; ids are TEXT PRIMARY KEY across
    the whole table, so the second Analyze of a session used to die on a UNIQUE
    constraint. Both must save, and each must load only its own rows."""
    first = db.save_meeting(conn, title="one", meeting_date="2026-09-15", raw_notes="n1")
    db.save_extraction(conn, first, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    second = db.save_meeting(conn, title="two", meeting_date="2026-09-16", raw_notes="n2")
    db.save_extraction(conn, second, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")

    for meeting_id in (first, second):
        items = db.load_action_items(conn, meeting_id)
        assert len(items) == 2
        assert all(i["id"].startswith(f"{meeting_id}:item:") for i in items)
        decisions = db.load_decisions(conn, meeting_id)
        assert [d["id"] for d in decisions] == [f"{meeting_id}:decision:d1"]
        gaps = db.load_gaps(conn, meeting_id)
        assert [g["id"] for g in gaps] == [f"{meeting_id}:gap:struct::a2::missing_owner"]

    assert (db.load_action_items(conn, first)[0]["id"]
            != db.load_action_items(conn, second)[0]["id"])


def test_gap_target_ids_still_match_their_items_after_namespacing(conn, extraction, review):
    """The highest-risk half of the namespacing fix: ui.gap_display.gaps_for_item
    matches gap.target_id against item["id"]. Namespace one without the other and
    every badge silently disappears."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    item = next(i for i in db.load_action_items(conn, meeting_id)
                if i["task"] == "Draft the migration doc")
    gap = db.load_gaps(conn, meeting_id)[0]
    assert gap["target_id"] == item["id"]

    gaps = [Gap(**{k: v for k, v in g.items()
                   if k in {"id", "type", "severity", "target_id",
                            "explanation", "suggested_question"}})
            for g in db.load_gaps(conn, meeting_id)]
    assert gaps_for_item(gaps, item["id"]) != []


def test_a_deleted_meeting_leaves_nothing_in_the_sidebar(conn):
    """The orphan-cleanup path: save_meeting commits before save_extraction runs."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.delete_meeting(conn, meeting_id)
    assert [m["id"] for m in db.list_meetings(conn)] == []


def test_colliding_item_and_decision_ids_stay_distinct(conn):
    """The model numbers decisions 1,2 and action items 1,2,3,4 — the same integers
    in two different id spaces. Scoping by meeting alone left `<meeting>:2` matching
    both, so a gap targeting it rendered twice and crashed the page with a duplicate
    Streamlit key. Ids must be distinguishable by entity kind."""
    extraction = MeetingExtraction(
        summary="s", participants=["Priya"],
        decisions=[Decision(id="2", decision="Keep Redis", rationale=None,
                            source_quote="q", confidence=0.9)],
        action_items=[ActionItem(id="2", task="Add error alerting", owner="Dan",
                                 deadline="2026-09-15", source_quote="q", confidence=0.9)],
    )
    review = ReviewResult(
        gaps=[Gap(id="model::2::conflicting_decision", type=GapType.CONFLICTING_DECISION,
                  severity=Severity.BLOCKING, target_id="2",
                  explanation="reversed later", suggested_question="Which stands?")],
        overall_confidence=0.6, reviewer_notes="")

    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")

    item_ids = {i["id"] for i in db.load_action_items(conn, meeting_id)}
    decision_ids = {d["id"] for d in db.load_decisions(conn, meeting_id)}
    assert item_ids & decision_ids == set(), "an action item and a decision share an id"

    gap = db.load_gaps(conn, meeting_id)[0]
    assert gap["target_id"] in decision_ids, "a conflicting_decision gap must target the decision"
    assert gap["target_id"] not in item_ids, "gap is ambiguous — it matches an action item too"


def test_technical_records_round_trip(conn, extraction, review):
    extraction.risks = [TechnicalRisk(
        id="r1", description="Cache saturation", impact="latency", likelihood=None,
        severity="high", mitigation="Add capacity", owner=None,
        source_quote="cache saturation", confidence=0.8)]
    extraction.dependencies = [TechnicalDependency(
        id="dep1", description="Wait for API contract", depends_on="API team",
        blocked_by=None, owner=None, source_quote="wait for API contract",
        confidence=0.8)]
    extraction.learnings = [TechnicalLearning(
        id="l1", lesson="Use smaller batches", technical_area="migration",
        validation_status="observed", follow_up_experiment=None,
        source_quote="smaller batches", confidence=0.8)]
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="notes")
    db.save_extraction(conn, meeting_id, extraction, review, model="m",
                       prompt_version="v1", tokens_used=1, latency_ms=1,
                       raw_response="{}")
    assert db.load_risks(conn, meeting_id)[0]["description"] == "Cache saturation"
    assert db.load_dependencies(conn, meeting_id)[0]["depends_on"] == "API team"
    assert db.load_learnings(conn, meeting_id)[0]["lesson"] == "Use smaller batches"


def test_technical_ai_values_are_frozen_after_edit(conn, extraction, review):
    extraction.risks = [TechnicalRisk(
        id="r1", description="Cache saturation", impact=None, likelihood=None,
        severity="high", mitigation=None, owner=None,
        source_quote="cache saturation", confidence=0.8)]
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m",
                       prompt_version="v1", tokens_used=1, latency_ms=1,
                       raw_response="{}")
    db.update_risk(conn, f"{meeting_id}:risk:r1", severity="medium", owner="Priya")
    risk = db.load_risks(conn, meeting_id)[0]
    assert risk["severity"] == "medium"
    assert risk["ai_severity"] == "high"
    assert risk["ai_owner"] is None


def test_technical_human_add_and_soft_delete(conn):
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    risk_id = db.add_risk(
        conn, meeting_id, description="Human-confirmed risk", impact=None,
        likelihood=None, severity="medium", mitigation=None, owner="Sam")
    risk = db.load_risks(conn, meeting_id)[0]
    assert risk["id"] == risk_id
    assert risk["origin"] == "human"
    assert risk["ai_description"] is None
    assert risk["source_quote"] == ""
    assert risk["confidence"] is None
    db.delete_risk(conn, risk_id)
    assert db.load_risks(conn, meeting_id) == []


def test_technical_dependency_and_learning_add_update_delete(conn):
    """add_dependency/add_learning, their typed updates, and their soft deletes —
    the same contract as add_risk, exercised for the other two record kinds."""
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")

    dep_id = db.add_dependency(conn, meeting_id, description="Wait on vendor",
                               depends_on="Vendor", blocked_by=None, owner=None)
    dep = db.load_dependencies(conn, meeting_id)[0]
    assert dep["id"] == dep_id
    assert dep["origin"] == "human"
    assert dep["ai_depends_on"] is None
    assert dep["source_quote"] == ""
    assert dep["confidence"] is None
    db.update_dependency(conn, dep_id, blocked_by="Contract signature")
    dep = db.load_dependencies(conn, meeting_id)[0]
    assert dep["blocked_by"] == "Contract signature"
    assert dep["depends_on"] == "Vendor"
    db.delete_dependency(conn, dep_id)
    assert db.load_dependencies(conn, meeting_id) == []

    learning_id = db.add_learning(conn, meeting_id, lesson="Rehearse the cutover",
                                  technical_area=None, validation_status=None,
                                  follow_up_experiment=None)
    learning = db.load_learnings(conn, meeting_id)[0]
    assert learning["id"] == learning_id
    assert learning["origin"] == "human"
    assert learning["ai_lesson"] is None
    assert learning["source_quote"] == ""
    assert learning["confidence"] is None
    db.update_learning(conn, learning_id, validation_status="confirmed")
    learning = db.load_learnings(conn, meeting_id)[0]
    assert learning["validation_status"] == "confirmed"
    db.delete_learning(conn, learning_id)
    assert db.load_learnings(conn, meeting_id) == []


def test_technical_human_edits_are_reported_with_kind(conn, extraction, review):
    """human_edits() must append technical diffs with a 'kind' key while leaving
    the action-item dict shape untouched (Ruling R1)."""
    extraction.risks = [TechnicalRisk(
        id="r1", description="Cache saturation", impact=None, likelihood=None,
        severity="high", mitigation=None, owner=None,
        source_quote="cache saturation", confidence=0.8)]
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    db.update_risk(conn, f"{meeting_id}:risk:r1", severity="medium")
    edits = db.human_edits(conn, meeting_id)
    assert all("kind" not in e for e in edits if e["item_id"] != f"{meeting_id}:risk:r1"), (
        "action-item edit dicts must keep their existing shape (Ruling R1)")
    assert edits == [{"kind": "risk", "item_id": f"{meeting_id}:risk:r1", "field": "severity",
                      "ai_value": "high", "human_value": "medium"}]


def test_unsupported_evidence_gap_targets_a_risk(conn, extraction):
    """Controller amendment A2: an UNSUPPORTED_EVIDENCE gap whose raw target_id
    is a risk id (not an item/decision id) must resolve to the risk's scoped id."""
    extraction.risks = [TechnicalRisk(
        id="r1", description="Cache saturation", impact=None, likelihood=None,
        severity="high", mitigation=None, owner=None,
        source_quote="cache saturation", confidence=0.8)]
    review = ReviewResult(
        gaps=[Gap(id="evidence::risk::r1", type=GapType.UNSUPPORTED_EVIDENCE,
                  severity=Severity.WARNING, target_id="r1",
                  explanation="not supported", suggested_question="What supports this?")],
        overall_confidence=0.7, reviewer_notes="")
    meeting_id = db.save_meeting(conn, title="t", meeting_date="2026-09-15", raw_notes="n")
    db.save_extraction(conn, meeting_id, extraction, review, model="m", prompt_version="v1",
                       tokens_used=1, latency_ms=1, raw_response="{}")
    gap = db.load_gaps(conn, meeting_id)[0]
    assert gap["target_id"] == f"{meeting_id}:risk:r1"
