from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    meeting_id: str
    sequence: int
    text: str
    source_label: str
    start_offset: int | None = None
    end_offset: int | None = None


ChunkDraft = ChunkRecord


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    score: float


@dataclass(frozen=True)
class QueryFilters:
    date_from: str | None = None
    date_to: str | None = None
    meeting_id: str | None = None
    participant: str | None = None
    owner: str | None = None
    record_type: str | None = None
    severity: str | None = None
    program_phase: str | None = None


@dataclass(frozen=True)
class EvidenceItem:
    citation_id: str
    chunk_id: str
    meeting_id: str
    title: str
    meeting_date: str
    text_fragment: str
    score: float
    record_type: str | None = None
    record_id: str | None = None
    relationship_label: str | None = None


@dataclass(frozen=True)
class Citation:
    citation_id: str
    meeting_id: str
    title: str
    meeting_date: str
    quote: str
    record_type: str | None = None
    record_id: str | None = None
    chunk_id: str | None = None
    relationship_label: str | None = None


class AnswerDraft(BaseModel):
    status: Literal["answered", "not_found"]
    answer: str | None = None
    citation_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class VerifiedAnswer:
    status: Literal["answered", "not_found"]
    answer: str | None
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class QueryResult:
    status: Literal["answered", "not_found", "error"]
    answer: str | None
    citations: tuple[Citation, ...]
    error: str | None = None
    applied_filters: tuple[str, ...] = ()
    suggested_filters: tuple[str, ...] = ()
    # Everything the model was shown, for the audit panel; empty when no model call.
    evidence: tuple[EvidenceItem, ...] = ()


@dataclass(frozen=True)
class FilterOptions:
    """Values the Ask meetings filters can offer, all sorted for stable display."""
    meetings: tuple[tuple[str, str], ...]  # (meeting_id, "date · title")
    participants: tuple[str, ...]
    owners: tuple[str, ...]
    severities: tuple[str, ...]
    program_phases: tuple[str, ...]
    record_types: tuple[str, ...] = (
        "action_items", "decisions", "risks", "dependencies", "learnings",
    )
