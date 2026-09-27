"""Regression tests built from small, representative technical meeting fixtures.

These fixtures live under fixtures/technical/, separate from
fixtures/sample_meetings/, so the paid evaluation harness (fixtures/loader.py,
scoped to fixtures/sample_meetings/) does not silently gain new live-API eval
cases. Records here are constructed by hand, from text known to be in (or
deliberately absent from) the fixture, and checked with the same pure gap
detection the pipeline uses — no model calls.
"""
from pathlib import Path

from agent.gaps import detect_evidence_gaps, detect_structural_gaps
from agent.schemas import (
    ActionItem, Decision, GapType, MeetingExtraction, Severity,
    TechnicalDependency, TechnicalLearning, TechnicalRisk,
)

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "technical"


def _load(name: str) -> str:
    return (_FIXTURES_DIR / name).read_text()


def test_fixture_files_exist_with_expected_content():
    design = _load("1_design_review.md")
    risk_dep = _load("2_risk_dependency_review.md")
    unsupported = _load("3_unsupported_evidence.md")
    assert "retry handling into the API layer" in design
    assert "cache saturation" in risk_dep
    assert "Redis" in unsupported


def test_supported_decision_action_and_learning_produce_no_evidence_gaps():
    notes = _load("1_design_review.md")
    decision = Decision(
        id="d1", decision="Move retry handling into the API layer",
        rationale="the worker swallowed errors",
        source_quote="move retry handling into the API layer", confidence=0.9)
    action = ActionItem(
        id="a1", task="Write the migration plan", owner="Sam",
        deadline="2026-10-02",
        source_quote="Sam will write the migration plan by 2026-10-02",
        confidence=0.9)
    learning = TechnicalLearning(
        id="l1", lesson="Smaller batches reduce retry failures",
        technical_area=None, validation_status=None, follow_up_experiment=None,
        source_quote="Smaller batches reduced retry failures during the last test",
        confidence=0.85)
    extraction = MeetingExtraction(
        summary="s", participants=["Sam"], decisions=[decision],
        action_items=[action], learnings=[learning])
    assert detect_evidence_gaps(extraction, notes) == []


def test_supported_risk_and_dependency_produce_no_evidence_gaps():
    notes = _load("2_risk_dependency_review.md")
    risk = TechnicalRisk(
        id="r1", description="Cache saturation during launch", impact=None,
        likelihood=None, severity=None,
        mitigation="add capacity before the load test", owner=None,
        source_quote="cache saturation during the launch window", confidence=0.8)
    dependency = TechnicalDependency(
        id="dep1", description="Launch depends on the API contract",
        depends_on="API team", blocked_by=None, owner=None,
        source_quote="Launch depends on the API team publishing the contract",
        confidence=0.8)
    extraction = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[],
        risks=[risk], dependencies=[dependency])
    assert detect_evidence_gaps(extraction, notes) == []


def test_invented_action_item_quote_is_unsupported_evidence_and_blocking():
    notes = _load("3_unsupported_evidence.md")
    action = ActionItem(
        id="a1", task="Deploy the new cache", owner="Dan", deadline="2026-10-02",
        source_quote="Dan will deploy the new cache tonight", confidence=0.6)
    extraction = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[action])
    gaps = detect_evidence_gaps(extraction, notes)
    assert len(gaps) == 1
    assert gaps[0].type is GapType.UNSUPPORTED_EVIDENCE
    assert gaps[0].severity is Severity.BLOCKING
    assert gaps[0].id == "evidence::action_item::a1"


def test_invented_risk_quote_is_unsupported_evidence_and_warning():
    """Same fixture, same invented-quote failure mode, but on a risk: severity
    must be a WARNING, not BLOCKING — the taxonomy from agent/gaps.py."""
    notes = _load("3_unsupported_evidence.md")
    risk = TechnicalRisk(
        id="r1", description="Redis eviction under load", impact=None,
        likelihood=None, severity=None, mitigation=None, owner=None,
        source_quote="Redis will evict keys under heavy load", confidence=0.5)
    extraction = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[], risks=[risk])
    gaps = detect_evidence_gaps(extraction, notes)
    assert len(gaps) == 1
    assert gaps[0].type is GapType.UNSUPPORTED_EVIDENCE
    assert gaps[0].severity is Severity.WARNING
    assert gaps[0].id == "evidence::risk::r1"


def test_design_review_holds_a_decision_action_and_learning_without_changing_owner_deadline_rules():
    """The design-review text supports a decision, an action item, and a
    learning at once. Adding risks/dependencies/learnings to an extraction must
    not relax or otherwise touch the pre-existing owner/deadline structural
    rule for action items."""
    notes = _load("1_design_review.md")
    decision = Decision(
        id="d1", decision="Move retry handling into the API layer",
        rationale="the worker swallowed errors",
        source_quote="move retry handling into the API layer", confidence=0.9)
    action = ActionItem(
        id="a1", task="Write the migration plan", owner="Sam",
        deadline="2026-10-02",
        source_quote="Sam will write the migration plan by 2026-10-02",
        confidence=0.9)
    learning = TechnicalLearning(
        id="l1", lesson="Smaller batches reduce retry failures",
        technical_area=None, validation_status=None, follow_up_experiment=None,
        source_quote="Smaller batches reduced retry failures during the last test",
        confidence=0.85)
    extraction = MeetingExtraction(
        summary="s", participants=["Sam"], decisions=[decision],
        action_items=[action], learnings=[learning])

    # Owner and deadline are both stated, so the existing structural rule finds
    # nothing to flag, decision/learning notwithstanding.
    assert detect_structural_gaps(extraction) == []
    assert detect_evidence_gaps(extraction, notes) == []

    # The rule itself is unchanged: blanking the owner still trips it, exactly
    # as it does for an extraction with no technical records at all.
    missing_owner = action.model_copy(update={"owner": None})
    extraction_missing_owner = extraction.model_copy(
        update={"action_items": [missing_owner]})
    owner_gaps = detect_structural_gaps(extraction_missing_owner)
    assert any(g.type is GapType.MISSING_OWNER for g in owner_gaps)

    missing_deadline = action.model_copy(update={"deadline": None})
    extraction_missing_deadline = extraction.model_copy(
        update={"action_items": [missing_deadline]})
    deadline_gaps = detect_structural_gaps(extraction_missing_deadline)
    assert any(g.type is GapType.MISSING_DEADLINE for g in deadline_gaps)
