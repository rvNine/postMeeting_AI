import pytest

import config
from agent.loop import make_ids_unique, merge_extractions, run_agent_loop
from agent.llm_client import LLMError
from agent.schemas import (
    ActionItem, Decision, Gap, GapTriage, GapType, MeetingContext,
    MeetingExtraction, ReviewResult, Severity, TechnicalDependency,
    TechnicalLearning, TechnicalRisk, TriageResult, TriageVerdict,
)


def _item(id_, task, owner=None, deadline=None, source_quote=None):
    return ActionItem(id=id_, task=task, owner=owner, deadline=deadline,
                      source_quote=task if source_quote is None else source_quote,
                      confidence=0.8)


def _extraction(items, summary="s"):
    return MeetingExtraction(summary=summary, participants=["Priya"],
                             decisions=[], action_items=items)


def _review(gaps=()):
    return ReviewResult(gaps=list(gaps), overall_confidence=0.7, reviewer_notes="")


def _gap(gap_id="g1", target="a1"):
    return Gap(id=gap_id, type=GapType.MISSING_OWNER, severity=Severity.BLOCKING,
               target_id=target, explanation="e", suggested_question="q")


def _triage(gap_id, verdict, quote=None):
    return TriageResult(triages=[GapTriage(gap_id=gap_id, verdict=verdict,
                                           supporting_quote=quote, reasoning="r")])


# ---------- merge ----------

def test_merge_updates_a_matching_item():
    first = _extraction([_item("a1", "Audit the budget")])
    second = _extraction([_item("a1", "Audit the Q3 error budget", owner="Dan",
                                source_quote="Audit the budget")])
    merged, corrected = merge_extractions(first, second)
    assert len(merged.action_items) == 1
    assert merged.action_items[0].owner == "Dan"
    assert corrected == {"a1"}


def test_merge_adds_a_new_item():
    first = _extraction([_item("a1", "Audit the budget")])
    second = _extraction([_item("a2", "Book the room", owner="Sam")])
    merged, corrected = merge_extractions(first, second)
    assert {i.id for i in merged.action_items} == {"a1", "a2"}
    assert corrected == {"a2"}


def test_merge_never_drops_a_first_pass_item():
    """Invariant 4: pass 2 may add or correct, never silently remove."""
    first = _extraction([_item("a1", "Audit the budget"), _item("a2", "Book the room")])
    second = _extraction([_item("a1", "Audit the budget", owner="Dan")])
    merged, _ = merge_extractions(first, second)
    assert {i.id for i in merged.action_items} == {"a1", "a2"}


def test_merge_never_drops_a_first_pass_decision():
    """Pass 2 returning a shorter decision list must not delete the difference."""
    d1 = Decision(id="d1", decision="Use Postgres", rationale=None,
                  source_quote="q", confidence=0.9)
    d2 = Decision(id="d2", decision="Keep Redis", rationale=None,
                  source_quote="q", confidence=0.9)
    first = MeetingExtraction(summary="s", participants=["A"], decisions=[d1, d2],
                              action_items=[])
    second = MeetingExtraction(summary="s2", participants=["A"], decisions=[d2],
                               action_items=[])
    merged, _ = merge_extractions(first, second)
    assert {d.id for d in merged.decisions} == {"d1", "d2"}


def test_merge_keeps_the_second_summary_and_first_decisions_when_second_has_none():
    first = MeetingExtraction(summary="first", participants=["A"],
                              decisions=[Decision(id="d1", decision="Keep Redis",
                                                  rationale=None, source_quote="q",
                                                  confidence=0.9)],
                              action_items=[])
    second = MeetingExtraction(summary="second", participants=["A", "B"],
                               decisions=[], action_items=[])
    merged, _ = merge_extractions(first, second)
    assert merged.summary == "second"
    assert [d.id for d in merged.decisions] == ["d1"]


def _quoted(id_, task, quote, owner=None, confidence=0.8):
    return ActionItem(id=id_, task=task, owner=owner, deadline=None,
                      source_quote=quote, confidence=confidence)


