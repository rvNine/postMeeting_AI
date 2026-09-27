import pytest

from agent import prompts
from agent.gaps import GateBlockedError, detect_structural_gaps, is_blocked
from agent.llm_client import LLMError
from agent.pipeline import (build_extract_user, owner_gap_is_hopeless, quote_supports,
                            run_draft, run_extract, run_review, run_triage)
from agent.schemas import (ActionItem, Decision, Gap, GapTriage, GapType, MeetingContext,
                           MeetingExtraction, OwnerHint, PriorCommitment, ReviewResult,
                           Severity, TechnicalDependency, TechnicalLearning,
                           TechnicalRisk, TriageResult, TriageVerdict)


@pytest.fixture
def clean_extraction():
    return MeetingExtraction(
        summary="We reviewed sprint 24.",
        participants=["Priya", "Sam"],
        decisions=[Decision(id="d1", decision="Move retry logic to the API layer",
                            rationale="the worker swallowed errors",
                            source_quote="move the payment retry logic", confidence=0.9)],
        action_items=[ActionItem(id="a1", task="Write the retry migration plan",
                                 owner="Sam", deadline="2026-09-12",
                                 source_quote="Sam will write the retry migration plan",
                                 confidence=0.95)],
    )


def test_run_extract_returns_the_parsed_extraction(stub_client, clean_extraction):
    client = stub_client([clean_extraction])
    outcome = run_extract("some notes", client)
    assert outcome.extraction.action_items[0].owner == "Sam"


def test_run_extract_sends_the_extraction_prompt(stub_client, clean_extraction):
    client = stub_client([clean_extraction])
    run_extract("some notes", client)
    assert client.calls[0]["system"] == prompts.EXTRACT_SYSTEM
    assert "some notes" in client.calls[0]["user"]


def test_run_extract_uses_low_temperature(stub_client, clean_extraction):
    """Extraction is a transcription task. Creativity is a defect here."""
    client = stub_client([clean_extraction])
    run_extract("notes", client)
    assert client.calls[0]["temperature"] <= 0.2


def test_run_extract_records_tokens_and_latency(stub_client, clean_extraction):
    client = stub_client([clean_extraction])
    outcome = run_extract("notes", client)
    assert outcome.tokens == 100
    assert outcome.latency_ms == 10


def test_extract_prompt_states_the_null_rule_twice():
    """R1 mitigation: the rule's repetition is load-bearing, not accidental."""
    assert prompts.EXTRACT_SYSTEM.lower().count("never invent") >= 2


def test_extract_prompt_requests_technical_records():
    assert "risk" in prompts.EXTRACT_SYSTEM.lower()
    assert "dependency" in prompts.EXTRACT_SYSTEM.lower()
    assert "learning" in prompts.EXTRACT_SYSTEM.lower()
    assert "source_quote" in prompts.EXTRACT_SYSTEM


def test_extract_prompt_defines_five_record_categories_without_legacy_contradiction():
    """Discussion is context, not a sixth record type or an everything-else bucket
    that contradicts the risk/dependency/learning rules later in the prompt."""
    prompt = prompts.EXTRACT_SYSTEM.lower()
    assert "exactly five extracted record categories" in prompt
    for category in ("decision", "action item", "risk", "dependency", "learning"):
        assert f"- {category}:" in prompt
    assert "discussion/background" in prompt
    assert "non-record context" in prompt
    assert "exactly three buckets" not in prompt
    assert "discussion: everything else" not in prompt


def test_review_prompt_forbids_filling_gaps():
    assert "never fill" in prompts.REVIEW_SYSTEM.lower()


def test_review_prompt_allows_all_record_types_as_gap_targets():
    target_rule = prompts.REVIEW_SYSTEM.split("2. `target_id`", 1)[1].split("3.", 1)[0]
    for record_type in ("decision", "action item", "risk", "dependency", "learning"):
        assert record_type in target_rule.lower()


def test_draft_prompt_forbids_adding_items():
    assert "do not add" in prompts.DRAFT_SYSTEM.lower()


