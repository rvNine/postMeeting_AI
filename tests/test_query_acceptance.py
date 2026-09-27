"""Acceptance gate for meeting knowledge queries: the whole synthetic dataset,
end to end through QueryService, with no network access."""
import json
from pathlib import Path

from fixtures.technical_standardization.seed import main as seed_main
from query.models import QueryFilters
from storage import db


GOLDEN_QUERY_PATH = (
    Path(__file__).parent.parent / "fixtures" / "technical_standardization" / "golden_queries.json"
)


def load_golden_queries() -> list[dict]:
    return json.loads(GOLDEN_QUERY_PATH.read_text())


def test_full_synthetic_dataset_supports_required_query_categories(indexed_conn, golden_query_service):
    for case in load_golden_queries():
        service = golden_query_service(case)
        result = service.ask(case["question"], QueryFilters(**case["filters"]))
        assert result.status == ("answered" if case["answerable"] else "not_found"), case["question"]
        if not case["answerable"]:
            # The answer stub abstains on its own; abstention must come from retrieval.
            assert service.llm.calls == [], case["question"]
        if case["answerable"]:
            assert set(case["expected_meetings"]) & {c.meeting_id for c in result.citations}, case["question"]
            assert any(phrase.lower() in citation.quote.lower()
                       for phrase in case["expected_phrases"]
                       for citation in result.citations), case["question"]


def test_existing_action_gate_tables_remain_unchanged(indexed_conn, query_service):
    tables = ("action_items", "gaps", "approvals", "decisions", "risks", "dependencies", "learnings")
    before = {t: indexed_conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables}
    result = query_service.ask("What standard was approved?", QueryFilters())
    after = {t: indexed_conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables}
    assert result.status in {"answered", "not_found"}
    assert after == before


def _fixture_meeting_count(path: Path) -> int:
    conn = db.connect(path)
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM meeting_metadata WHERE fixture_set = 'latticebridge-v1'"
        ).fetchone()["n"]
    finally:
        conn.close()


def test_seed_command_is_repeatable_and_indexes_the_fixtures(tmp_path, capsys):
    db_path = tmp_path / "nested" / "m.db"
    assert seed_main(["--db", str(db_path)]) == 0
    assert _fixture_meeting_count(db_path) == 10
    assert seed_main(["--db", str(db_path)]) == 0
    assert _fixture_meeting_count(db_path) == 10
    conn = db.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM meeting_chunks").fetchone()["n"] > 0
    finally:
        conn.close()
    assert "10" in capsys.readouterr().out


def test_seed_command_keeps_user_meetings(tmp_path):
    db_path = tmp_path / "m.db"
    conn = db.connect(db_path)
    db.init_db(conn)
    user_id = db.save_meeting(conn, title="Mine", meeting_date="2026-09-26", raw_notes="user notes")
    conn.close()
    assert seed_main(["--db", str(db_path)]) == 0
    conn = db.connect(db_path)
    try:
        assert conn.execute("SELECT title FROM meetings WHERE id = ?", (user_id,)).fetchone()["title"] == "Mine"
    finally:
        conn.close()
