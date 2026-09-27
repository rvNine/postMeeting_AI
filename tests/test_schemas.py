from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from agent.schemas import (
    ActionItem,
    Decision,
    Gap,
    GapTriage,
    GapType,
    MeetingContext,
    MeetingExtraction,
    OwnerHint,
    PriorCommitment,
    ReviewResult,
    Severity,
    TechnicalDependency,
    TechnicalLearning,
    TechnicalRisk,
    TriageResult,
    TriageVerdict,
)


@pytest.mark.parametrize("raw", ["null", "TBD", "N/A", "  NULL  "])
def test_action_item_owner_placeholder_strings_normalize_to_none(raw):
    """The 'null' bug: the model can emit the STRING 'null' instead of JSON null."""
    item = ActionItem(id="a1", task="x", owner=raw, deadline=None,
                      source_quote="q", confidence=0.5)
    assert item.owner is None


def test_action_item_owner_real_name_is_preserved_unchanged():
    item = ActionItem(id="a1", task="x", owner="Priya", deadline=None,
                      source_quote="q", confidence=0.5)
    assert item.owner == "Priya"


def test_action_item_deadline_placeholder_string_normalizes_to_none():
    """Normalisation must run before the ISO-date check, or this raises instead."""
    item = ActionItem(id="a1", task="x", owner=None, deadline="null",
                      source_quote="q", confidence=0.5)
    assert item.deadline is None


def test_action_item_valid_deadline_still_passes_iso_check():
    item = ActionItem(id="a1", task="x", owner=None, deadline="2026-10-02",
                      source_quote="q", confidence=0.5)
    assert item.deadline == "2026-10-02"


def test_action_item_invalid_deadline_still_raises():
    """Normalisation must not swallow genuine bad input."""
    with pytest.raises(ValidationError):
        ActionItem(id="a1", task="x", owner=None, deadline="next Friday",
                   source_quote="q", confidence=0.5)


def test_decision_rationale_placeholder_string_normalizes_to_none():
    decision = Decision(id="d1", decision="Use Postgres", rationale="N/A",
                        source_quote="q", confidence=0.9)
    assert decision.rationale is None


def test_action_item_allows_null_owner_and_deadline():
    """The null-over-guess rule depends on these being nullable."""
    item = ActionItem(
        id="a1", task="Benchmark Postgres", owner=None, deadline=None,
        source_quote="we should benchmark postgres", confidence=0.8,
    )
    assert item.owner is None
    assert item.deadline is None


def test_action_item_rejects_confidence_above_one():
    with pytest.raises(ValidationError):
        ActionItem(id="a1", task="x", owner=None, deadline=None,
                   source_quote="q", confidence=1.4)


def test_action_item_rejects_confidence_below_zero():
    with pytest.raises(ValidationError):
        ActionItem(id="a1", task="x", owner=None, deadline=None,
                   source_quote="q", confidence=-0.1)


def test_action_item_rejects_malformed_deadline():
    with pytest.raises(ValidationError):
        ActionItem(id="a1", task="x", owner=None, deadline="next friday",
                   source_quote="q", confidence=0.5)


def test_action_item_accepts_iso_deadline():
    item = ActionItem(id="a1", task="x", owner="Priya", deadline="2026-10-02",
                      source_quote="q", confidence=0.9)
    assert item.deadline == "2026-10-02"


def test_action_item_requires_source_quote():
    with pytest.raises(ValidationError):
        ActionItem(id="a1", task="x", owner=None, deadline=None, confidence=0.5)


def test_schema_has_no_unsupported_jsonschema_keywords():
    """OpenAI strict mode rejects minimum/maximum. Guard against reintroduction."""
    schema = str(MeetingExtraction.model_json_schema())
    assert "minimum" not in schema
    assert "maximum" not in schema


def test_gap_carries_an_id_and_severity():
    gap = Gap(id="g1", type=GapType.MISSING_OWNER, severity=Severity.BLOCKING,
              target_id="a1", explanation="No owner stated.",
              suggested_question="Who is taking this?")
    assert gap.severity is Severity.BLOCKING


def test_meeting_extraction_composes():
    extraction = MeetingExtraction(
        summary="We discussed the migration.",
        participants=["Priya", "Sam"],
        decisions=[Decision(id="d1", decision="Use Postgres", rationale=None,
                            source_quote="we're going with postgres", confidence=0.9)],
        action_items=[ActionItem(id="a1", task="Benchmark Postgres", owner="Sam",
                                 deadline="2026-10-02", source_quote="Sam to benchmark",
                                 confidence=0.95)],
    )
    assert len(extraction.action_items) == 1


def test_meeting_extraction_defaults_technical_lists_to_empty():
    extraction = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[])
    assert extraction.risks == []
    assert extraction.dependencies == []
    assert extraction.learnings == []


def test_technical_risk_normalizes_optional_placeholders():
    risk = TechnicalRisk(
        id="r1", description="The migration may exceed the window.",
        impact=" TBD ", likelihood="unknown", severity="high",
        mitigation="Add a rollback test", owner="null",
        source_quote="migration may exceed the window", confidence=0.8)
    assert risk.impact is None
    assert risk.likelihood is None
    assert risk.owner is None


def test_technical_records_reject_confidence_outside_range():
    with pytest.raises(ValidationError):
        TechnicalLearning(
            id="l1", lesson="Use smaller batches", technical_area=None,
            validation_status=None, follow_up_experiment=None,
            source_quote="use smaller batches", confidence=1.1)


# New tests for context and triage schemas


def test_meeting_context_defaults_to_empty():
    """Empty context is the first-meeting case and must be the default."""
    ctx = MeetingContext()
    assert ctx.prior_commitments == ()
    assert ctx.owner_hints == ()
    assert ctx.is_empty is True


def test_meeting_context_is_not_empty_with_either_half():
    hint = OwnerHint(owner="Dan", times_assigned=3, example_task="Add alerting")
    assert MeetingContext(owner_hints=(hint,)).is_empty is False
    commitment = PriorCommitment(task="Write the plan", owner="Sam",
                                 deadline="2026-09-12", meeting_title="Sprint 23",
                                 meeting_date="2026-09-01")
    assert MeetingContext(prior_commitments=(commitment,)).is_empty is False


def test_context_dataclasses_are_frozen():
    """Context is passed across a layer boundary; it must not be mutable there."""
    hint = OwnerHint(owner="Dan", times_assigned=1, example_task="t")
    with pytest.raises(FrozenInstanceError):
        hint.owner = "Sam"


def test_gap_triage_requires_a_verdict():
    t = GapTriage(gap_id="g1", verdict=TriageVerdict.NEEDS_HUMAN,
                  supporting_quote=None, reasoning="nobody is named")
    assert t.verdict is TriageVerdict.NEEDS_HUMAN


def test_gap_triage_carries_a_supporting_quote_when_self_resolvable():
    t = GapTriage(gap_id="g1", verdict=TriageVerdict.SELF_RESOLVABLE,
                  supporting_quote="Sam will write the plan", reasoning="stated")
    assert t.supporting_quote == "Sam will write the plan"


def test_triage_result_schema_has_no_unsupported_jsonschema_keywords():
    """OpenAI strict mode rejects minimum/maximum. Same guard as MeetingExtraction."""
    schema = str(TriageResult.model_json_schema())
    assert "minimum" not in schema
    assert "maximum" not in schema