@pytest.fixture
def gappy_extraction():
    """One item with no owner and no deadline."""
    return MeetingExtraction(
        summary="Planning.", participants=["Priya"], decisions=[],
        action_items=[ActionItem(id="a1", task="Audit the error budget",
                                 owner=None, deadline=None,
                                 source_quote="someone needs to audit", confidence=0.7)],
    )


def test_review_merges_model_gaps_with_structural_gaps(stub_client, gappy_extraction):
    model_review = ReviewResult(
        gaps=[Gap(id="model::a1::ambiguous_task", type=GapType.AMBIGUOUS_TASK,
                  severity=Severity.WARNING, target_id="a1",
                  explanation="vague scope", suggested_question="How far back?")],
        overall_confidence=0.7, reviewer_notes="ok")
    outcome = run_review("someone needs to audit", gappy_extraction,
                         stub_client([model_review]))
    types = {g.type for g in outcome.review.gaps}
    assert types == {GapType.AMBIGUOUS_TASK, GapType.MISSING_OWNER, GapType.MISSING_DEADLINE}


def test_review_digest_contains_technical_records(stub_client):
    extraction = MeetingExtraction(
        summary="s", participants=[], decisions=[], action_items=[],
        risks=[TechnicalRisk(
            id="r1", description="Cache saturation", impact=None,
            likelihood=None, severity="high", mitigation=None, owner=None,
            source_quote="cache saturation is possible", confidence=0.8)],
        dependencies=[TechnicalDependency(
            id="dep1", description="Wait for API contract", depends_on="API team",
            blocked_by=None, owner=None, source_quote="wait for the API contract",
            confidence=0.8)],
        learnings=[TechnicalLearning(
            id="l1", lesson="Smaller batches reduce retries", technical_area="migration",
            validation_status="observed", follow_up_experiment=None,
            source_quote="smaller batches reduced retries", confidence=0.8)],
    )
    review = ReviewResult(gaps=[], overall_confidence=0.9, reviewer_notes="clean")
    client = stub_client([review])
    run_review(
        "cache saturation is possible; wait for the API contract; smaller batches reduced retries",
        extraction,
        client,
    )
    digest = client.calls[0]["user"]
    assert "Cache saturation" in digest
    assert "Wait for API contract" in digest
    assert "Smaller batches reduce retries" in digest


def test_review_merges_evidence_gaps_even_when_model_returns_none(stub_client):
    extraction = MeetingExtraction(
        summary="s", participants=[], decisions=[Decision(
            id="d1", decision="Use Postgres", rationale=None,
            source_quote="not in the notes", confidence=0.8)], action_items=[])
    review = ReviewResult(gaps=[], overall_confidence=1.0, reviewer_notes="clean")
    outcome = run_review("The notes discuss Redis.", extraction, stub_client([review]))
    assert any(g.type is GapType.UNSUPPORTED_EVIDENCE for g in outcome.review.gaps)
    assert outcome.review.gaps[0].severity is Severity.BLOCKING


def test_review_model_cannot_downgrade_a_deterministic_evidence_gap(stub_client):
    extraction = MeetingExtraction(
        summary="s", participants=[], decisions=[Decision(
            id="d1", decision="Use Postgres", rationale=None,
            source_quote="not in the notes", confidence=0.8)], action_items=[])
    review = ReviewResult(
        gaps=[Gap(
            id="model::d1::unsupported_evidence",
            type=GapType.UNSUPPORTED_EVIDENCE,
            severity=Severity.WARNING,
            target_id="d1",
            explanation="weak model finding",
            suggested_question="Check it?",
        )],
        overall_confidence=0.5,
        reviewer_notes="",
    )
    outcome = run_review("The notes discuss Redis.", extraction, stub_client([review]))
    evidence_gap = next(
        g for g in outcome.review.gaps if g.type is GapType.UNSUPPORTED_EVIDENCE)
    assert evidence_gap.severity is Severity.BLOCKING
    assert evidence_gap.id == "evidence::decision::d1"


