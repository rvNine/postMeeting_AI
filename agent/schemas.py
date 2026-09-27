"""Pydantic domain models. These are the contract between every layer.

Two constraints shape this file:
  * OpenAI strict JSON-schema mode rejects `minimum`/`maximum`, so numeric
    bounds are enforced with validators, which do not reach the schema.
  * Structured Outputs has no date type, so deadlines travel as ISO strings.
"""
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class GapType(StrEnum):
    MISSING_OWNER = "missing_owner"
    MISSING_DEADLINE = "missing_deadline"
    AMBIGUOUS_TASK = "ambiguous_task"
    CONFLICTING_DECISION = "conflicting_decision"
    UNRESOLVED_QUESTION = "unresolved_question"
    UNSUPPORTED_EVIDENCE = "unsupported_evidence"


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


def _check_confidence(value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"confidence must be in [0, 1], got {value}")
    return value


def _check_iso_date(value: str | None) -> str | None:
    if value is None:
        return None
    date.fromisoformat(value)  # raises ValueError on anything but YYYY-MM-DD
    return value


PLACEHOLDER_VALUES = frozenset({
    "null", "none", "nil", "n/a", "tbd", "tbc", "unknown",
    "unassigned", "todo", "-", "--", "?",
})


def normalize_optional_text(value: str | None) -> str | None:
    """Blank, whitespace, and placeholder strings all mean 'the notes did not say'.

    A model asked for JSON null sometimes returns the STRING "null" (or "TBD",
    or "N/A") instead. Those are not people and not dates: treated as real
    values they defeat the gap detection this product is built on, because a
    non-empty string looks like a confirmed owner to every check downstream.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() in PLACEHOLDER_VALUES:
        return None
    return stripped


class Gap(BaseModel):
    id: str
    type: GapType
    severity: Severity
    target_id: str = Field(description="id of the action_item or decision this concerns")
    explanation: str = Field(description="Why this is a gap, in one sentence")
    suggested_question: str = Field(description="What to ask the team, if unresolvable alone")


class ActionItem(BaseModel):
    id: str
    task: str = Field(description="The task, phrased as an imperative")
    owner: str | None = Field(description="Exact name stated in the notes, else null. Never guess.")
    deadline: str | None = Field(description="ISO-8601 YYYY-MM-DD if stated, else null. Never guess.")
    source_quote: str = Field(description="Verbatim span from the notes supporting this item")
    confidence: float

    _v_conf = field_validator("confidence")(_check_confidence)
    _v_owner_norm = field_validator("owner", mode="before")(normalize_optional_text)
    _v_deadline_norm = field_validator("deadline", mode="before")(normalize_optional_text)
    _v_date = field_validator("deadline")(_check_iso_date)


class Decision(BaseModel):
    id: str
    decision: str
    rationale: str | None
    source_quote: str = Field(description="Verbatim span from the notes")
    confidence: float

    _v_conf = field_validator("confidence")(_check_confidence)
    _v_rationale_norm = field_validator("rationale", mode="before")(normalize_optional_text)


class TechnicalRisk(BaseModel):
    id: str
    description: str
    impact: str | None
    likelihood: str | None
    severity: str | None
    mitigation: str | None
    owner: str | None
    source_quote: str
    confidence: float

    _v_conf = field_validator("confidence")(_check_confidence)
    _v_impact = field_validator("impact", mode="before")(normalize_optional_text)
    _v_likelihood = field_validator("likelihood", mode="before")(normalize_optional_text)
    _v_severity = field_validator("severity", mode="before")(normalize_optional_text)
    _v_mitigation = field_validator("mitigation", mode="before")(normalize_optional_text)
    _v_owner = field_validator("owner", mode="before")(normalize_optional_text)


class TechnicalDependency(BaseModel):
    id: str
    description: str
    depends_on: str | None
    blocked_by: str | None
    owner: str | None
    source_quote: str
    confidence: float

    _v_conf = field_validator("confidence")(_check_confidence)
    _v_depends_on = field_validator("depends_on", mode="before")(normalize_optional_text)
    _v_blocked_by = field_validator("blocked_by", mode="before")(normalize_optional_text)
    _v_owner = field_validator("owner", mode="before")(normalize_optional_text)


class TechnicalLearning(BaseModel):
    id: str
    lesson: str
    technical_area: str | None
    validation_status: str | None
    follow_up_experiment: str | None
    source_quote: str
    confidence: float

    _v_conf = field_validator("confidence")(_check_confidence)
    _v_area = field_validator("technical_area", mode="before")(normalize_optional_text)
    _v_status = field_validator("validation_status", mode="before")(normalize_optional_text)
    _v_experiment = field_validator("follow_up_experiment", mode="before")(normalize_optional_text)


class MeetingExtraction(BaseModel):
    """Step 1 output schema."""
    summary: str = Field(description="3-6 sentence narrative summary")
    participants: list[str]
    decisions: list[Decision]
    action_items: list[ActionItem]
    risks: list[TechnicalRisk] = Field(default_factory=list)
    dependencies: list[TechnicalDependency] = Field(default_factory=list)
    learnings: list[TechnicalLearning] = Field(default_factory=list)


class ReviewResult(BaseModel):
    """Step 2 output schema."""
    gaps: list[Gap]
    overall_confidence: float
    reviewer_notes: str

    _v_conf = field_validator("overall_confidence")(_check_confidence)


@dataclass(frozen=True)
class OwnerHint:
    """An owner a human supplied where the agent found none.

    NEVER sent to a model. A model told "Dan usually owns alerting" is one
    prompt away from filling it in, which is the fabrication this product
    exists to prevent. This reaches the manager beside a blank field only.
    """
    owner: str
    times_assigned: int
    example_task: str


@dataclass(frozen=True)
class PriorCommitment:
    """A commitment from an earlier meeting: owner and deadline both present.

    There is no completion tracking, so this means "previously committed and
    never marked done here", NOT "verified still open".
    """
    task: str
    owner: str
    deadline: str
    meeting_title: str
    meeting_date: str


@dataclass(frozen=True)
class MeetingContext:
    """What the agent knows beyond today's notes.

    Plain data, so `agent/` can consume it without importing `storage/`.
    """
    prior_commitments: tuple[PriorCommitment, ...] = ()
    owner_hints: tuple[OwnerHint, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.prior_commitments and not self.owner_hints


class TriageVerdict(StrEnum):
    SELF_RESOLVABLE = "self_resolvable"
    NEEDS_HUMAN = "needs_human"


class GapTriage(BaseModel):
    """The agent's decision about one gap: can I fix this, or must a person?"""
    gap_id: str
    verdict: TriageVerdict
    supporting_quote: str | None = Field(
        description="Verbatim span of the notes that answers this gap. Required "
                    "for self_resolvable; null otherwise. Code verifies it.")
    reasoning: str


class TriageResult(BaseModel):
    """Step 3 output schema."""
    triages: list[GapTriage]