def test_merge_does_not_trust_ids_that_the_model_renumbered():
    """Pass 2 numbers from a1 again, so its a1 is not pass 1's a1. Merging by id
    overwrote "Send report" and dropped "Fix alerting" outright."""
    first = _extraction([_quoted("a1", "Send report", "Sam sends the report"),
                         _quoted("a2", "Fix alerting", "alerting is broken")])
    second = _extraction([_quoted("a1", "Retry thing", "still on the retry thing"),
                          _quoted("a2", "Send report", "Sam sends the report")])
    merged, corrected = merge_extractions(first, second)
    tasks = {i.id: i.task for i in merged.action_items}
    assert tasks["a1"] == "Send report"
    assert tasks["a2"] == "Fix alerting"
    assert sorted(tasks.values()) == ["Fix alerting", "Retry thing", "Send report"]
    new_id = next(k for k, v in tasks.items() if v == "Retry thing")
    assert corrected == {new_id}


def test_merge_keeps_the_first_pass_id_on_a_matched_correction():
    first = _extraction([_quoted("a1", "Send report", "Sam sends the report")])
    second = _extraction([_quoted("a3", "Send report", "Sam sends the report",
                                  owner="Sam")])
    merged, corrected = merge_extractions(first, second)
    assert [(i.id, i.owner) for i in merged.action_items] == [("a1", "Sam")]
    assert corrected == {"a1"}


def test_merge_does_not_mark_a_confidence_only_change_as_revised():
    first = _extraction([_quoted("a1", "Send report", "q", confidence=0.8)])
    second = _extraction([_quoted("a1", "Send report", "q", confidence=0.83)])
    merged, corrected = merge_extractions(first, second)
    assert corrected == set()
    assert merged.action_items[0].confidence == 0.8


def test_merge_does_not_trust_renumbered_decision_ids():
    def _d(id_, text, quote):
        return Decision(id=id_, decision=text, rationale=None,
                        source_quote=quote, confidence=0.9)
    first = MeetingExtraction(summary="s", participants=["A"], action_items=[],
                              decisions=[_d("d1", "Use Postgres", "go Postgres"),
                                         _d("d2", "Keep Redis", "keep Redis")])
    second = MeetingExtraction(summary="s", participants=["A"], action_items=[],
                               decisions=[_d("d1", "Drop Kafka", "no more Kafka")])
    merged, _ = merge_extractions(first, second)
    by_text = {d.decision: d.id for d in merged.decisions}
    assert by_text["Use Postgres"] == "d1" and by_text["Keep Redis"] == "d2"
    assert by_text["Drop Kafka"] not in {"d1", "d2"}


def test_merge_never_gives_a_new_item_an_id_already_used_by_a_decision():
    first = MeetingExtraction(
        summary="s", participants=["A"],
        decisions=[Decision(id="a2", decision="Use Postgres", rationale=None,
                            source_quote="go Postgres", confidence=0.9)],
        action_items=[_quoted("a1", "Send report", "Sam sends the report")])
    second = _extraction([_quoted("a2", "Book the room", "book a room")])
    merged, _ = merge_extractions(first, second)
    ids = [i.id for i in merged.action_items] + [d.id for d in merged.decisions]
    assert len(ids) == len(set(ids))


def test_merge_adds_and_updates_technical_records():
    first = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[],
        risks=[TechnicalRisk(
            id="r1", description="Cache saturation", impact=None, likelihood=None,
            severity=None, mitigation=None, owner=None,
            source_quote="cache saturation", confidence=0.7)],
        dependencies=[], learnings=[])
    second = MeetingExtraction(
        summary="s2", participants=[], decisions=[], action_items=[],
        risks=[TechnicalRisk(
            id="r4", description="Cache saturation", impact="latency", likelihood=None,
            severity="high", mitigation="Add capacity", owner=None,
            source_quote="cache saturation increases latency", confidence=0.9)],
        dependencies=[TechnicalDependency(
            id="dep1", description="Wait for API contract", depends_on="API team",
            blocked_by=None, owner=None, source_quote="wait for API contract",
            confidence=0.8)],
        learnings=[])
    merged, corrected = merge_extractions(first, second)
    assert merged.risks[0].id == "r1"
    assert merged.risks[0].severity == "high"
    assert [d.description for d in merged.dependencies] == ["Wait for API contract"]
    assert corrected == set()


