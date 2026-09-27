import re
from pathlib import Path

from agent.gaps import BLOCKING_TYPES
from agent.schemas import Gap, GapType, OwnerHint, PriorCommitment, Severity
from ui.gap_display import (DATA_FIXABLE_TYPES, PRIOR_COMMITMENTS_CAPTION, badge,
                            draft_blocked, format_prior_commitment, gap_is_satisfied,
                            gaps_for_item, gate_message, items_missing_fields,
                            needs_manual_resolution, owner_suggestion,
                            prior_commitment_lines, sort_items_gaps_first,
                            unattached_gaps, unresolved_manual_gaps)

REVIEW_VIEW = Path(__file__).parent.parent / "ui" / "review_view.py"


def _gap(gap_id, target, gap_type, severity=Severity.BLOCKING):
    return Gap(id=gap_id, type=gap_type, severity=severity, target_id=target,
               explanation="e", suggested_question="q")


def test_gate_message_is_singular_for_one_gap():
    msg = gate_message([_gap("g1", "a1", GapType.MISSING_OWNER)])
    assert "1 detail needs your input" in msg


def test_gate_message_is_plural_for_several_gaps():
    """One item missing both owner and deadline is two details, not two items."""
    gaps = [_gap("g1", "a1", GapType.MISSING_OWNER),
            _gap("g2", "a1", GapType.MISSING_DEADLINE)]
    assert "2 details need your input" in gate_message(gaps)


def test_gate_message_is_empty_when_nothing_blocks():
    assert gate_message([]) == ""


def test_gaps_for_item_filters_by_target():
    gaps = [_gap("g1", "a1", GapType.MISSING_OWNER),
            _gap("g2", "a2", GapType.MISSING_OWNER)]
    assert [g.id for g in gaps_for_item(gaps, "a1")] == ["g1"]


def test_items_with_blocking_gaps_sort_first():
    items = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
    gaps = [_gap("g1", "a3", GapType.MISSING_OWNER)]
    assert [i["id"] for i in sort_items_gaps_first(items, gaps)] == ["a3", "a1", "a2"]


def test_sorting_is_stable_among_items_without_gaps():
    items = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
    assert [i["id"] for i in sort_items_gaps_first(items, [])] == ["a1", "a2", "a3"]


def test_badge_distinguishes_blocking_from_warning():
    blocking = badge(_gap("g1", "a1", GapType.MISSING_OWNER))
    warning = badge(_gap("g2", "a1", GapType.AMBIGUOUS_TASK, Severity.WARNING))
    assert blocking != warning
    assert "owner" in blocking.lower()


def test_gap_is_satisfied_for_owner():
    g = _gap("g1", "a1", GapType.MISSING_OWNER)
    assert gap_is_satisfied(g, "Priya", None) is True
    assert gap_is_satisfied(g, "", None) is False
    assert gap_is_satisfied(g, "   ", None) is False
    assert gap_is_satisfied(g, None, None) is False


def test_gap_is_satisfied_for_deadline():
    g = _gap("g1", "a1", GapType.MISSING_DEADLINE)
    assert gap_is_satisfied(g, None, "2026-10-02") is True
    assert gap_is_satisfied(g, None, "") is False


def test_gap_is_satisfied_is_false_for_types_data_cannot_fix():
    g = _gap("g1", "d1", GapType.CONFLICTING_DECISION)
    assert gap_is_satisfied(g, "Priya", "2026-10-02") is False


def test_gap_is_not_satisfied_by_a_placeholder_owner():
    """A human typing "null"/"N/A" must not clear the badge — the button would
    stay disabled with nothing on screen explaining why."""
    g = _gap("g1", "a1", GapType.MISSING_OWNER)
    for placeholder in ("null", "N/A", "TBD", "  none  ", "-"):
        assert gap_is_satisfied(g, placeholder, None) is False
    assert gap_is_satisfied(g, "Priya", None) is True


def test_gap_is_not_satisfied_by_a_placeholder_deadline():
    g = _gap("g1", "a1", GapType.MISSING_DEADLINE)
    assert gap_is_satisfied(g, None, "TBD") is False
    assert gap_is_satisfied(g, None, "2026-10-02") is True