def test_review_normalizes_model_only_evidence_severity_by_target_kind(stub_client):
    """A verbatim quote can still be semantically irrelevant. In that case the
    reviewer gap has no deterministic collision, so record kind must remain the
    authority for severity rather than the model's supplied enum value."""
    notes = (
        "We discussed Postgres. Sam will benchmark Redis by 2026-10-02. "
        "Cache saturation came up. Launch depends on the API contract. "
        "Small batches reduced retries."
    )
    extraction = MeetingExtraction(
        summary="s",
        participants=["Sam"],
        decisions=[Decision(
            id="d1", decision="Adopt Redis", rationale=None,
            source_quote="We discussed Postgres", confidence=0.8)],
        action_items=[ActionItem(
            id="a1", task="Benchmark Postgres", owner="Sam", deadline="2026-10-02",
            source_quote="Sam will benchmark Redis by 2026-10-02", confidence=0.8)],
        risks=[TechnicalRisk(
            id="r1", description="Database corruption", impact=None, likelihood=None,
            severity=None, mitigation=None, owner=None,
            source_quote="Cache saturation came up", confidence=0.8)],
        dependencies=[TechnicalDependency(
            id="dep1", description="Wait for security review", depends_on=None,
            blocked_by=None, owner=None,
            source_quote="Launch depends on the API contract", confidence=0.8)],
        learnings=[TechnicalLearning(
            id="l1", lesson="Large batches are safer", technical_area=None,
            validation_status=None, follow_up_experiment=None,
            source_quote="Small batches reduced retries", confidence=0.8)],
    )
    wrong_severities = {
        "d1": Severity.WARNING,
        "a1": Severity.WARNING,
        "r1": Severity.BLOCKING,
        "dep1": Severity.BLOCKING,
        "l1": Severity.BLOCKING,
    }
    review = ReviewResult(
        gaps=[Gap(
            id=f"model::{target}::unsupported_evidence",
            type=GapType.UNSUPPORTED_EVIDENCE,
            severity=severity,
            target_id=target,
            explanation="The quote is verbatim but does not support the extracted claim.",
            suggested_question="What supports this claim?",
        ) for target, severity in wrong_severities.items()],
        overall_confidence=0.5,
        reviewer_notes="Evidence is semantically irrelevant.",
    )

    outcome = run_review(notes, extraction, stub_client([review]))

    by_target = {gap.target_id: gap.severity for gap in outcome.review.gaps}
    assert by_target == {
        "d1": Severity.BLOCKING,
        "a1": Severity.BLOCKING,
        "r1": Severity.WARNING,
        "dep1": Severity.WARNING,
        "l1": Severity.WARNING,
    }


def test_review_failure_keeps_evidence_gaps(stub_client):
    extraction = MeetingExtraction(
        summary="s", participants=[], decisions=[Decision(
            id="d1", decision="Use Postgres", rationale=None,
            source_quote="missing quote", confidence=0.8)], action_items=[])
    outcome = run_review("Redis was discussed.", extraction, stub_client([LLMError("boom")]))
    assert outcome.failed is True
    assert any(g.type is GapType.UNSUPPORTED_EVIDENCE for g in outcome.review.gaps)


def test_rubber_stamping_reviewer_cannot_unblock_the_gate(stub_client, gappy_extraction):
    """R2: the model returns zero gaps; the backstop must still block."""
    empty_review = ReviewResult(gaps=[], overall_confidence=1.0, reviewer_notes="all good")
    outcome = run_review("someone needs to audit", gappy_extraction,
                         stub_client([empty_review]))
    assert is_blocked(outcome.review.gaps, resolved_ids=set()) is True
    assert len(outcome.review.gaps) == 2


def test_review_falls_back_to_structural_gaps_when_the_model_fails(
        stub_client, gappy_extraction):
    """PRD §5.3: a step-2 failure degrades to deterministic detection, not to no gate."""
    outcome = run_review("someone needs to audit", gappy_extraction,
                         stub_client([LLMError("boom")]))
    assert len(outcome.review.gaps) == 2
    assert "fallback" in outcome.review.reviewer_notes.lower()


def test_review_sees_both_the_notes_and_the_extraction(stub_client, gappy_extraction):
    review = ReviewResult(gaps=[], overall_confidence=0.9, reviewer_notes="")
    client = stub_client([review])
    run_review("THE ORIGINAL NOTES", gappy_extraction, client)
    user = client.calls[0]["user"]
    assert "THE ORIGINAL NOTES" in user
    assert "Audit the error budget" in user