def test_merge_never_drops_first_pass_technical_records():
    first = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[],
        risks=[], dependencies=[], learnings=[TechnicalLearning(
            id="l1", lesson="Use smaller batches", technical_area=None,
            validation_status=None, follow_up_experiment=None,
            source_quote="smaller batches", confidence=0.8)])
    second = MeetingExtraction(
        summary="s2", participants=[], decisions=[], action_items=[],
        risks=[], dependencies=[], learnings=[])
    merged, _ = merge_extractions(first, second)
    assert [learning.lesson for learning in merged.learnings] == ["Use smaller batches"]


def test_merge_avoids_ids_used_by_other_record_kinds():
    first = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[],
        risks=[TechnicalRisk(
            id="r1", description="Risk one", impact=None, likelihood=None,
            severity=None, mitigation=None, owner=None, source_quote="risk one",
            confidence=0.8)],
        dependencies=[], learnings=[])
    second = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[], risks=[],
        dependencies=[TechnicalDependency(
            id="r1", description="Dependency one", depends_on=None, blocked_by=None,
            owner=None, source_quote="dependency one", confidence=0.8)],
        learnings=[])
    merged, _ = merge_extractions(first, second)
    ids = [r.id for r in merged.risks] + [d.id for d in merged.dependencies]
    assert len(ids) == len(set(ids))


# ---------- loop control ----------

def test_loop_exits_after_one_pass_when_nothing_is_self_resolvable(stub_client):
    extraction = _extraction([_item("a1", "Audit the budget")])
    client = stub_client([extraction, _review([_gap()]),
                          _triage("g1", TriageVerdict.NEEDS_HUMAN)])
    outcome = run_agent_loop("Someone should audit the budget.", client)
    assert outcome.passes == 1
    assert [c["kind"] for c in client.calls] == ["parse", "parse", "parse"]


def test_loop_runs_a_second_pass_when_a_gap_is_self_resolvable(stub_client):
    notes = "Dan will audit the error budget by 2026-10-02."
    first = _extraction([_item("a1", "Audit the error budget")])
    second = _extraction([_item("a1", "Audit the error budget", owner="Dan",
                                deadline="2026-10-02")])
    client = stub_client([
        first, _review([_gap()]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE,
                "Dan will audit the error budget"),
        second, _review([]),
    ])
    outcome = run_agent_loop(notes, client)
    assert outcome.passes == 2
    assert outcome.extraction.action_items[0].owner == "Dan"
    assert outcome.corrected_item_ids == {"a1"}


def test_loop_never_exceeds_max_passes(stub_client):
    """Even if pass 2 also finds a self-resolvable gap, the budget is hard."""
    notes = "Dan will audit the error budget."
    first = _extraction([_item("a1", "Audit the error budget")])
    second = _extraction([_item("a1", "Audit the error budget", owner="Dan")])
    client = stub_client([
        first, _review([_gap()]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "Dan will audit the error budget"),
        second, _review([_gap()]),
    ])
    outcome = run_agent_loop(notes, client)
    assert outcome.passes == config.MAX_PASSES == 2
    assert len(client.calls) == 5


def test_loop_with_no_gaps_makes_no_triage_call(stub_client):
    extraction = _extraction([_item("a1", "Audit", owner="Dan", deadline="2026-10-02")])
    client = stub_client([extraction, _review([])])
    outcome = run_agent_loop("Dan will audit by 2026-10-02.", client)
    assert outcome.passes == 1
    assert len(client.calls) == 2


def test_loop_keeps_pass_one_when_re_extraction_fails(stub_client):
    """Invariant: pass 1 is never lost to a pass-2 failure."""
    notes = "Dan will audit the error budget."
    first = _extraction([_item("a1", "Audit the error budget")])
    client = stub_client([
        first, _review([_gap()]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "Dan will audit the error budget"),
        LLMError("boom"),
    ])
    outcome = run_agent_loop(notes, client)
    assert outcome.extraction.action_items[0].task == "Audit the error budget"
    assert any("second pass" in n.lower() for n in outcome.notes_for_manager)


