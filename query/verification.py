"""Deterministic verification of model-produced meeting citations."""
from collections.abc import Sequence
import sqlite3

from query.models import AnswerDraft, Citation, EvidenceItem, VerifiedAnswer


class CitationVerificationError(ValueError):
    """Raised when an answer cites evidence that cannot be verified."""


_RECORD_TABLES = frozenset({"action_items", "decisions", "risks", "dependencies", "learnings"})


def _stored_quote(conn: sqlite3.Connection, item: EvidenceItem) -> str:
    meeting = conn.execute(
        "SELECT raw_notes FROM meetings WHERE id = ?", (item.meeting_id,)
    ).fetchone()
    if meeting is None:
        raise CitationVerificationError(f"meeting not found: {item.meeting_id}")
    if item.chunk_id:
        chunk = conn.execute(
            "SELECT meeting_id, text FROM meeting_chunks WHERE chunk_id = ?",
            (item.chunk_id,),
        ).fetchone()
        if chunk is None or chunk["meeting_id"] != item.meeting_id:
            raise CitationVerificationError(f"chunk not found: {item.chunk_id}")
        return chunk["text"]
    if item.record_type and item.record_id:
        if item.record_type not in _RECORD_TABLES:
            raise CitationVerificationError(f"unsupported record type: {item.record_type}")
        record = conn.execute(
            f"SELECT meeting_id FROM {item.record_type} WHERE id = ?",
            (item.record_id,),
        ).fetchone()
        if record is None or record["meeting_id"] != item.meeting_id:
            raise CitationVerificationError(f"record not found: {item.record_id}")
        # A record's source_quote is itself model output; the notes are the evidence.
        return meeting["raw_notes"]
    return meeting["raw_notes"]


def verify_answer(
    draft: AnswerDraft,
    evidence: Sequence[EvidenceItem],
    conn: sqlite3.Connection,
) -> VerifiedAnswer:
    if draft.status == "not_found":
        if draft.citation_ids:
            raise CitationVerificationError("not_found answers cannot contain citations")
        return VerifiedAnswer(status="not_found", answer=None, citations=())
    if not draft.answer or not draft.answer.strip():
        raise CitationVerificationError("answered response must contain an answer")
    if not draft.citation_ids:
        raise CitationVerificationError("answered response must contain citations")
    by_id = {item.citation_id: item for item in evidence}
    citations: list[Citation] = []
    for citation_id in dict.fromkeys(draft.citation_ids):
        item = by_id.get(citation_id)
        if item is None:
            raise CitationVerificationError(f"citation not supplied: {citation_id}")
        stored = _stored_quote(conn, item)
        quote = item.text_fragment
        if not quote or quote not in stored:
            raise CitationVerificationError(f"citation quote not present: {citation_id}")
        citations.append(Citation(
            citation_id=item.citation_id, meeting_id=item.meeting_id, title=item.title,
            meeting_date=item.meeting_date, quote=quote, record_type=item.record_type,
            record_id=item.record_id, chunk_id=item.chunk_id or None,
            relationship_label=item.relationship_label,
        ))
    return VerifiedAnswer(status="answered", answer=draft.answer, citations=tuple(citations))