def test_badge_and_button_agree_on_a_placeholder_owner():
    """Regression guard for the disagreement itself: whatever clears the badge
    must also unblock the button, and vice versa."""
    g = _gap("g1", "a1", GapType.MISSING_OWNER)
    rows = [{"id": "a1", "owner": "null", "deadline": "2026-10-02"}]
    resolved = {g.id} if gap_is_satisfied(g, "null", "2026-10-02") else set()
    assert draft_blocked(rows, [g], resolved) is True
    assert resolved == set()   # the gap must NOT have been treated as resolved


def test_items_missing_fields_finds_blank_and_whitespace():
    items = [{"id": "a1", "owner": "Priya", "deadline": "2026-10-02"},
             {"id": "a2", "owner": None, "deadline": "2026-10-02"},
             {"id": "a3", "owner": "Sam", "deadline": "  "}]
    assert [i["id"] for i in items_missing_fields(items)] == ["a2", "a3"]


def test_items_missing_fields_flags_a_placeholder_owner_string():
    """Regression: a row whose owner is the literal string "null" must be flagged."""
    items = [{"id": "a1", "owner": "null", "deadline": "2026-10-02"}]
    assert [i["id"] for i in items_missing_fields(items)] == ["a1"]


def test_draft_blocked_for_a_placeholder_owner_string():
    items = [{"id": "a1", "owner": "null", "deadline": "2026-10-02"}]
    assert draft_blocked(items, [], set()) is True


def test_draft_blocked_when_an_item_has_no_gap_but_blank_fields():
    """Finding 2: the button must gate on data, not only on gaps."""
    items = [{"id": "a1", "owner": None, "deadline": None}]
    assert draft_blocked(items, [], set()) is True


def test_draft_not_blocked_when_data_complete_and_gaps_resolved():
    items = [{"id": "a1", "owner": "Priya", "deadline": "2026-10-02"}]
    gap = _gap("g1", "a1", GapType.MISSING_OWNER)
    assert draft_blocked(items, [gap], {"g1"}) is False


def test_resolved_gaps_stop_floating_to_the_top():
    """Finding 4."""
    items = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
    gaps = [_gap("g1", "a3", GapType.MISSING_OWNER)]
    assert [i["id"] for i in sort_items_gaps_first(items, gaps, {"g1"})] == ["a1", "a2", "a3"]


# --- every blocking gap type must be dischargeable ---------------------------
#
# db.resolve_gap has exactly two kinds of caller: the data-edit handlers (Save /
# Delete on an action item, which consult gap_is_satisfied) and the explicit
# "Mark resolved" control. gap_is_satisfied returns True only for
# DATA_FIXABLE_TYPES, so a blocking type outside that set that is *also* not
# given a manual control can never enter resolved_ids — which is exactly how
# CONFLICTING_DECISION made fixture 3 permanently un-draftable.


def test_gap_is_satisfied_can_only_ever_be_true_for_data_fixable_types():
    """Pins the assumption the property test below rests on."""
    satisfiable = {t for t in GapType
                   if gap_is_satisfied(_gap("g", "x", t), "Priya", "2026-10-02")}
    assert satisfiable == set(DATA_FIXABLE_TYPES)


def test_every_blocking_gap_type_has_a_path_into_resolved_ids():
    """The general property, not just the CONFLICTING_DECISION case: for every
    blocking type, either a data edit can satisfy it or it is routed to a manual
    control. Adding a new member to BLOCKING_TYPES with neither route fails here.
    """
    for gap_type in BLOCKING_TYPES:
        gap = _gap("g1", "t1", gap_type)
        data_fixable = gap_is_satisfied(gap, "Priya", "2026-10-02")
        assert data_fixable or needs_manual_resolution(gap), (
            f"{gap_type.value} is blocking but nothing can resolve it: no data edit "
            f"satisfies it and the view is not told to render a manual control")
        assert not (data_fixable and needs_manual_resolution(gap)), (
            f"{gap_type.value} claims both routes — the partition must be exact")


def test_a_conflicting_decision_gap_is_not_data_fixable():
    gap = _gap("g1", "d1", GapType.CONFLICTING_DECISION)
    assert gap_is_satisfied(gap, "Priya", "2026-10-02") is False
    assert needs_manual_resolution(gap) is True


