"""Seed the LatticeBridge fixture set into the meeting database.

Run explicitly; the app never seeds on startup:

    python -m fixtures.technical_standardization.seed --db data/meetings.db
"""
import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from fixtures.meeting_manifest import load_fixture_manifest, validate_fixture_manifest
from storage.meeting_knowledge import (
    MeetingLink,
    Participant,
    upsert_meeting_metadata,
    validate_meeting_links,
)

FIXTURE_SET = "latticebridge-v1"
PROGRAM_NAME = "LatticeBridge"
_CHILD_TABLES = (
    "approvals", "gaps", "action_items", "decisions", "risks", "dependencies",
    "learnings", "extractions",
)


@dataclass(frozen=True)
class SeedReport:
    meeting_ids: dict[str, str]
    inserted_meetings: int
    replaced_fixture_rows: int


def _delete_fixture_meetings(conn: sqlite3.Connection, meeting_ids: list[str]) -> None:
    if not meeting_ids:
        return
    placeholders = ", ".join("?" for _ in meeting_ids)
    conn.execute(
        f"DELETE FROM meeting_chunk_fts WHERE meeting_id IN ({placeholders})", meeting_ids,
    )
    for table in _CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE meeting_id IN ({placeholders})", meeting_ids)
    conn.execute(f"DELETE FROM meetings WHERE id IN ({placeholders})", meeting_ids)


def _insert_record(conn: sqlite3.Connection, meeting_id: str, record) -> None:
    fields = record.fields
    if record.record_type == "action_items":
        conn.execute(
            "INSERT INTO action_items (id, meeting_id, task, owner, deadline, source_quote, "
            "confidence, ai_task, ai_owner, ai_deadline, origin, deleted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?, 'fixture', 0)",
            (record.id, meeting_id, fields["task"], fields.get("owner"),
             fields.get("deadline"), record.source_quote, record.confidence,
             fields["task"], fields.get("owner"), fields.get("deadline")),
        )
    elif record.record_type == "decisions":
        conn.execute(
            "INSERT INTO decisions (id, meeting_id, decision, rationale, source_quote, "
            "confidence, deleted) VALUES (?,?,?,?,?,?,0)",
            (record.id, meeting_id, fields["decision"], fields.get("rationale"),
             record.source_quote, record.confidence),
        )
    elif record.record_type == "risks":
        conn.execute(
            "INSERT INTO risks (id, meeting_id, description, impact, likelihood, severity, "
            "mitigation, owner, source_quote, confidence, ai_description, ai_impact, "
            "ai_likelihood, ai_severity, ai_mitigation, ai_owner, origin, deleted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'fixture', 0)",
            (record.id, meeting_id, fields["description"], fields.get("impact"),
             fields.get("likelihood"), fields.get("severity"), fields.get("mitigation"),
             fields.get("owner"), record.source_quote, record.confidence,
             fields["description"], fields.get("impact"), fields.get("likelihood"),
             fields.get("severity"), fields.get("mitigation"), fields.get("owner")),
        )
    elif record.record_type == "dependencies":
        conn.execute(
            "INSERT INTO dependencies (id, meeting_id, description, depends_on, blocked_by, "
            "owner, source_quote, confidence, ai_description, ai_depends_on, ai_blocked_by, "
            "ai_owner, origin, deleted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'fixture', 0)",
            (record.id, meeting_id, fields["description"], fields.get("depends_on"),
             fields.get("blocked_by"), fields.get("owner"), record.source_quote,
             record.confidence, fields["description"], fields.get("depends_on"),
             fields.get("blocked_by"), fields.get("owner")),
        )
    elif record.record_type == "learnings":
        conn.execute(
            "INSERT INTO learnings (id, meeting_id, lesson, technical_area, validation_status, "
            "follow_up_experiment, source_quote, confidence, ai_lesson, ai_technical_area, "
            "ai_validation_status, ai_follow_up_experiment, origin, deleted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'fixture', 0)",
            (record.id, meeting_id, fields["lesson"], fields.get("technical_area"),
             fields.get("validation_status"), fields.get("follow_up_experiment"),
             record.source_quote, record.confidence, fields["lesson"],
             fields.get("technical_area"), fields.get("validation_status"),
             fields.get("follow_up_experiment")),
        )
    else:
        raise ValueError(f"unsupported fixture record type: {record.record_type}")