def test_review_uses_zero_temperature(stub_client, gappy_extraction):
    review = ReviewResult(gaps=[], overall_confidence=0.9, reviewer_notes="")
    client = stub_client([review])
    run_review("notes", gappy_extraction, client)
    assert client.calls[0]["temperature"] == 0.0


def test_clean_extraction_produces_no_blocking_gaps(stub_client, clean_extraction):
    review = ReviewResult(gaps=[], overall_confidence=0.95, reviewer_notes="clean")
    notes = ("move the payment retry logic. "
             "Sam will write the retry migration plan.")
    outcome = run_review(notes, clean_extraction, stub_client([review]))
    assert is_blocked(outcome.review.gaps, resolved_ids=set()) is False


def _draft_args(extraction, gaps, resolved_ids, client):
    return dict(meeting_title="Sprint 24 Review", decisions=extraction.decisions,
                action_items=extraction.action_items, gaps=gaps,
                resolved_ids=resolved_ids, client=client)


def test_draft_raises_when_a_blocking_gap_is_open(stub_client, gappy_extraction):
    """R5: the gate is enforced here, not only in the UI."""
    gaps = detect_structural_gaps(gappy_extraction)
    with pytest.raises(GateBlockedError):
        run_draft(**_draft_args(gappy_extraction, gaps, set(), stub_client(["draft"])))


def test_draft_does_not_call_the_model_when_blocked(stub_client, gappy_extraction):
    gaps = detect_structural_gaps(gappy_extraction)
    client = stub_client(["draft"])
    with pytest.raises(GateBlockedError):
        run_draft(**_draft_args(gappy_extraction, gaps, set(), client))
    assert client.calls == []


def test_draft_error_names_the_unresolved_items(stub_client, gappy_extraction):
    gaps = detect_structural_gaps(gappy_extraction)
    with pytest.raises(GateBlockedError, match="2 unresolved"):
        run_draft(**_draft_args(gappy_extraction, gaps, set(), stub_client(["draft"])))


def test_draft_succeeds_once_every_blocking_gap_is_resolved(stub_client, gappy_extraction):
    """Resolving a gap means the field was actually filled in, not just dismissed."""
    gaps = detect_structural_gaps(gappy_extraction)
    gappy_extraction.action_items[0].owner = "Priya"
    gappy_extraction.action_items[0].deadline = "2026-09-20"
    client = stub_client(["## Decisions\n- none"])
    outcome = run_draft(**_draft_args(gappy_extraction, gaps,
                                      {g.id for g in gaps}, client))
    assert outcome.text.startswith("## Decisions")


def test_draft_proceeds_with_only_warnings_open(stub_client, clean_extraction):
    warning = Gap(id="w1", type=GapType.AMBIGUOUS_TASK, severity=Severity.WARNING,
                  target_id="a1", explanation="vague", suggested_question="?")
    client = stub_client(["message"])
    outcome = run_draft(**_draft_args(clean_extraction, [warning], set(), client))
    assert outcome.text == "message"


def test_draft_receives_only_approved_items(stub_client, clean_extraction):
    client = stub_client(["message"])
    run_draft(**_draft_args(clean_extraction, [], set(), client))
    user = client.calls[0]["user"]
    assert "Write the retry migration plan" in user
    assert "Sprint 24 Review" in user


def test_draft_blocked_when_a_resolved_gap_left_the_field_empty(stub_client, gappy_extraction):
    """Resolving a gap is bookkeeping; run_draft checks the data itself."""
    gaps = detect_structural_gaps(gappy_extraction)
    client = stub_client(["draft"])
    with pytest.raises(GateBlockedError, match="missing an owner or deadline"):
        run_draft(**_draft_args(gappy_extraction, gaps, {g.id for g in gaps}, client))
    assert client.calls == []