def test_loop_respects_an_explicit_max_passes_of_one(stub_client):
    notes = "Dan will audit the error budget."
    first = _extraction([_item("a1", "Audit the error budget")])
    client = stub_client([first, _review([_gap()])])
    outcome = run_agent_loop(notes, client, max_passes=1)
    assert outcome.passes == 1
    assert len(client.calls) == 2      # no triage: a second pass is impossible


def test_the_gate_still_refuses_after_a_two_pass_loop(stub_client):
    """Invariant 1, end to end. The loop must not open a path to a draft.

    Pass 2 fills the owner but not the deadline, so a blocking gap survives and
    run_draft must still refuse — and must not call the model to find that out.
    """
    from agent.gaps import GateBlockedError
    from agent.pipeline import run_draft

    notes = "Dan will audit the error budget."
    first = _extraction([_item("a1", "Audit the error budget")])
    second = _extraction([_item("a1", "Audit the error budget", owner="Dan")])
    client = stub_client([
        first, _review([_gap()]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "Dan will audit the error budget"),
        second, _review([]),
    ])
    outcome = run_agent_loop(notes, client)
    assert outcome.passes == 2

    draft_client = stub_client(["a drafted message"])
    with pytest.raises(GateBlockedError):
        run_draft(meeting_title="T", decisions=outcome.extraction.decisions,
                  action_items=outcome.extraction.action_items,
                  gaps=outcome.review.gaps, resolved_ids=set(), client=draft_client)
    assert draft_client.calls == []


def test_the_backstop_reflags_an_item_the_merge_added(stub_client):
    """merge_extractions can add items the review never saw. The final backstop
    must catch a new item that arrives without an owner or deadline."""
    notes = "We should also rewrite the on-call rota."
    first = _extraction([_item("a1", "Audit the budget", owner="Dan",
                               deadline="2026-10-02")])
    second = _extraction([_item("a2", "Rewrite the on-call rota")])
    client = stub_client([
        first, _review([_gap("g1", target="a1")]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "We should also rewrite the on-call rota"),
        second, _review([]),
    ])
    outcome = run_agent_loop(notes, client)
    flagged = {g.target_id for g in outcome.review.gaps}
    assert "a2" in flagged, "the merged-in item was never re-checked by the backstop"


def test_owner_hints_never_reach_any_call(stub_client):
    """Invariant 3, end to end across the whole loop.

    Queues a self-resolvable triage so the loop runs all five calls (including
    the pass-2 run_extract and the triage call, which also re-pass context) —
    not just the two calls a no-gap first pass would make.
    """
    from agent.schemas import OwnerHint
    ctx = MeetingContext(owner_hints=(
        OwnerHint(owner="Dan", times_assigned=9, example_task="Add error alerting"),))
    first = _extraction([_item("a1", "Audit", owner="Sam")])
    second = _extraction([_item("a1", "Audit", owner="Sam", deadline="2026-10-02")])
    client = stub_client([
        first, _review([_gap("g1", target="a1")]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "Sam will audit by 2026-10-02"),
        second, _review([]),
    ])
    run_agent_loop("Sam will audit by 2026-10-02.", client, context=ctx)
    assert len(client.calls) == 5
    for call in client.calls:
        assert "Dan" not in call["system"] and "Dan" not in call["user"]
        assert "Add error alerting" not in call["user"]


def test_the_loops_own_backstop_flags_a_merged_in_item(stub_client, monkeypatch):
    """The loop's post-merge backstop, isolated from run_review's internal merge.

    run_review merges detect_structural_gaps itself, which masks whether the loop's
    own backstop does anything. Here the reviewer deliberately does not merge, so a
    gap on the pass-2 item can only come from the loop.
    """
    from agent import loop as loop_module
    from agent.pipeline import ReviewOutcome

    calls = {"n": 0}

    def fake_run_review(notes, extraction, client):
        calls["n"] += 1
        client.parse("s", "u", ReviewResult, temperature=0.0)   # keep the call count honest
        gaps = [_gap("g1", target="a1")] if calls["n"] == 1 else []
        return ReviewOutcome(
            review=ReviewResult(gaps=gaps, overall_confidence=0.5, reviewer_notes=""),
            raw="", tokens=1, latency_ms=1)

    monkeypatch.setattr(loop_module, "run_review", fake_run_review)

    notes = "We should also rewrite the on-call rota."
    first = _extraction([_item("a1", "Audit the budget", owner="Dan", deadline="2026-10-02")])
    second = _extraction([_item("a2", "Rewrite the on-call rota")])
    client = stub_client([
        first, _review([_gap("g1", target="a1")]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "We should also rewrite the on-call rota"),
        second, _review([]),
    ])
    outcome = run_agent_loop(notes, client)
    assert "a2" in {g.target_id for g in outcome.review.gaps}, (
        "the loop's own backstop did not flag the item the merge introduced")