def seed_fixture_set(conn: sqlite3.Connection, fixture_dir: Path) -> SeedReport:
    """Atomically replace only the owned LatticeBridge fixture-set rows."""
    manifest = load_fixture_manifest(fixture_dir)
    validate_fixture_manifest(manifest)
    links = [
        MeetingLink(
            source_meeting_id=link.source_meeting_id.strip(),
            target_meeting_id=link.target_meeting_id.strip(),
            link_type=link.link_type.strip(),
            source_quote=link.quote.strip(),
            confidence=link.confidence,
        )
        for link in manifest.links
    ]
    meeting_ids = [meeting.meeting_id for meeting in manifest.meetings]
    with conn:
        fixture_rows = conn.execute(
            "SELECT meeting_id FROM meeting_metadata WHERE fixture_set = ?",
            (FIXTURE_SET,),
        ).fetchall()
        replaced_fixture_rows = len(fixture_rows)
        _delete_fixture_meetings(conn, [row["meeting_id"] for row in fixture_rows])
        for meeting in manifest.meetings:
            conn.execute(
                "INSERT INTO meetings (id, title, meeting_date, raw_notes, created_at, status) "
                "VALUES (?,?,?,?,?, 'draft')",
                (meeting.meeting_id, meeting.title, meeting.meeting_date,
                 meeting.raw_markdown, f"{meeting.meeting_date}T00:00:00+00:00"),
            )
            upsert_meeting_metadata(
                conn, meeting.meeting_id, program_name=PROGRAM_NAME,
                program_phase=meeting.phase, meeting_sequence=meeting.sequence,
                facilitator=meeting.facilitator, source_type=meeting.source_type,
                fixture_set=meeting.fixture_set,
                participants=[Participant(item["name"], item.get("role"))
                              for item in meeting.participants],
            )
            conn.execute(
                "INSERT INTO extractions (id, meeting_id, summary, participants, reviewer_notes, "
                "overall_confidence, raw_response, prompt_version, processing_pass, model, "
                "tokens_used, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{meeting.meeting_id}:fixture-extraction", meeting.meeting_id,
                 f"Synthetic fixture extraction for {meeting.title}.",
                 json.dumps([item["name"] for item in meeting.participants]),
                 "Synthetic fixture data; not model generated.", 1.0,
                 "synthetic-fixture", "synthetic-v1", 1, "fixture", 0, 0,
                 f"{meeting.meeting_date}T00:00:00+00:00"),
            )
            for record in meeting.all_records:
                _insert_record(conn, meeting.meeting_id, record)
        validate_meeting_links(conn, links)
        for link in links:
            conn.execute(
                "INSERT INTO meeting_links (source_meeting_id, target_meeting_id, link_type, "
                "source_quote, confidence) VALUES (?,?,?,?,?)",
                (link.source_meeting_id, link.target_meeting_id, link.link_type,
                 link.source_quote, link.confidence),
            )
    # Chunking is deliberately downstream of the atomic seed replacement: it
    # reads the persisted canonical meeting rows and makes the fixture set
    # immediately searchable without changing any extraction data.
    from storage.meeting_knowledge import rebuild_fixture_index

    rebuild_fixture_index(conn)
    return SeedReport(
        meeting_ids={meeting.slug: meeting.meeting_id for meeting in manifest.meetings},
        inserted_meetings=len(manifest.meetings),
        replaced_fixture_rows=replaced_fixture_rows,
    )


FIXTURE_DIR = Path(__file__).parent


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the synthetic LatticeBridge meetings.")
    parser.add_argument("--db", type=Path, required=True, help="SQLite database file to seed")
    args = parser.parse_args(argv)

    from storage import db

    conn = db.connect(args.db)
    try:
        db.init_db(conn)
        report = seed_fixture_set(conn, FIXTURE_DIR)
    finally:
        conn.close()
    print(f"Seeded {report.inserted_meetings} synthetic meetings into {args.db} "
          f"(replaced {report.replaced_fixture_rows} fixture rows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