def test_draft_blocked_for_a_placeholder_owner_string(stub_client, clean_extraction):
    """Regression: a placeholder string like "null" must not slip past run_draft's
    own data check, even if it bypassed schema-level normalisation (e.g. via
    direct attribute assignment after construction)."""
    clean_extraction.action_items[0].owner = "null"
    client = stub_client(["draft"])
    with pytest.raises(GateBlockedError, match="missing an owner or deadline"):
        run_draft(**_draft_args(clean_extraction, [], set(), client))
    assert client.calls == []


def test_draft_blocked_for_an_item_that_never_had_a_gap(stub_client, clean_extraction):
    """A human-added item bypasses gap detection entirely; it must still be checked."""
    added = ActionItem(id="h1", task="Book the room", owner=None, deadline=None,
                       source_quote="", confidence=0.0)
    clean_extraction.action_items.append(added)
    client = stub_client(["draft"])
    with pytest.raises(GateBlockedError, match="Book the room"):
        run_draft(**_draft_args(clean_extraction, [], set(), client))
    assert client.calls == []


def test_draft_message_falls_back_when_there_are_no_action_items(stub_client, clean_extraction):
    """A decisions-only meeting must not emit a bare, empty header."""
    client = stub_client(["message"])
    run_draft(meeting_title="Decisions only", decisions=clean_extraction.decisions,
              action_items=[], gaps=[], resolved_ids=set(), client=client)
    user = client.calls[0]["user"]
    assert "Approved action items:\n- (none recorded)" in user


def test_draft_user_message_never_contains_a_none_owner(stub_client, clean_extraction):
    """Regression guard: the model must never be told 'owner: None'."""
    client = stub_client(["message"])
    run_draft(**_draft_args(clean_extraction, [], set(), client))
    user = client.calls[0]["user"]
    assert "owner: None" not in user
    assert "due: None" not in user


def test_empty_context_produces_todays_exact_prompt():
    """Invariant 5: an empty context must change nothing at all."""
    assert build_extract_user("some notes", MeetingContext()) == "Meeting notes:\n\nsome notes"


def test_prior_commitments_appear_in_a_delimited_block():
    ctx = MeetingContext(prior_commitments=(
        PriorCommitment(task="Write the retry plan", owner="Sam", deadline="2026-09-12",
                        meeting_title="Sprint 23", meeting_date="2026-09-01"),))
    user = build_extract_user("some notes", ctx)
    assert "Write the retry plan" in user
    assert "some notes" in user
    assert "BACKGROUND" in user


def test_owner_hints_never_reach_the_prompt():
    """Invariant 3. A model told 'Dan usually owns this' would fill it in."""
    ctx = MeetingContext(owner_hints=(
        OwnerHint(owner="Dan", times_assigned=9, example_task="Add error alerting"),))
    user = build_extract_user("some notes", ctx)
    assert "Dan" not in user
    assert "Add error alerting" not in user
    assert user == "Meeting notes:\n\nsome notes"


def test_feedback_from_triage_appears_for_a_second_pass():
    user = build_extract_user("some notes", MeetingContext(),
                              feedback=["Sam will write the plan"])
    assert "Sam will write the plan" in user
    assert "MISSED" in user


def test_run_extract_passes_context_through(stub_client, clean_extraction):
    ctx = MeetingContext(prior_commitments=(
        PriorCommitment(task="Write the retry plan", owner="Sam", deadline="2026-09-12",
                        meeting_title="Sprint 23", meeting_date="2026-09-01"),))
    client = stub_client([clean_extraction])
    run_extract("some notes", client, context=ctx)
    assert "Write the retry plan" in client.calls[0]["user"]


def test_run_extract_without_context_is_unchanged(stub_client, clean_extraction):
    client = stub_client([clean_extraction])
    run_extract("some notes", client)
    assert client.calls[0]["user"] == "Meeting notes:\n\nsome notes"


def test_prompt_version_is_v4():
    """The five-category taxonomy changes extraction behavior, so persisted
    prompt provenance must distinguish it from the contradictory v3 prompt."""
    assert prompts.PROMPT_VERSION == "v4"


def _gap(gap_id="g1", gap_type=GapType.MISSING_OWNER, target="a1"):
    return Gap(id=gap_id, type=gap_type, severity=Severity.BLOCKING,
               target_id=target, explanation="e", suggested_question="q")


