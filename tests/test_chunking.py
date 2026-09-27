from query.chunking import chunk_meeting
from pathlib import Path
import pytest

from query.vector import (
    ConfiguredVectorAdapterLoader,
    DeterministicVectorAdapter,
    NullVectorAdapter,
    configure_vector_adapter,
)
from storage.meeting_knowledge import rebuild_meeting_index


def test_chunk_ids_and_offsets_are_stable(sample_meeting):
    """Changing chunk sequencing or source offsets would break citations."""
    first = chunk_meeting(sample_meeting, max_chars=80, overlap=10)
    second = chunk_meeting(sample_meeting, max_chars=80, overlap=10)

    assert [(x.chunk_id, x.sequence, x.start_offset, x.end_offset) for x in first] == [
        (x.chunk_id, x.sequence, x.start_offset, x.end_offset) for x in second
    ]
    assert all(x.meeting_id == sample_meeting.meeting_id for x in first)
    assert all(
        sample_meeting.raw_notes[chunk.start_offset:chunk.end_offset] == chunk.text
        for chunk in first
    )


def test_deterministic_vector_adapter_orders_ties_by_chunk_id(chunk_a, chunk_b):
    """A tie must not make offline retrieval or resulting citations unstable."""
    adapter = DeterministicVectorAdapter([chunk_b, chunk_a])

    hits = adapter.search("migration", limit=2)

    assert [hit.chunk_id for hit in hits] == sorted([chunk_a.chunk_id, chunk_b.chunk_id])


def test_rebuild_meeting_index_replaces_only_one_meetings_chunks(seeded_conn):
    """Reindexing must be repeatable without changing analysis source records."""
    before_notes = seeded_conn.execute(
        "SELECT raw_notes FROM meetings WHERE id = ?", ("fx-kickoff",),
    ).fetchone()["raw_notes"]
    before_extractions = seeded_conn.execute(
        "SELECT COUNT(*) AS n FROM extractions WHERE meeting_id = ?", ("fx-kickoff",),
    ).fetchone()["n"]

    first_count = rebuild_meeting_index(seeded_conn, "fx-kickoff")
    first_rows = seeded_conn.execute(
        "SELECT chunk_id, sequence, text, start_offset, end_offset FROM meeting_chunks "
        "WHERE meeting_id = ? ORDER BY sequence", ("fx-kickoff",),
    ).fetchall()
    fts_count = seeded_conn.execute(
        "SELECT COUNT(*) AS n FROM meeting_chunk_fts WHERE meeting_id = ?", ("fx-kickoff",),
    ).fetchone()["n"]

    second_count = rebuild_meeting_index(seeded_conn, "fx-kickoff")
    second_rows = seeded_conn.execute(
        "SELECT chunk_id, sequence, text, start_offset, end_offset FROM meeting_chunks "
        "WHERE meeting_id = ? ORDER BY sequence", ("fx-kickoff",),
    ).fetchall()

    assert first_count == second_count == len(first_rows) == fts_count
    assert [tuple(row) for row in first_rows] == [tuple(row) for row in second_rows]
    assert seeded_conn.execute(
        "SELECT raw_notes FROM meetings WHERE id = ?", ("fx-kickoff",),
    ).fetchone()["raw_notes"] == before_notes
    assert seeded_conn.execute(
        "SELECT COUNT(*) AS n FROM extractions WHERE meeting_id = ?", ("fx-kickoff",),
    ).fetchone()["n"] == before_extractions


def test_fixture_seed_rebuilds_chunks_and_fts_rows(conn):
    """A fresh fixture dataset must immediately be searchable without a second command."""
    from fixtures.technical_standardization.seed import seed_fixture_set
    from tests.conftest import FIXTURE_DIR

    seed_fixture_set(conn, FIXTURE_DIR)

    meeting_count = conn.execute(
        "SELECT COUNT(*) AS n FROM meeting_metadata WHERE fixture_set = ?", ("latticebridge-v1",),
    ).fetchone()["n"]
    chunk_count = conn.execute("SELECT COUNT(*) AS n FROM meeting_chunks").fetchone()["n"]
    fts_count = conn.execute("SELECT COUNT(*) AS n FROM meeting_chunk_fts").fetchone()["n"]

    assert meeting_count == 10
    assert chunk_count > 0
    assert fts_count == chunk_count


def test_rebuild_meeting_index_refreshes_the_configured_vector_adapter(seeded_conn):
    """A configured in-memory adapter must receive fresh user/fixture chunks."""
    adapter = DeterministicVectorAdapter()
    configure_vector_adapter(adapter)
    try:
        rebuild_meeting_index(seeded_conn, "fx-kickoff")
        hits = adapter.search("versioned envelope", limit=5, meeting_ids={"fx-kickoff"})
    finally:
        configure_vector_adapter(NullVectorAdapter())

    assert hits


