"""Persistence helpers for meeting knowledge metadata.

This module deliberately owns only meeting-level context.  Chunks and query
logic belong to later layers.
"""
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import sqlite3


SUPPORTED_LINK_TYPES = frozenset({
    "continues", "supersedes", "depends_on", "reviews", "implements", "follow_up_to",
})


@dataclass(frozen=True)
class Participant:
    name: str
    role: str | None = None


@dataclass(frozen=True)
class MeetingLink:
    source_meeting_id: str
    target_meeting_id: str
    link_type: str
    source_quote: str
    confidence: float


@dataclass(frozen=True)
class MeetingContextRow:
    meeting_id: str
    title: str
    meeting_date: str
    program_name: str | None
    program_phase: str | None
    meeting_sequence: int | None
    facilitator: str | None
    source_type: str | None
    participants: tuple[Participant, ...]
    raw_notes: str
    fixture_set: str | None


def _normalise_link(link: MeetingLink) -> MeetingLink:
    return MeetingLink(
        source_meeting_id=link.source_meeting_id.strip(),
        target_meeting_id=link.target_meeting_id.strip(),
        link_type=link.link_type.strip(),
        source_quote=link.source_quote.strip(),
        confidence=link.confidence,
    )


def validate_meeting_links(
    conn: sqlite3.Connection,
    links: Iterable[MeetingLink],
) -> None:
    """Validate directed links against meetings in ``conn`` before insertion."""
    seen_keys: set[tuple[str, str, str]] = set()
    meeting_ids = {
        row["id"] for row in conn.execute("SELECT id FROM meetings").fetchall()
    }
    for raw_link in links:
        link = _normalise_link(raw_link)
        if link.source_meeting_id not in meeting_ids:
            raise ValueError(f"source meeting not found: {link.source_meeting_id}")
        if link.target_meeting_id not in meeting_ids:
            raise ValueError(f"target meeting not found: {link.target_meeting_id}")
        if link.link_type not in SUPPORTED_LINK_TYPES:
            raise ValueError(f"unsupported link type: {link.link_type}")
        if not link.source_quote:
            raise ValueError("source quote must not be empty")
        if not 0 <= link.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        key = (link.source_meeting_id, link.target_meeting_id, link.link_type)
        if key in seen_keys:
            raise ValueError(f"duplicate link: {key}")
        seen_keys.add(key)


def list_meeting_links(
    conn: sqlite3.Connection,
    meeting_id: str | None = None,
) -> list[MeetingLink]:
    """Return validated persisted links in stable directed-key order."""
    query = (
        "SELECT source_meeting_id, target_meeting_id, link_type, source_quote, confidence "
        "FROM meeting_links"
    )
    parameters: tuple[str, ...] = ()
    if meeting_id is not None:
        query += " WHERE source_meeting_id = ? OR target_meeting_id = ?"
        parameters = (meeting_id, meeting_id)
    query += " ORDER BY source_meeting_id, target_meeting_id, link_type"
    return [
        MeetingLink(
            source_meeting_id=row["source_meeting_id"],
            target_meeting_id=row["target_meeting_id"],
            link_type=row["link_type"],
            source_quote=row["source_quote"],
            confidence=row["confidence"],
        )
        for row in conn.execute(query, parameters).fetchall()
    ]


def upsert_meeting_metadata(
    conn: sqlite3.Connection,
    meeting_id: str,
    *,
    program_name: str | None,
    program_phase: str | None,
    meeting_sequence: int | None,
    facilitator: str | None,
    source_type: str | None,
    fixture_set: str | None,
    participants: Sequence[Participant],
) -> None:
    """Replace the metadata and ordered participant list for one meeting.

    The caller owns transaction boundaries so a fixture seed can remain atomic.
    """
    conn.execute(
        "INSERT INTO meeting_metadata (meeting_id, program_name, program_phase, "
        "meeting_sequence, facilitator, source_type, fixture_set) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(meeting_id) DO UPDATE SET "
        "program_name = excluded.program_name, program_phase = excluded.program_phase, "
        "meeting_sequence = excluded.meeting_sequence, facilitator = excluded.facilitator, "
        "source_type = excluded.source_type, fixture_set = excluded.fixture_set",
        (meeting_id, program_name, program_phase, meeting_sequence, facilitator,
         source_type, fixture_set),
    )
    conn.execute("DELETE FROM meeting_participants WHERE meeting_id = ?", (meeting_id,))
    conn.executemany(
        "INSERT INTO meeting_participants (meeting_id, participant_order, name, role) "
        "VALUES (?,?,?,?)",
        [(meeting_id, order, participant.name, participant.role)
         for order, participant in enumerate(participants)],
    )