def test_the_loops_own_backstop_flags_unsupported_merged_technical_record(
        stub_client, monkeypatch):
    """The loop must evidence-check technical records introduced by pass 2,
    even when the model re-review reports no gaps."""
    from agent import loop as loop_module
    from agent.pipeline import ReviewOutcome

    calls = {"n": 0}

    def fake_run_review(notes, extraction, client):
        calls["n"] += 1
        client.parse("s", "u", ReviewResult, temperature=0.0)
        gaps = [_gap("g1", target="a1")] if calls["n"] == 1 else []
        return ReviewOutcome(
            review=ReviewResult(gaps=gaps, overall_confidence=0.5, reviewer_notes=""),
            raw="", tokens=1, latency_ms=1)

    monkeypatch.setattr(loop_module, "run_review", fake_run_review)

    notes = "We should revisit capacity."
    first = _extraction([_item("a1", "Revisit capacity", owner="Dan",
                               deadline="2026-10-02")])
    second = MeetingExtraction(
        summary="s2", participants=["Priya"], decisions=[],
        action_items=[_item("a1", "Revisit capacity", owner="Dan",
                            deadline="2026-10-02")],
        risks=[TechnicalRisk(
            id="r1", description="Cache saturation", impact=None, likelihood=None,
            severity=None, mitigation=None, owner=None,
            source_quote="cache saturation", confidence=0.8)],
    )
    client = stub_client([
        first, _review([_gap("g1", target="a1")]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "revisit capacity"),
        second, _review([]),
    ])
    outcome = run_agent_loop(notes, client)
    assert any(
        gap.target_id == "r1" and gap.type is GapType.UNSUPPORTED_EVIDENCE
        for gap in outcome.review.gaps
    )


def test_loop_exposes_its_own_first_pass(stub_client):
    """The eval measures pass-2 gain against this, not a separate run."""
    notes = "Dan will audit the error budget by 2026-10-02."
    first = _extraction([_item("a1", "Audit the error budget")])
    second = _extraction([_item("a1", "Audit the error budget", owner="Dan",
                                deadline="2026-10-02")])
    client = stub_client([
        first, _review([_gap()]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "Dan will audit the error budget"),
        second, _review([]),
    ])
    outcome = run_agent_loop(notes, client)
    assert outcome.first_extraction == first


def test_loop_carries_a_supported_technical_risk_through_to_final_review(stub_client):
    """End-to-end regression: a technical risk introduced on the corrective
    (second) pass survives the merge into the final extraction, and produces
    no evidence gap in the final review because its quote genuinely appears in
    the notes. Queue order: extract, review, triage, extract, review."""
    notes = ("Dan will audit the error budget by 2026-10-02. Cache saturation "
             "is the main risk during the launch window.")
    first = _extraction([_item("a1", "Audit the error budget")])
    risk = TechnicalRisk(
        id="r1", description="Cache saturation during launch", impact=None,
        likelihood=None, severity=None, mitigation=None, owner=None,
        source_quote="Cache saturation is the main risk during the launch window",
        confidence=0.8)
    second = MeetingExtraction(
        summary="s2", participants=["Priya"], decisions=[],
        action_items=[_item("a1", "Audit the error budget", owner="Dan",
                            deadline="2026-10-02")],
        risks=[risk])
    client = stub_client([
        first, _review([_gap()]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "Dan will audit the error budget"),
        second, _review([]),
    ])
    outcome = run_agent_loop(notes, client)
    assert outcome.passes == 2
    assert [c["kind"] for c in client.calls] == ["parse"] * 5
    assert any(r.id == "r1" for r in outcome.extraction.risks)
    assert not any(g.type is GapType.UNSUPPORTED_EVIDENCE for g in outcome.review.gaps)