def test_quote_supports_matches_ignoring_case_and_whitespace():
    notes = "Sam   will write\nthe retry migration plan by Friday."
    assert quote_supports("sam will write the retry migration plan", notes) is True


def test_quote_supports_rejects_an_invented_quote():
    assert quote_supports("Dan will handle it", "Sam will write the plan") is False


def test_quote_supports_rejects_none_and_blank():
    assert quote_supports(None, "anything") is False
    assert quote_supports("   ", "anything") is False


def test_quote_supports_requires_word_boundaries():
    """A bare "Dan" must not be supported by notes that only say "Danielle"."""
    assert quote_supports("Dan", "Danielle will handle it") is False
    assert quote_supports("Sam", "Samantha owns this") is False


def test_quote_supports_still_matches_a_whole_word():
    """The boundary rule must cost no legitimate match."""
    assert quote_supports("Dan", "Dan will handle it") is True
    assert quote_supports("Dan will handle it", "So Dan will handle it, agreed.") is True


def test_quote_supports_matches_across_punctuation():
    """Boundaries are word edges, not whitespace — a trailing comma or period
    in the notes must not defeat an otherwise exact quote."""
    assert quote_supports("Dan will handle it", "Agreed: Dan will handle it.") is True


def test_triage_keeps_a_verdict_backed_by_a_real_quote(stub_client, gappy_extraction):
    notes = "Priya said she would audit the error budget by 2026-10-02."
    result = TriageResult(triages=[GapTriage(
        gap_id="g1", verdict=TriageVerdict.SELF_RESOLVABLE,
        supporting_quote="Priya said she would audit the error budget",
        reasoning="the owner is stated")])
    outcome = run_triage(notes, gappy_extraction, [_gap()], stub_client([result]))
    assert outcome.triages[0].verdict is TriageVerdict.SELF_RESOLVABLE


def test_triage_downgrades_a_verdict_whose_quote_is_not_in_the_notes(
        stub_client, gappy_extraction):
    """The model proposes; deterministic code disposes."""
    notes = "Someone needs to audit the error budget."
    result = TriageResult(triages=[GapTriage(
        gap_id="g1", verdict=TriageVerdict.SELF_RESOLVABLE,
        supporting_quote="Dan will audit the error budget",
        reasoning="I think Dan owns this")])
    outcome = run_triage(notes, gappy_extraction, [_gap()], stub_client([result]))
    assert outcome.triages[0].verdict is TriageVerdict.NEEDS_HUMAN


def test_triage_downgrades_a_self_resolvable_verdict_with_no_quote_at_all(
        stub_client, gappy_extraction):
    result = TriageResult(triages=[GapTriage(
        gap_id="g1", verdict=TriageVerdict.SELF_RESOLVABLE,
        supporting_quote=None, reasoning="trust me")])
    outcome = run_triage("Priya raised the error budget.", gappy_extraction,
                         [_gap()], stub_client([result]))
    assert outcome.triages[0].verdict is TriageVerdict.NEEDS_HUMAN


def test_triage_downgrades_a_name_prefix_quote(stub_client, gappy_extraction):
    """End to end: the boundary rule reaches the verdict, not just the helper."""
    notes = "Danielle will audit the error budget."
    result = TriageResult(triages=[GapTriage(
        gap_id="g1", verdict=TriageVerdict.SELF_RESOLVABLE,
        supporting_quote="Dan", reasoning="Dan is named")])
    outcome = run_triage(notes, gappy_extraction, [_gap()], stub_client([result]))
    assert outcome.triages[0].verdict is TriageVerdict.NEEDS_HUMAN
    assert outcome.triages[0].gap_id == "g1"


def test_triage_failure_treats_every_gap_as_needing_a_human(
        stub_client, gappy_extraction):
    """Degrade to today's behaviour — never to 'no gaps'."""
    gaps = [_gap("g1"), _gap("g2", target="a2")]
    outcome = run_triage("Priya raised the error budget.", gappy_extraction, gaps,
                         stub_client([LLMError("boom")]))
    assert [t.verdict for t in outcome.triages] == [TriageVerdict.NEEDS_HUMAN] * 2
    assert [t.gap_id for t in outcome.triages] == ["g1", "g2"]


