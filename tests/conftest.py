"""Shared test fixtures. No test in this suite may touch the network."""
from collections.abc import Mapping
from pathlib import Path
import re

import pytest

from agent.llm_client import LLMResult
from fixtures.technical_standardization.seed import seed_fixture_set
from query.models import AnswerDraft, ChunkRecord, EvidenceItem
from query.vector import DeterministicVectorAdapter
from storage import db
from storage.meeting_knowledge import (
    MeetingContextRow,
    Participant,
    rebuild_fixture_index,
)


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "technical_standardization"


class StubLLMClient:
    """Returns queued responses in order and records what it was asked.

    Queue items may be a Pydantic model (returned as LLMResult.value), a plain
    string (for `complete`), or an Exception instance (raised).
    """

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def _next(self, kind: str, system: str, user: str, temperature: float) -> LLMResult:
        self.calls.append({"kind": kind, "system": system, "user": user,
                           "temperature": temperature})
        if not self._responses:
            raise AssertionError("StubLLMClient ran out of queued responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(value=item, raw=str(item), tokens=100, latency_ms=10)

    def parse(self, system, user, schema, *, temperature=0.1):
        return self._next("parse", system, user, temperature)

    def complete(self, system, user, *, temperature=0.4):
        return self._next("complete", system, user, temperature)



class GoldenAnswerClient:
    """Offline answer stub for golden cases.

    Cites every supplied evidence item whose quote contains an expected phrase,
    and answers not_found when none does. It only ever cites IDs present in the
    prompt, so verification still decides whether the citations are real.
    """

    _ITEM_RE = re.compile(r"^\[([cr]\d+)\] ", re.MULTILINE)

    def __init__(self, expected_phrases):
        self._phrases = [phrase.casefold() for phrase in expected_phrases]
        self.calls: list[dict] = []

    def parse(self, system, user, schema, *, temperature=0.1):
        self.calls.append({"kind": "parse", "system": system, "user": user,
                           "temperature": temperature})
        parts = self._ITEM_RE.split(user.split("\nEvidence:\n", 1)[1])
        cited = [
            citation_id
            for citation_id, body in zip(parts[1::2], parts[2::2])
            if any(phrase in body.split("; quote=", 1)[-1].casefold() for phrase in self._phrases)
        ]
        draft = (AnswerDraft(status="answered", answer="Golden answer.", citation_ids=cited)
                 if cited else AnswerDraft(status="not_found"))
        return LLMResult(value=draft, raw=draft.model_dump_json(), tokens=0, latency_ms=0)

    def complete(self, system, user, *, temperature=0.4):
        raise AssertionError("GoldenAnswerClient only answers parse calls")

@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def seeded_conn(conn):
    seed_fixture_set(conn, FIXTURE_DIR)
    return conn


@pytest.fixture
def indexed_conn(seeded_conn):
    rebuild_fixture_index(seeded_conn)
    return seeded_conn


@pytest.fixture
def stub_client():
    def _make(responses: list) -> StubLLMClient:
        return StubLLMClient(responses)
    return _make


@pytest.fixture
def sample_meeting() -> MeetingContextRow:
    return MeetingContextRow(
        meeting_id="fx-kickoff",
        title="LatticeBridge kickoff and vocabulary",
        meeting_date="2026-09-01",
        program_name="LatticeBridge",
        program_phase="kickoff",
        meeting_sequence=1,
        facilitator="Mira Vale",
        source_type="meeting_notes",
        participants=(Participant("Mira Vale", "program lead"),),
        raw_notes=(
            "# Kickoff\n\n"
            "The schema revision establishes the migration baseline.\n\n"
            "Teams will review the migration plan before pilot validation.\n"
        ),
        fixture_set="latticebridge-v1",
    )


@pytest.fixture
def chunk_a() -> ChunkRecord:
    return ChunkRecord(
        chunk_id="chunk-a", meeting_id="fx-kickoff", sequence=0,
        text="The migration schema has one baseline.", source_label="meeting notes",
    )


@pytest.fixture
def chunk_b() -> ChunkRecord:
    return ChunkRecord(
        chunk_id="chunk-b", meeting_id="fx-kickoff", sequence=1,
        text="Migration review needs an owner.", source_label="meeting notes",
    )


@pytest.fixture
def vector(indexed_conn) -> DeterministicVectorAdapter:
    rows = indexed_conn.execute(
        "SELECT chunk_id, meeting_id, sequence, text, source_label, start_offset, end_offset "
        "FROM meeting_chunks ORDER BY meeting_id, sequence"
    ).fetchall()
    return DeterministicVectorAdapter([
        ChunkRecord(
            chunk_id=row["chunk_id"], meeting_id=row["meeting_id"],
            sequence=row["sequence"], text=row["text"], source_label=row["source_label"],
            start_offset=row["start_offset"], end_offset=row["end_offset"],
        )
        for row in rows
    ])


@pytest.fixture
def evidence(indexed_conn, vector) -> list[EvidenceItem]:
    """Stable, request-labelled schema-revision evidence for later query tests."""
    hits = vector.search("schema revision", limit=2)
    assert len(hits) == 2, "fixture set must contain two schema-revision chunks"
    chunk_ids = [hit.chunk_id for hit in hits]
    placeholders = ", ".join("?" for _ in chunk_ids)
    rows = {
        row["chunk_id"]: row
        for row in indexed_conn.execute(
            "SELECT chunks.chunk_id, chunks.meeting_id, chunks.text, meetings.title, "
            "meetings.meeting_date FROM meeting_chunks AS chunks "
            "JOIN meetings ON meetings.id = chunks.meeting_id "
            f"WHERE chunks.chunk_id IN ({placeholders})",
            chunk_ids,
        ).fetchall()
    }
    return [
        EvidenceItem(
            citation_id=f"c{index}", chunk_id=hit.chunk_id,
            meeting_id=rows[hit.chunk_id]["meeting_id"],
            title=rows[hit.chunk_id]["title"],
            meeting_date=rows[hit.chunk_id]["meeting_date"],
            text_fragment=rows[hit.chunk_id]["text"], score=hit.score,
        )
        for index, hit in enumerate(hits, start=1)
    ]


@pytest.fixture
def query_service(indexed_conn, stub_client, vector):
    """Construct the Task 7 service lazily without importing it during Task 4."""
    from query.service import QueryService

    return QueryService(
        indexed_conn,
        stub_client([AnswerDraft(status="not_found")]),
        vector,
    )


@pytest.fixture
def golden_query_service(indexed_conn, vector):
    """Build a QueryService whose model cites evidence matching one golden case."""
    from query.service import QueryService

    def _make(case) -> QueryService:
        phrases = case["expected_phrases"] if isinstance(case, Mapping) else case.expected_phrases
        return QueryService(indexed_conn, GoldenAnswerClient(phrases), vector)
    return _make