def test_a_failed_re_review_keeps_the_first_reviews_conflict_gap(stub_client):
    """The re-review's fallback has structural gaps only. Taking it as-is dropped
    a CONFLICT the first review found — and with it, the block on the draft."""
    from agent.gaps import is_blocked

    notes = "Dan will audit the error budget by 2026-10-02. Use Postgres. Use MySQL."
    conflict = Gap(id="model::d1::conflicting_decision",
                   type=GapType.CONFLICTING_DECISION, severity=Severity.BLOCKING,
                   target_id="d1", explanation="e", suggested_question="q")
    first = _extraction([_item("a1", "Audit the error budget")])
    second = _extraction([_item("a1", "Audit the error budget", owner="Dan",
                                deadline="2026-10-02")])
    client = stub_client([
        first, _review([_gap(), conflict]),
        _triage("g1", TriageVerdict.SELF_RESOLVABLE, "Dan will audit the error budget"),
        second, LLMError("boom"),
    ])
    outcome = run_agent_loop(notes, client)
    types = {(g.target_id, g.type) for g in outcome.review.gaps}
    assert ("d1", GapType.CONFLICTING_DECISION) in types
    assert ("a1", GapType.MISSING_OWNER) not in types, "a stale owner gap came back"
    assert is_blocked(outcome.review.gaps, resolved_ids=set())
    assert any("re-check" in n for n in outcome.notes_for_manager)


# ---------- deterministic evidence stays authoritative (final review F1) ----------

def _decision(id_, text, quote):
    return Decision(id=id_, decision=text, rationale=None, source_quote=quote,
                    confidence=0.9)


def _evidence_warning(target):
    return Gap(id=f"model::{target}::unsupported_evidence",
               type=GapType.UNSUPPORTED_EVIDENCE, severity=Severity.WARNING,
               target_id=target, explanation="e", suggested_question="q")


def test_a_failed_re_review_cannot_keep_a_model_downgrade_of_an_evidence_gap(stub_client):
    """Pass 2 rewrites d1's quote to text absent from the notes, then the
    re-review fails. The model's pass-1 WARNING on (d1, UNSUPPORTED_EVIDENCE)
    must not win the (target_id, type) tie against the deterministic BLOCKING
    evidence gap — otherwise the gate opens on an unquoted decision."""
    from agent.gaps import is_blocked

    notes = "Dan will audit the error budget by 2026-10-02. We chose Postgres."
    item = _item("a1", "Audit the error budget", owner="Dan", deadline="2026-10-02",
                 source_quote="Dan will audit the error budget by 2026-10-02")
    first = MeetingExtraction(summary="s", participants=["Dan"],
                              decisions=[_decision("d1", "Use Postgres", "We chose Postgres")],
                              action_items=[item])
    second = MeetingExtraction(summary="s", participants=["Dan"],
                               decisions=[_decision("d1", "Use Postgres",
                                                    "Postgres won the vote unanimously")],
                               action_items=[item])
    client = stub_client([
        first, _review([_evidence_warning("d1")]),
        _triage("model::d1::unsupported_evidence", TriageVerdict.SELF_RESOLVABLE,
                "We chose Postgres"),
        second, LLMError("boom"),
    ])
    outcome = run_agent_loop(notes, client)
    assert outcome.passes == 2
    d1_evidence = [g for g in outcome.review.gaps
                   if g.target_id == "d1" and g.type is GapType.UNSUPPORTED_EVIDENCE]
    assert len(d1_evidence) == 1
    assert d1_evidence[0].severity is Severity.BLOCKING
    assert is_blocked(outcome.review.gaps, resolved_ids=set())