def load_meeting_context(conn: sqlite3.Connection, meeting_id: str) -> MeetingContextRow:
    row = conn.execute(
        "SELECT meetings.id, meetings.title, meetings.meeting_date, meetings.raw_notes, "
        "meeting_metadata.program_name, meeting_metadata.program_phase, "
        "meeting_metadata.meeting_sequence, meeting_metadata.facilitator, "
        "meeting_metadata.source_type, meeting_metadata.fixture_set "
        "FROM meetings LEFT JOIN meeting_metadata ON meeting_metadata.meeting_id = meetings.id "
        "WHERE meetings.id = ?",
        (meeting_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"meeting not found: {meeting_id}")
    participant_rows = conn.execute(
        "SELECT name, role FROM meeting_participants WHERE meeting_id = ? "
        "ORDER BY participant_order",
        (meeting_id,),
    ).fetchall()
    return MeetingContextRow(
        meeting_id=row["id"], title=row["title"], meeting_date=row["meeting_date"],
        program_name=row["program_name"], program_phase=row["program_phase"],
        meeting_sequence=row["meeting_sequence"], facilitator=row["facilitator"],
        source_type=row["source_type"],
        participants=tuple(Participant(name=item["name"], role=item["role"])
                           for item in participant_rows),
        raw_notes=row["raw_notes"], fixture_set=row["fixture_set"],
    )


def persist_chunks(
    conn: sqlite3.Connection,
    chunks: Iterable["ChunkDraft"],
    *,
    meeting_id: str | None = None,
) -> int:
    """Replace selected meetings' chunks and FTS rows, including with no chunks."""
    from query.models import ChunkDraft

    chunk_list = list(chunks)
    chunk_meeting_ids = {chunk.meeting_id for chunk in chunk_list}
    if meeting_id is not None:
        if chunk_meeting_ids - {meeting_id}:
            raise ValueError("all replacement chunks must belong to meeting_id")
        meeting_ids = [meeting_id]
    else:
        meeting_ids = sorted(chunk_meeting_ids)
    if not meeting_ids:
        return 0
    placeholders = ", ".join("?" for _ in meeting_ids)
    titles = {
        row["id"]: row["title"]
        for row in conn.execute(
            f"SELECT id, title FROM meetings WHERE id IN ({placeholders})", meeting_ids,
        ).fetchall()
    }
    with conn:
        conn.execute(
            f"DELETE FROM meeting_chunk_fts WHERE meeting_id IN ({placeholders})", meeting_ids,
        )
        conn.execute(
            f"DELETE FROM meeting_chunks WHERE meeting_id IN ({placeholders})", meeting_ids,
        )
        if chunk_list:
            conn.executemany(
                "INSERT INTO meeting_chunks "
                "(chunk_id, meeting_id, sequence, text, source_label, start_offset, end_offset) "
                "VALUES (?,?,?,?,?,?,?)",
                [
                    (chunk.chunk_id, chunk.meeting_id, chunk.sequence, chunk.text,
                     chunk.source_label, chunk.start_offset, chunk.end_offset)
                    for chunk in chunk_list
                ],
            )
            conn.executemany(
                "INSERT INTO meeting_chunk_fts (chunk_id, meeting_id, title, text, source_label) "
                "VALUES (?,?,?,?,?)",
                [
                    (chunk.chunk_id, chunk.meeting_id, titles[chunk.meeting_id],
                     chunk.text, chunk.source_label)
                    for chunk in chunk_list
                ],
            )
    return len(chunk_list)


def rebuild_meeting_index(conn: sqlite3.Connection, meeting_id: str) -> int:
    """Regenerate one meeting's deterministic chunks and corresponding FTS rows."""
    from query.chunking import chunk_meeting
    from query.vector import configured_vector_adapter

    chunks = chunk_meeting(load_meeting_context(conn, meeting_id))
    count = persist_chunks(conn, chunks, meeting_id=meeting_id)
    configured_vector_adapter().replace_meeting(meeting_id, chunks)
    return count


def index_unindexed_meetings(conn: sqlite3.Connection) -> int:
    """Index every meeting that has no chunks yet (e.g. saved before indexing
    existed). Returns how many meetings gained chunks; safe to call on every start."""
    meeting_ids = [
        row["id"] for row in conn.execute(
            "SELECT id FROM meetings WHERE id NOT IN (SELECT meeting_id FROM meeting_chunks) "
            "ORDER BY id"
        ).fetchall()
    ]
    return sum(1 for meeting_id in meeting_ids if rebuild_meeting_index(conn, meeting_id) > 0)


def rebuild_fixture_index(conn: sqlite3.Connection) -> int:
    """Rebuild every currently seeded fixture meeting in stable canonical-ID order."""
    meeting_ids = [
        row["meeting_id"]
        for row in conn.execute(
            "SELECT meeting_id FROM meeting_metadata WHERE fixture_set IS NOT NULL "
            "ORDER BY meeting_id"
        ).fetchall()
    ]
    return sum(rebuild_meeting_index(conn, meeting_id) for meeting_id in meeting_ids)


def is_fixture_meeting(conn: sqlite3.Connection, meeting_id: str) -> bool:
    """Whether the meeting belongs to a synthetic fixture set (and is read-only)."""
    row = conn.execute(
        "SELECT fixture_set FROM meeting_metadata WHERE meeting_id = ?", (meeting_id,)
    ).fetchone()
    return row is not None and row["fixture_set"] is not None


def list_filter_options(conn: sqlite3.Connection) -> dict[str, list]:
    """Distinct values for each query filter, sorted; deleted records are excluded."""
    def distinct(sql: str) -> list[str]:
        values = {" ".join(row[0].split()) for row in conn.execute(sql) if row[0] and row[0].strip()}
        return sorted(values, key=str.casefold)

    meetings = [
        (row["id"], f"{row['meeting_date']} · {row['title']}")
        for row in conn.execute("SELECT id, meeting_date, title FROM meetings ORDER BY meeting_date, id")
    ]
    return {
        "meetings": meetings,
        "participants": distinct("SELECT name FROM meeting_participants"),
        "owners": distinct(
            "SELECT owner FROM action_items WHERE deleted = 0 "
            "UNION SELECT owner FROM risks WHERE deleted = 0 "
            "UNION SELECT owner FROM dependencies WHERE deleted = 0"
        ),
        "severities": distinct("SELECT severity FROM risks WHERE deleted = 0"),
        "program_phases": distinct("SELECT program_phase FROM meeting_metadata"),
    }