def test_unresolved_manual_gaps_returns_the_conflict_gap_for_its_decision():
    gaps = [_gap("g1", "d1", GapType.CONFLICTING_DECISION),
            _gap("g2", "a1", GapType.MISSING_OWNER)]
    assert [g.id for g in unresolved_manual_gaps(gaps, "d1", set())] == ["g1"]
    assert unresolved_manual_gaps(gaps, "a1", set()) == []   # data-fixable, excluded


def test_unresolved_manual_gaps_drops_a_gap_once_it_is_resolved():
    """The control must disappear after the manager clicks it."""
    gaps = [_gap("g1", "d1", GapType.CONFLICTING_DECISION)]
    assert unresolved_manual_gaps(gaps, "d1", {"g1"}) == []


def test_unresolved_manual_gaps_ignores_a_non_blocking_warning():
    """A warning does not gate the draft, so it needs no resolve control."""
    gaps = [_gap("g1", "a1", GapType.AMBIGUOUS_TASK, severity=Severity.WARNING)]
    assert unresolved_manual_gaps(gaps, "a1", set()) == []


def test_marking_a_conflict_resolved_unblocks_the_draft():
    """End state: the whole reason the control exists."""
    items = [{"id": "a1", "owner": "Dan", "deadline": "2026-10-02"}]
    gaps = [_gap("g1", "d1", GapType.CONFLICTING_DECISION)]
    assert draft_blocked(items, gaps, set()) is True
    assert draft_blocked(items, gaps, {"g1"}) is False


# --- the view actually wires the control up ----------------------------------


def _function_source(name: str) -> str:
    """Slice one top-level function out of ui/review_view.py by text.

    Read as text rather than imported: review_view imports streamlit, and this
    assertion is about the source, not about running a Streamlit widget.
    """
    source = REVIEW_VIEW.read_text()
    match = re.search(rf"\ndef {name}\(.*?(?=\ndef |\Z)", source, re.DOTALL)
    assert match, f"ui/review_view.py has no top-level {name}()"
    return match.group(0)


def test_the_review_view_renders_a_resolve_control_for_manual_gaps():
    """Structural: the decision renderer must consult unresolved_manual_gaps and
    call db.resolve_gap from a control of its own. Without this, the pure
    property above holds while the button that discharges it is missing from
    the screen, which is precisely the state fixture 3 was in.
    """
    source = _function_source("_render_decision")
    assert "unresolved_manual_gaps(" in source
    assert "Mark resolved" in source
    assert "db.resolve_gap(" in source


def test_the_review_view_renders_the_prior_commitments_panel():
    """Structural: `render` must actually call `_render_prior_commitments`.

    The four prior-commitment tests elsewhere in this file only exercise the
    pure helpers (`prior_commitment_lines`, `format_prior_commitment`, the
    memory queries). None of them would fail if the call site in `render` were
    deleted — the manager would just silently lose the audit panel while every
    pure property kept holding. This pins the call site itself.
    """
    source = _function_source("render")
    assert "_render_prior_commitments(" in source


def test_every_technical_renderer_shows_human_provenance_and_evidence_state():
    for renderer in ("_render_risk", "_render_dependency", "_render_learning"):
        assert "_render_technical_provenance(" in _function_source(renderer)


def test_the_decision_delete_handler_resolves_that_decisions_gaps():
    """PRD §4.3 step 4 resolves the contradiction by deleting the superseded
    decision. A gap left open against a deleted row blocks forever with no
    control left on screen, so Delete must discharge it — as the action-item
    Delete handler already did."""
    source = _function_source("_render_decision")
    delete_block = source[source.index("db.delete_decision("):]
    assert "db.resolve_gap(" in delete_block


# --- unattached_gaps: the target_id-doesn't-exist permanent lock -------------
#
# The extraction prompt asks the model for a real target_id but nothing
# validates it, so a hallucinated or malformed id ("d1,d2", "", a task string)
# produces a blocking gap that is counted in the banner but has no control
# anywhere on screen — the same permanent lock unresolved_manual_gaps exists
# to close, reached by a different route.


def test_unattached_gaps_excludes_a_gap_targeting_a_real_item():
    gap = _gap("g1", "a1", GapType.MISSING_OWNER)
    assert unattached_gaps([gap], {"a1"}, set(), set()) == []