def test_a_failed_re_review_does_not_carry_a_stale_evidence_gap(stub_client):
    """Pass 1's d1 quote is unsupported; pass 2 fixes it; the re-review fails.
    The evidence gap is recomputed from the merged extraction, so no stale gap
    on d1 survives from pass 1."""
    notes = "Dan will audit the error budget by 2026-10-02. We chose Postgres."
    item = _item("a1", "Audit the error budget", owner="Dan", deadline="2026-10-02",
                 source_quote="Dan will audit the error budget by 2026-10-02")
    first = MeetingExtraction(summary="s", participants=["Dan"],
                              decisions=[_decision("d1", "Use Postgres",
                                                   "Postgres won the vote")],
                              action_items=[item])
    second = MeetingExtraction(summary="s", participants=["Dan"],
                               decisions=[_decision("d1", "Use Postgres",
                                                    "We chose Postgres")],
                               action_items=[item])
    client = stub_client([
        first, _review([]),   # run_review adds the deterministic evidence gap on d1
        _triage("evidence::decision::d1", TriageVerdict.SELF_RESOLVABLE,
                "We chose Postgres"),
        second, LLMError("boom"),
    ])
    outcome = run_agent_loop(notes, client)
    assert outcome.passes == 2
    assert outcome.extraction.decisions[0].source_quote == "We chose Postgres"
    assert not any(g.target_id == "d1" and g.type is GapType.UNSUPPORTED_EVIDENCE
                   for g in outcome.review.gaps), "a stale evidence gap survived"


# ---------- ids unique across record kinds (final review F2) ----------

def _dependency(id_, description, quote):
    return TechnicalDependency(id=id_, description=description, depends_on=None,
                               blocked_by=None, owner=None, source_quote=quote,
                               confidence=0.8)


def _all_ids(extraction):
    return [r.id for records in (extraction.action_items, extraction.decisions,
                                 extraction.risks, extraction.dependencies,
                                 extraction.learnings) for r in records]


def test_make_ids_unique_renames_later_duplicates_with_their_kinds_prefix():
    extraction = MeetingExtraction(
        summary="s", participants=[],
        decisions=[_decision("d1", "Use Postgres", "q")],
        action_items=[_item("d1", "Send report"), _item("a1", "Book room")],
        risks=[TechnicalRisk(id="a1", description="Cache", impact=None,
                             likelihood=None, severity=None, mitigation=None,
                             owner=None, source_quote="q", confidence=0.8)],
        dependencies=[_dependency("d1", "Wait for API", "q")],
        learnings=[])
    fixed = make_ids_unique(extraction)
    ids = _all_ids(fixed)
    assert len(ids) == len(set(ids))
    # First occurrence (action items are walked first) keeps its id.
    assert [a.id for a in fixed.action_items] == ["d1", "a1"]
    assert fixed.decisions[0].id.startswith("d") and fixed.decisions[0].id != "d1"
    assert fixed.risks[0].id.startswith("r")
    assert fixed.dependencies[0].id.startswith("dep")
    # Content is untouched.
    assert fixed.decisions[0].decision == "Use Postgres"


def test_make_ids_unique_is_a_no_op_when_ids_are_already_unique():
    extraction = MeetingExtraction(
        summary="s", participants=[],
        decisions=[_decision("d1", "Use Postgres", "q")],
        action_items=[_item("a1", "Send report")],
        dependencies=[_dependency("dep1", "Wait for API", "q")])
    assert make_ids_unique(extraction) == extraction


def test_a_decision_and_a_dependency_sharing_an_id_each_get_an_evidence_gap(stub_client):
    """Both records are `d1` with unsupported quotes. Evidence gaps dedupe on
    (target_id, type), so a shared id silently swallowed one of the two gaps."""
    notes = "Nothing here supports either record."
    first = MeetingExtraction(
        summary="s", participants=[],
        decisions=[_decision("d1", "Use Postgres", "Postgres was chosen")],
        action_items=[],
        dependencies=[_dependency("d1", "Wait for the API team", "API team blocks us")])
    client = stub_client([
        first, _review([]),
        _triage("evidence::decision::d1", TriageVerdict.NEEDS_HUMAN),
    ])
    outcome = run_agent_loop(notes, client)
    ids = _all_ids(outcome.extraction)
    assert len(ids) == len(set(ids))
    evidence_targets = {g.target_id for g in outcome.review.gaps
                        if g.type is GapType.UNSUPPORTED_EVIDENCE}
    assert evidence_targets == {outcome.extraction.decisions[0].id,
                                outcome.extraction.dependencies[0].id}
    assert len(evidence_targets) == 2
