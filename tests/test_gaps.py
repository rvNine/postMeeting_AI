from agent.gaps import (
    detect_evidence_gaps,
    detect_structural_gaps,
    is_blocked,
    merge_gaps,
    merge_with_deterministic,
    open_blocking,
)
from agent.schemas import (
    ActionItem,
    Decision,
    Gap,
    GapType,
    MeetingExtraction,
    Severity,
    TechnicalRisk,
)


def _item(id_: str, owner: str | None, deadline: str | None) -> ActionItem:
    return ActionItem(id=id_, task="do the thing", owner=owner, deadline=deadline,
                      source_quote="quote", confidence=0.8)


def _extraction(items: list[ActionItem]) -> MeetingExtraction:
    return MeetingExtraction(summary="s", participants=["Priya"],
                             decisions=[], action_items=items)


def test_missing_owner_produces_a_blocking_gap():
    gaps = detect_structural_gaps(_extraction([_item("a1", None, "2026-10-02")]))
    assert len(gaps) == 1
    assert gaps[0].type is GapType.MISSING_OWNER
    assert gaps[0].severity is Severity.BLOCKING
    assert gaps[0].target_id == "a1"


def test_missing_deadline_produces_a_blocking_gap():
    gaps = detect_structural_gaps(_extraction([_item("a1", "Priya", None)]))
    assert len(gaps) == 1
    assert gaps[0].type is GapType.MISSING_DEADLINE


def test_item_missing_both_produces_two_gaps():
    gaps = detect_structural_gaps(_extraction([_item("a1", None, None)]))
    assert len(gaps) == 2


def test_complete_item_produces_no_gaps():
    gaps = detect_structural_gaps(_extraction([_item("a1", "Priya", "2026-10-02")]))
    assert gaps == []


def test_blank_owner_string_counts_as_missing():
    """A model returning "" or "  " must not slip past the gate."""
    gaps = detect_structural_gaps(_extraction([_item("a1", "   ", "2026-10-02")]))
    assert gaps[0].type is GapType.MISSING_OWNER


def test_gap_ids_are_deterministic():
    """Re-running detection must not produce new ids, or resolutions would be lost."""
    first = detect_structural_gaps(_extraction([_item("a1", None, None)]))
    second = detect_structural_gaps(_extraction([_item("a1", None, None)]))
    assert [g.id for g in first] == [g.id for g in second]


def test_merge_gaps_deduplicates_by_target_and_type():
    """The model and the backstop will both flag the same missing owner."""
    model_gap = Gap(id="model-1", type=GapType.MISSING_OWNER, severity=Severity.BLOCKING,
                    target_id="a1", explanation="model saw it",
                    suggested_question="Who owns this?")
    structural = detect_structural_gaps(_extraction([_item("a1", None, "2026-10-02")]))
    merged = merge_gaps([model_gap], structural)
    assert len(merged) == 1
    assert merged[0].explanation == "model saw it"  # model's wording wins


def test_merge_keeps_model_only_gaps():
    model_gap = Gap(id="model-1", type=GapType.AMBIGUOUS_TASK, severity=Severity.WARNING,
                    target_id="a1", explanation="vague verb",
                    suggested_question="What does 'look into' mean here?")
    merged = merge_gaps([model_gap], [])
    assert len(merged) == 1


def test_merge_keeps_structural_gaps_the_model_missed():
    """R2: a rubber-stamping reviewer must not be able to unblock the gate."""
    structural = detect_structural_gaps(_extraction([_item("a1", None, None)]))
    merged = merge_gaps([], structural)
    assert len(merged) == 2


def test_placeholder_owner_string_produces_a_blocking_gap():
    """Regression: the model emitting the STRING "null" must not bypass the gate."""
    gaps = detect_structural_gaps(_extraction([_item("a1", "null", "2026-10-02")]))
    assert len(gaps) == 1
    assert gaps[0].type is GapType.MISSING_OWNER
    assert is_blocked(gaps, resolved_ids=set()) is True


def test_is_blocked_true_with_one_open_blocking_gap():
    gaps = detect_structural_gaps(_extraction([_item("a1", None, None)]))
    assert is_blocked(gaps, resolved_ids=set()) is True


def test_is_blocked_false_when_all_blocking_gaps_resolved():
    gaps = detect_structural_gaps(_extraction([_item("a1", None, None)]))
    assert is_blocked(gaps, resolved_ids={g.id for g in gaps}) is False


def test_warnings_alone_do_not_block():
    warning = Gap(id="w1", type=GapType.AMBIGUOUS_TASK, severity=Severity.WARNING,
                  target_id="a1", explanation="vague", suggested_question="?")
    assert is_blocked([warning], resolved_ids=set()) is False


def test_open_blocking_counts_only_unresolved_blocking_gaps():
    gaps = detect_structural_gaps(_extraction([_item("a1", None, None),
                                               _item("a2", None, "2026-10-02")]))
    assert len(open_blocking(gaps, resolved_ids=set())) == 3
    assert len(open_blocking(gaps, resolved_ids={gaps[0].id})) == 2


def test_blocking_type_with_warning_severity_still_blocks():
    """A model can emit a blocking type tagged WARNING; the taxonomy must win."""
    gap = Gap(id="m1", type=GapType.CONFLICTING_DECISION, severity=Severity.WARNING,
              target_id="d1", explanation="reversed later",
              suggested_question="Which decision stands?")
    assert is_blocked([gap], resolved_ids=set()) is True


def test_resolving_a_blocking_type_gap_clears_it():
    gap = Gap(id="m1", type=GapType.CONFLICTING_DECISION, severity=Severity.WARNING,
              target_id="d1", explanation="reversed later",
              suggested_question="Which decision stands?")
    assert is_blocked([gap], resolved_ids={"m1"}) is False


def test_evidence_gap_is_blocking_for_a_decision_and_warning_for_a_risk():
    extraction = MeetingExtraction(
        summary="s", participants=[],
        decisions=[Decision(id="d1", decision="Use Postgres", rationale=None,
                            source_quote="invented decision quote", confidence=0.8)],
        action_items=[],
        risks=[TechnicalRisk(
            id="r1", description="Risk", impact=None, likelihood=None,
            severity=None, mitigation=None, owner=None,
            source_quote="invented risk quote", confidence=0.7)],
    )
    gaps = detect_evidence_gaps(extraction, "The meeting notes contain no quotes.")
    by_target = {gap.target_id: gap for gap in gaps}
    assert by_target["d1"].type is GapType.UNSUPPORTED_EVIDENCE
    assert by_target["d1"].severity is Severity.BLOCKING
    assert by_target["r1"].severity is Severity.WARNING


def test_merge_with_deterministic_drops_a_model_downgrade_of_an_evidence_gap():
    model = Gap(id="model::d1", type=GapType.UNSUPPORTED_EVIDENCE,
                severity=Severity.WARNING, target_id="d1",
                explanation="e", suggested_question="q")
    evidence = Gap(id="evidence::decision::d1", type=GapType.UNSUPPORTED_EVIDENCE,
                   severity=Severity.BLOCKING, target_id="d1",
                   explanation="e", suggested_question="q")
    merged = merge_with_deterministic([model], [], [evidence])
    assert merged == [evidence]
    assert is_blocked(merged, resolved_ids=set())