def test_unattached_gaps_excludes_a_gap_targeting_a_real_decision():
    gap = _gap("g1", "d1", GapType.CONFLICTING_DECISION)
    assert unattached_gaps([gap], set(), {"d1"}, set()) == []


def test_unattached_gaps_includes_a_gap_targeting_nothing_rendered():
    gap = _gap("g1", "bogus-id", GapType.MISSING_OWNER)
    assert [g.id for g in unattached_gaps([gap], {"a1"}, {"d1"}, set())] == ["g1"]


def test_unattached_gaps_excludes_a_resolved_gap():
    gap = _gap("g1", "bogus-id", GapType.MISSING_OWNER)
    assert unattached_gaps([gap], set(), set(), {"g1"}) == []


def test_unattached_gaps_includes_unresolved_warnings_with_malformed_targets():
    gaps = [
        _gap("g1", "bogus-id", GapType.AMBIGUOUS_TASK, severity=Severity.WARNING),
        _gap("g2", "d1,d2", GapType.UNRESOLVED_QUESTION, severity=Severity.WARNING),
        _gap("g3", "", GapType.UNSUPPORTED_EVIDENCE, severity=Severity.WARNING),
    ]
    assert [gap.id for gap in unattached_gaps(gaps, set(), set(), set())] == [
        "g1", "g2", "g3"]


def test_visible_unattached_warning_does_not_change_draft_gate_semantics():
    items = [{"id": "a1", "owner": "Priya", "deadline": "2026-10-02"}]
    warning = _gap(
        "g1", "malformed-target", GapType.UNRESOLVED_QUESTION,
        severity=Severity.WARNING,
    )
    assert unattached_gaps([warning], {"a1"}, set(), set()) == [warning]
    assert draft_blocked(items, [warning], set()) is False


def test_owner_suggestion_only_appears_for_a_blank_owner():
    hints = (OwnerHint(owner="Dan", times_assigned=3, example_task="Add alerting"),)
    assert owner_suggestion(hints, {"owner": None}) is not None
    assert owner_suggestion(hints, {"owner": "Sam"}) is None


def test_owner_suggestion_treats_a_placeholder_owner_as_blank():
    hints = (OwnerHint(owner="Dan", times_assigned=3, example_task="Add alerting"),)
    assert owner_suggestion(hints, {"owner": "null"}) is not None


def test_owner_suggestion_names_who_and_how_often():
    hints = (OwnerHint(owner="Dan", times_assigned=3, example_task="Add alerting"),)
    text = owner_suggestion(hints, {"owner": None})
    assert "Dan" in text and "3 times" in text


def test_owner_suggestion_claims_no_similarity_it_did_not_compute():
    """There is no similarity computation: the helper ignores the item except
    for blankness and always renders hints[0]. The copy must not imply one."""
    hints = (OwnerHint(owner="Dan", times_assigned=3, example_task="Add alerting"),)
    text = owner_suggestion(hints, {"owner": None})
    assert "similar" not in text.lower()


def test_owner_suggestion_does_not_offer_the_example_task_as_a_reason():
    """example_task is SQL MIN(task) — alphabetically first, not most recent and
    not most relevant. Beside a name it would read as evidence of a match."""
    hints = (OwnerHint(owner="Dan", times_assigned=3, example_task="Add alerting"),)
    assert "Add alerting" not in owner_suggestion(hints, {"owner": None})


def test_owner_suggestion_says_once_for_a_single_assignment():
    hints = (OwnerHint(owner="Dan", times_assigned=1, example_task="Add alerting"),)
    assert "once" in owner_suggestion(hints, {"owner": None})


def test_owner_suggestion_is_none_without_hints():
    assert owner_suggestion((), {"owner": None}) is None


def _commitment(task="Add error alerting", owner="Dan", deadline="2026-09-01",
                title="Ops sync", date="2026-08-28"):
    return PriorCommitment(task=task, owner=owner, deadline=deadline,
                           meeting_title=title, meeting_date=date)


def test_format_prior_commitment_names_the_meeting_it_came_from():
    """The provenance half is the point: a manager must be able to tell a name
    carried forward from last week apart from one today's notes stated."""
    line = format_prior_commitment(_commitment())
    assert line == ("Add error alerting — Dan, due 2026-09-01 "
                    "(Ops sync, 2026-08-28)")