def test_triage_uses_zero_temperature(stub_client, gappy_extraction):
    result = TriageResult(triages=[])
    client = stub_client([result])
    run_triage("Priya raised the error budget.", gappy_extraction, [_gap()], client)
    assert client.calls[0]["temperature"] == 0.0


def test_triage_with_no_gaps_makes_no_model_call(stub_client, gappy_extraction):
    client = stub_client([])
    outcome = run_triage("Priya raised it.", gappy_extraction, [], client)
    assert outcome.triages == []
    assert client.calls == []


def test_missing_owner_gap_is_hopeless_when_no_name_appears():
    assert owner_gap_is_hopeless(_gap(gap_type=GapType.MISSING_OWNER),
                                 "someone needs to audit the budget") is True


def test_missing_owner_gap_is_not_hopeless_when_a_name_appears():
    assert owner_gap_is_hopeless(_gap(gap_type=GapType.MISSING_OWNER),
                                 "Priya will audit the budget") is False


def test_only_missing_owner_gaps_are_judged_hopeless():
    """A missing DEADLINE can be answered by a date, not a name."""
    assert owner_gap_is_hopeless(_gap(gap_type=GapType.MISSING_DEADLINE),
                                 "someone needs to audit it") is False


def test_triage_skips_the_model_for_a_hopeless_owner_gap(stub_client, gappy_extraction):
    """Spec 4.1: no candidate name in the notes means no model call is spent."""
    client = stub_client([])
    outcome = run_triage("someone needs to audit the budget", gappy_extraction,
                         [_gap(gap_type=GapType.MISSING_OWNER)], client)
    assert outcome.triages[0].verdict is TriageVerdict.NEEDS_HUMAN
    assert client.calls == []


def test_triage_still_consults_the_model_for_other_gaps(stub_client, gappy_extraction):
    """A hopeless owner gap must not suppress triage of its neighbours."""
    hopeless = _gap("g1", gap_type=GapType.MISSING_OWNER)
    answerable = _gap("g2", gap_type=GapType.MISSING_DEADLINE, target="a2")
    result = TriageResult(triages=[GapTriage(
        gap_id="g2", verdict=TriageVerdict.SELF_RESOLVABLE,
        supporting_quote="by 2026-10-02", reasoning="date stated")])
    outcome = run_triage("audit it by 2026-10-02", gappy_extraction,
                         [hopeless, answerable], stub_client([result]))
    verdicts = {t.gap_id: t.verdict for t in outcome.triages}
    assert verdicts["g1"] is TriageVerdict.NEEDS_HUMAN
    assert verdicts["g2"] is TriageVerdict.SELF_RESOLVABLE


def test_a_background_name_cannot_become_an_owner(stub_client, gappy_extraction):
    """The reproduced bypass, at the triage seam.

    Notes that name nobody; a model that returns a genuinely verbatim quote and
    calls the missing owner self-resolvable. Before the §4.1 rule the verdict
    stood, a second pass ran, and the extractor copied a name out of the
    BACKGROUND block of prior commitments. Now the gap never reaches the model.
    """
    notes = ("ops sync. someone needs to look at the alerting again before the "
             "2026-10-02 release.")
    optimistic = TriageResult(triages=[GapTriage(
        gap_id="g1", verdict=TriageVerdict.SELF_RESOLVABLE,
        supporting_quote="someone needs to look at the alerting again",
        reasoning="the notes say who")])
    client = stub_client([optimistic])
    outcome = run_triage(notes, gappy_extraction,
                         [_gap("g1", gap_type=GapType.MISSING_OWNER)], client)
    assert outcome.triages[0].verdict is TriageVerdict.NEEDS_HUMAN
    assert client.calls == [], "the model was consulted about an unanswerable owner"


