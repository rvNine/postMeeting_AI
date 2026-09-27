import json
from pathlib import Path

import pytest

from fixtures.meeting_manifest import (
    FixtureManifestError,
    load_fixture_manifest,
    validate_fixture_manifest,
)
from fixtures.technical_standardization.seed import seed_fixture_set
from storage import db
from storage.meeting_knowledge import load_meeting_context


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "technical_standardization"
EXPECTED_IDS = {
    "fx-kickoff", "fx-current-state", "fx-design-review", "fx-interoperability",
    "fx-pilot-validation", "fx-security-ipr", "fx-operations-observability",
    "fx-change-control", "fx-rollout-readiness", "fx-rollout-next-horizon",
}


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    yield connection
    connection.close()


def test_manifest_declares_ten_canonical_fixture_ids():
    manifest = load_fixture_manifest(FIXTURE_DIR)
    validate_fixture_manifest(manifest)
    assert len(manifest.meetings) == 10
    assert {meeting.meeting_id for meeting in manifest.meetings} == EXPECTED_IDS


def test_seed_is_idempotent_and_preserves_user_meeting(conn):
    seed_fixture_set(conn, FIXTURE_DIR)
    user_id = db.save_meeting(
        conn, title="User meeting", meeting_date="2026-09-26", raw_notes="user",
    )

    first = seed_fixture_set(conn, FIXTURE_DIR)
    second = seed_fixture_set(conn, FIXTURE_DIR)

    assert first.meeting_ids == second.meeting_ids
    assert conn.execute("SELECT COUNT(*) AS n FROM meetings").fetchone()["n"] == 11
    assert conn.execute(
        "SELECT title FROM meetings WHERE id = ?", (user_id,),
    ).fetchone()["title"] == "User meeting"


def test_delete_meeting_cascades_metadata_links_and_chunks(conn):
    seed_fixture_set(conn, FIXTURE_DIR)
    conn.execute(
        "INSERT INTO meeting_chunks (chunk_id, meeting_id, sequence, text, source_label) "
        "VALUES (?,?,?,?,?)",
        ("chunk-delete-test", "fx-kickoff", 999, "delete me", "fixture"),
    )
    conn.execute(
        "INSERT INTO meeting_chunk_fts (chunk_id, meeting_id, title, text) VALUES (?,?,?,?)",
        ("chunk-delete-test", "fx-kickoff", "Kickoff", "delete me"),
    )
    conn.commit()

    db.delete_meeting(conn, "fx-kickoff")

    assert conn.execute(
        "SELECT COUNT(*) AS n FROM meeting_metadata WHERE meeting_id = ?", ("fx-kickoff",),
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM meeting_participants WHERE meeting_id = ?", ("fx-kickoff",),
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM meeting_links "
        "WHERE source_meeting_id = ? OR target_meeting_id = ?", ("fx-kickoff", "fx-kickoff"),
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM meeting_chunks WHERE meeting_id = ?", ("fx-kickoff",),
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM meeting_chunk_fts WHERE meeting_id = ?", ("fx-kickoff",),
    ).fetchone()["n"] == 0


def test_seed_persists_context_records_links_and_synthetic_provenance(conn):
    report = seed_fixture_set(conn, FIXTURE_DIR)

    context = load_meeting_context(conn, report.meeting_ids["kickoff"])
    extraction = db.load_extraction_meta(conn, "fx-kickoff")
    action = conn.execute(
        "SELECT task, origin, source_quote, confidence FROM action_items WHERE id = ?",
        ("a-kickoff-1",),
    ).fetchone()
    link_count = conn.execute("SELECT COUNT(*) AS n FROM meeting_links").fetchone()["n"]

    assert context.meeting_id == "fx-kickoff"
    assert context.title == "LatticeBridge kickoff and vocabulary"
    assert context.program_phase == "kickoff"
    assert context.meeting_sequence == 1
    assert context.facilitator == "Mira Vale"
    assert context.source_type == "meeting_notes"
    assert context.fixture_set == "latticebridge-v1"
    assert [(participant.name, participant.role) for participant in context.participants] == [
        ("Mira Vale", "program lead"), ("Theo Quill", "standards lead"),
        ("Nia Sol", "platform lead"), ("Oren Pike", "quality lead"),
    ]
    assert extraction["model"] == "fixture"
    assert extraction["prompt_version"] == "synthetic-v1"
    assert extraction["tokens_used"] == extraction["latency_ms"] == 0
    assert action["origin"] == "fixture"
    assert action["source_quote"] in context.raw_notes
    assert 0 <= action["confidence"] <= 1
    assert link_count == 10


def test_manifest_contains_complete_records_links_and_golden_queries():
    manifest = load_fixture_manifest(FIXTURE_DIR)
    validate_fixture_manifest(manifest)

    assert all(link.source_meeting_id.startswith("fx-") for link in manifest.links)
    assert all(link.target_meeting_id.startswith("fx-") for link in manifest.links)
    assert {link.link_type for link in manifest.links} == {
        "continues", "reviews", "implements", "follow_up_to", "depends_on", "supersedes",
    }
    assert 30 <= len(manifest.golden_queries) <= 35
    assert {query.category for query in manifest.golden_queries} == {
        "semantic", "structured", "history", "relationship", "citation", "abstention",
    }
    assert all(query.fixture_set == "latticebridge-v1" for query in manifest.golden_queries)


def test_every_source_quote_resolves_to_its_markdown():
    manifest = load_fixture_manifest(FIXTURE_DIR)
    validate_fixture_manifest(manifest)
    for meeting in manifest.meetings:
        assert meeting.source_path.read_text().strip()
        for record in meeting.all_records:
            assert record.source_quote in meeting.raw_markdown
    for link in manifest.links:
        assert link.quote in link.source_meeting.raw_markdown


@pytest.mark.parametrize("mutation", ["missing_id", "duplicate_link", "bad_confidence", "missing_quote", "quote_not_in_source"])
def test_manifest_validation_rejects_broken_contract(tmp_path, mutation):
    source = json.loads((FIXTURE_DIR / "manifest.json").read_text())
    if mutation == "missing_id":
        del source["fixtures"][0]["meeting_id"]
    elif mutation == "duplicate_link":
        source["links"].append(source["links"][0])
    elif mutation == "bad_confidence":
        source["links"][0]["confidence"] = 1.1
    elif mutation == "missing_quote":
        del source["links"][0]["quote"]
    else:
        source["links"][0]["quote"] = "not present in the meeting"

    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    for path in FIXTURE_DIR.glob("*.md"):
        (fixture_dir / path.name).write_text(path.read_text())
    (fixture_dir / "manifest.json").write_text(json.dumps(source))

    with pytest.raises(FixtureManifestError):
        validate_fixture_manifest(load_fixture_manifest(fixture_dir))