def test_prior_commitment_lines_preserves_the_order_memory_returned():
    commitments = (_commitment(task="First"), _commitment(task="Second"))
    assert [line.split(" — ")[0] for line in prior_commitment_lines(commitments)] == [
        "First", "Second"]


def test_prior_commitment_lines_is_empty_for_no_memory():
    assert prior_commitment_lines(()) == []


def test_the_caption_states_every_limitation_the_query_cannot_back_up():
    """Three claims the manager needs: not today's notes, no completion
    tracking, and that the agent was given them as background."""
    caption = PRIOR_COMMITMENTS_CAPTION.lower()
    assert "earlier meetings" in caption
    assert "completion tracking" in caption
    assert "background" in caption


# --- Controller amendment A3: badge() must not KeyError on every GapType -----


def test_every_gaptype_has_a_badge_label():
    """Regression guard for the crash: `badge()` indexes `_LABELS[gap.type]`
    with no entry for GapType.UNSUPPORTED_EVIDENCE, so a WARNING evidence gap
    on a risk/dependency/learning row raised KeyError on the review screen the
    moment Task 5 tried to render it."""
    for gap_type in GapType:
        label = badge(_gap("g1", "t1", gap_type))
        assert label


# --- Controller amendment A4: unattached_gaps() must know about technical ----
# records too, without breaking any existing positional caller.


def test_unattached_gaps_excludes_a_gap_targeting_a_real_risk():
    gap = _gap("g1", "r1", GapType.UNSUPPORTED_EVIDENCE, severity=Severity.WARNING)
    assert unattached_gaps([gap], set(), set(), set(), risk_ids={"r1"}) == []


def test_unattached_gaps_excludes_a_gap_targeting_a_real_dependency():
    gap = _gap("g1", "dep1", GapType.MISSING_OWNER)
    assert unattached_gaps([gap], set(), set(), set(), dependency_ids={"dep1"}) == []


def test_unattached_gaps_excludes_a_gap_targeting_a_real_learning():
    gap = _gap("g1", "l1", GapType.MISSING_OWNER)
    assert unattached_gaps([gap], set(), set(), set(), learning_ids={"l1"}) == []


def test_unattached_gaps_still_flags_a_gap_targeting_nothing_technical_either():
    gap = _gap("g1", "bogus-id", GapType.MISSING_OWNER)
    assert [g.id for g in unattached_gaps([gap], set(), set(), set(),
                                          risk_ids={"r1"}, dependency_ids={"dep1"},
                                          learning_ids={"l1"})] == ["g1"]


# --- Controller amendment A6: every blocking-capable GapType is resolvable ---


def test_every_gaptype_that_can_be_blocking_has_a_resolution_path():
    """Severity and type are supplied independently (see `open_blocking`), so
    ANY GapType can arrive tagged BLOCKING regardless of BLOCKING_TYPES
    membership. This is the general property behind
    `test_every_blocking_gap_type_has_a_path_into_resolved_ids` above, over
    every member of the enum rather than just BLOCKING_TYPES — it is what
    would have caught UNSUPPORTED_EVIDENCE having no resolution path if one
    had been missed.
    """
    for gap_type in GapType:
        gap = _gap("g1", "t1", gap_type, severity=Severity.BLOCKING)
        data_fixable = gap_is_satisfied(gap, "Priya", "2026-10-02")
        assert data_fixable or needs_manual_resolution(gap), (
            f"{gap_type.value} can be tagged blocking but nothing can resolve it")


# --- Controller amendment A7: a warning evidence gap on a risk never gates ---


def test_a_warning_unsupported_evidence_gap_on_a_risk_does_not_block_the_draft():
    """UNSUPPORTED_EVIDENCE on a risk is severity WARNING (agent/gaps.py's
    `detect_evidence_gaps`), not in BLOCKING_TYPES, so it must never disable
    the Draft button even while the item list is otherwise complete."""
    items = [{"id": "a1", "owner": "Priya", "deadline": "2026-10-02"}]
    gap = _gap("g1", "meeting1:risk:r1", GapType.UNSUPPORTED_EVIDENCE,
              severity=Severity.WARNING)
    assert draft_blocked(items, [gap], set()) is False