def test_an_owner_hint_stays_out_of_a_prompt_that_has_a_background_block():
    """Belt and braces behind the SQL fix in storage/memory.py.

    `prior_commitments` no longer returns a row whose owner a human supplied, so
    a correctly-built context can no longer hold that person in both halves.
    This builds one by hand anyway, to prove the prompt-builder is not a second
    route: the hint for Dan is invisible even on the branch that DOES render a
    BACKGROUND block, not merely on the empty-context branch the older test
    covers.
    """
    ctx = MeetingContext(
        owner_hints=(OwnerHint(owner="Dan", times_assigned=3,
                               example_task="Add error alerting"),),
        prior_commitments=(PriorCommitment(task="Write the plan", owner="Sam",
                                           deadline="2026-09-12",
                                           meeting_title="Sprint 23",
                                           meeting_date="2026-09-01"),))
    user = build_extract_user("someone will look at the alerting", ctx)
    assert "BACKGROUND" in user, "the commitment branch must actually be exercised"
    assert "Dan" not in user
    assert "Add error alerting" not in user


def test_the_prompt_builder_is_not_where_a_human_supplied_owner_is_filtered():
    """Says plainly what the belt-and-braces guard above does NOT prove.

    `build_extract_user` renders whatever prior commitments it is handed, and it
    cannot do otherwise: `tests/test_layer_discipline.py` forbids anything under
    `agent/` from so much as reading `.owner_hints`, so the prompt builder has
    no way to know that a commitment's owner came from a human. The filter lives
    in `storage.memory.prior_commitments` (`AND ai.ai_owner IS NOT NULL`) and
    nowhere else. This test pins that division of labour so a future reader does
    not mistake the guard above for a defence in depth it is not.
    """
    ctx = MeetingContext(prior_commitments=(
        PriorCommitment(task="Add error alerting", owner="Dan",
                        deadline="2026-09-01", meeting_title="Ops sync",
                        meeting_date="2026-08-28"),))
    assert "Dan" in build_extract_user("notes", ctx)


def test_triage_ignores_a_verdict_on_a_gap_it_was_never_shown(stub_client, gappy_extraction):
    """An invented gap_id with a real quote must not feed a second pass."""
    result = TriageResult(triages=[GapTriage(
        gap_id="invented", verdict=TriageVerdict.SELF_RESOLVABLE,
        supporting_quote="audit it by 2026-10-02", reasoning="r")])
    outcome = run_triage("audit it by 2026-10-02", gappy_extraction,
                         [_gap("g2", gap_type=GapType.MISSING_DEADLINE)],
                         stub_client([result]))
    assert "invented" not in {t.gap_id for t in outcome.triages}


def test_triage_cannot_override_a_predetermined_verdict(stub_client, gappy_extraction):
    """A hopeless owner gap is settled before the model; a model verdict on the
    same id must not sit beside it and trigger a second pass anyway."""
    hopeless = _gap("g1", gap_type=GapType.MISSING_OWNER)
    answerable = _gap("g2", gap_type=GapType.MISSING_DEADLINE, target="a2")
    result = TriageResult(triages=[
        GapTriage(gap_id="g1", verdict=TriageVerdict.SELF_RESOLVABLE,
                  supporting_quote="audit it by 2026-10-02", reasoning="r"),
        GapTriage(gap_id="g2", verdict=TriageVerdict.NEEDS_HUMAN,
                  supporting_quote=None, reasoning="r"),
    ])
    outcome = run_triage("audit it by 2026-10-02", gappy_extraction,
                         [hopeless, answerable], stub_client([result]))
    g1 = [t for t in outcome.triages if t.gap_id == "g1"]
    assert [t.verdict for t in g1] == [TriageVerdict.NEEDS_HUMAN]


def test_triage_keeps_only_the_first_verdict_per_gap(stub_client, gappy_extraction):
    answerable = _gap("g2", gap_type=GapType.MISSING_DEADLINE, target="a2")
    result = TriageResult(triages=[
        GapTriage(gap_id="g2", verdict=TriageVerdict.NEEDS_HUMAN,
                  supporting_quote=None, reasoning="r"),
        GapTriage(gap_id="g2", verdict=TriageVerdict.SELF_RESOLVABLE,
                  supporting_quote="by 2026-10-02", reasoning="r"),
    ])
    outcome = run_triage("audit it by 2026-10-02", gappy_extraction,
                         [answerable], stub_client([result]))
    assert [t.verdict for t in outcome.triages] == [TriageVerdict.NEEDS_HUMAN]