def test_rebuild_changed_meeting_removes_stale_sql_fts_and_vector_rows(seeded_conn):
    """Replacement must remove chunk IDs that are no longer generated."""
    adapter = DeterministicVectorAdapter()
    configure_vector_adapter(adapter)
    try:
        rebuild_meeting_index(seeded_conn, "fx-kickoff")
        old_ids = {
            row["chunk_id"]
            for row in seeded_conn.execute(
                "SELECT chunk_id FROM meeting_chunks WHERE meeting_id = ?",
                ("fx-kickoff",),
            ).fetchall()
        }
        seeded_conn.execute(
            "UPDATE meetings SET raw_notes = ? WHERE id = ?",
            ("replacement sentinel", "fx-kickoff"),
        )
        seeded_conn.commit()

        assert rebuild_meeting_index(seeded_conn, "fx-kickoff") == 1

        new_ids = {
            row["chunk_id"]
            for row in seeded_conn.execute(
                "SELECT chunk_id FROM meeting_chunks WHERE meeting_id = ?",
                ("fx-kickoff",),
            ).fetchall()
        }
        fts_ids = {
            row["chunk_id"]
            for row in seeded_conn.execute(
                "SELECT chunk_id FROM meeting_chunk_fts WHERE meeting_id = ?",
                ("fx-kickoff",),
            ).fetchall()
        }
        vector_ids = {
            hit.chunk_id
            for hit in adapter.search(
                "replacement sentinel", limit=10, meeting_ids={"fx-kickoff"}
            )
        }
    finally:
        configure_vector_adapter(NullVectorAdapter())

    assert old_ids.isdisjoint(new_ids)
    assert fts_ids == new_ids
    assert vector_ids == new_ids
    assert not adapter.search("versioned envelope", limit=10, meeting_ids={"fx-kickoff"})


def test_rebuild_empty_meeting_clears_sql_fts_and_vector_rows(seeded_conn):
    """An empty source is a replacement with zero chunks, not a no-op."""
    adapter = DeterministicVectorAdapter()
    configure_vector_adapter(adapter)
    try:
        rebuild_meeting_index(seeded_conn, "fx-kickoff")
        seeded_conn.execute(
            "UPDATE meetings SET raw_notes = '' WHERE id = ?", ("fx-kickoff",),
        )
        seeded_conn.commit()

        assert rebuild_meeting_index(seeded_conn, "fx-kickoff") == 0
        chunk_count = seeded_conn.execute(
            "SELECT COUNT(*) AS n FROM meeting_chunks WHERE meeting_id = ?",
            ("fx-kickoff",),
        ).fetchone()["n"]
        fts_count = seeded_conn.execute(
            "SELECT COUNT(*) AS n FROM meeting_chunk_fts WHERE meeting_id = ?",
            ("fx-kickoff",),
        ).fetchone()["n"]
        vector_hits = adapter.search(
            "versioned envelope", limit=10, meeting_ids={"fx-kickoff"}
        )
    finally:
        configure_vector_adapter(NullVectorAdapter())

    assert chunk_count == 0
    assert fts_count == 0
    assert vector_hits == []


def test_configured_loader_selects_backend_and_reloads_per_database_signature(
    indexed_conn,
):
    """Backend choice is explicit and cached adapters reflect current SQLite chunks."""
    loader = ConfiguredVectorAdapterLoader()

    assert isinstance(loader.load(indexed_conn, backend="none"), NullVectorAdapter)
    first = loader.load(indexed_conn, backend="deterministic")
    assert first.search("schema revision", limit=5)
    assert loader.load(indexed_conn, backend="deterministic") is first

    indexed_conn.execute(
        "UPDATE meeting_chunks SET text = ? WHERE chunk_id = ("
        "SELECT chunk_id FROM meeting_chunks ORDER BY chunk_id LIMIT 1)",
        ("database signature sentinel",),
    )
    indexed_conn.commit()
    refreshed = loader.load(indexed_conn, backend="deterministic")

    assert refreshed is not first
    assert refreshed.search("database signature sentinel", limit=1)
    with pytest.raises(ValueError, match="Unsupported VECTOR_BACKEND"):
        loader.load(indexed_conn, backend="implicit-live-provider")


def test_evidence_fixture_has_request_local_labels(evidence):
    """Downstream query tests receive evidence in the Task 4 public shape."""
    assert [item.citation_id for item in evidence] == ["c1", "c2"]
    assert all("schema" in item.text_fragment.casefold() for item in evidence)


def test_app_caches_the_configured_adapter_by_database_signature():
    """Reruns must not reuse an offline index after SQLite chunk data changes."""
    source = (Path(__file__).parent.parent / "app.py").read_text()

    assert "def get_vector_adapter(" in source
    assert "@st.cache_resource" in source
    assert "database_signature(conn)" in source


def test_meetings_saved_before_indexing_existed_are_backfilled_once(indexed_conn):
    from storage import db
    from storage.meeting_knowledge import index_unindexed_meetings

    meeting_id = db.save_meeting(indexed_conn, title="Old meeting", meeting_date="2026-08-01",
                                 raw_notes="The legacy exporter owns the nightly report.")
    assert index_unindexed_meetings(indexed_conn) == 1
    assert indexed_conn.execute("SELECT COUNT(*) AS n FROM meeting_chunks WHERE meeting_id = ?",
                                (meeting_id,)).fetchone()["n"] > 0
    assert index_unindexed_meetings(indexed_conn) == 0


def test_app_backfills_the_index_when_it_opens_the_database():
    source = (Path(__file__).parent.parent / "app.py").read_text()
    assert "index_unindexed_meetings(conn)" in source
