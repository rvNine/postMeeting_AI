"""Deterministic, source-preserving meeting-note chunking."""
from hashlib import sha256

from query.models import ChunkDraft
from storage.meeting_knowledge import MeetingContextRow


def _boundary_after_separator(text: str, start: int, limit: int) -> int | None:
    for separator in ("\n\n", "\n"):
        index = text.rfind(separator, start + 1, limit + 1)
        if index >= start:
            return index + len(separator)
    return None


def chunk_meeting(
    meeting: MeetingContextRow,
    *,
    max_chars: int = 1200,
    overlap: int = 160,
) -> list[ChunkDraft]:
    """Return ordered chunks whose text is always an exact notes substring."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")

    notes = meeting.raw_notes
    if not notes:
        return []

    chunks: list[ChunkDraft] = []
    start = 0
    sequence = 0
    while start < len(notes):
        limit = min(start + max_chars, len(notes))
        end = limit
        if limit < len(notes):
            end = _boundary_after_separator(notes, start, limit) or limit
        text = notes[start:end]
        chunk_id = sha256(
            "\x1f".join((meeting.meeting_id, str(sequence), text)).encode()
        ).hexdigest()[:24]
        chunks.append(ChunkDraft(
            chunk_id=chunk_id,
            meeting_id=meeting.meeting_id,
            sequence=sequence,
            text=text,
            source_label="meeting notes",
            start_offset=start,
            end_offset=end,
        ))
        if end == len(notes):
            break
        start = end - overlap
        sequence += 1
    return chunks
