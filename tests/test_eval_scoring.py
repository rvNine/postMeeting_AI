from agent.schemas import ActionItem, Gap, GapType, MeetingExtraction, Severity
from eval.run_eval import pass2_gain, score_fixture


def _extraction(tasks_with_owners):
    return MeetingExtraction(
        summary="s", participants=[], decisions=[],
        action_items=[ActionItem(id=f"a{n}", task=t, owner=o, deadline=None,
                                 source_quote="q", confidence=0.8)
                      for n, (t, o) in enumerate(tasks_with_owners)])


EXPECTED = {
    "expected_action_items": ["audit the error budget", "rewrite the on-call rota"],
    "expected_decisions": [],
    "expected_blocking_gap_count": 4,
    "expected_missing_owner_count": 2,
    "must_not_fabricate": ["Priya", "Sam"],
}


def test_perfect_extraction_scores_one():
    extraction = _extraction([("audit the error budget", None),
                              ("rewrite the on-call rota", None)])
    score = score_fixture(EXPECTED, extraction, gaps=[])
    assert score["recall"] == 1.0
    assert score["precision"] == 1.0


def test_missed_item_lowers_recall():
    extraction = _extraction([("audit the error budget", None)])
    assert score_fixture(EXPECTED, extraction, gaps=[])["recall"] == 0.5


def test_invented_item_lowers_precision():
    extraction = _extraction([("audit the error budget", None),
                              ("rewrite the on-call rota", None),
                              ("buy a new coffee machine", None)])
    assert score_fixture(EXPECTED, extraction, gaps=[])["precision"] < 1.0


def test_fabricated_owner_is_counted():
    """R1: an owner the notes never stated is the one unforgivable failure."""
    extraction = _extraction([("audit the error budget", "Priya"),
                              ("rewrite the on-call rota", None)])
    assert score_fixture(EXPECTED, extraction, gaps=[])["fabrications"] == 1


def test_no_fabrication_when_owner_is_null():
    extraction = _extraction([("audit the error budget", None),
                              ("rewrite the on-call rota", None)])
    assert score_fixture(EXPECTED, extraction, gaps=[])["fabrications"] == 0


def test_gap_recall_counts_a_blocking_type_tagged_warning():
    """Mirrors agent.gaps.open_blocking: the taxonomy wins over a downgraded severity."""
    gap = Gap(id="g1", type=GapType.CONFLICTING_DECISION, severity=Severity.WARNING,
              target_id="d1", explanation="e", suggested_question="q")
    expected = dict(EXPECTED, expected_blocking_gap_count=1)
    score = score_fixture(expected, _extraction([]), gaps=[gap])
    assert score["gap_recall"] == 1.0


def test_fabrication_is_case_insensitive():
    extraction = _extraction([("audit the error budget", "Sam")])
    assert score_fixture(EXPECTED, extraction, gaps=[], notes="sam is away")["fabrications"] == 0


def test_fabrication_respects_word_boundaries():
    """'Sam' must not be considered supported by 'Samantha'."""
    extraction = _extraction([("audit the error budget", "Sam")])
    score = score_fixture(EXPECTED, extraction, gaps=[], notes="Samantha will do it")
    assert score["fabrications"] == 1


def test_owner_absent_from_notes_is_a_fabrication():
    extraction = _extraction([("audit the error budget", "Fabrice")])
    score = score_fixture(EXPECTED, extraction, gaps=[], notes="Priya and Sam attended")
    assert score["fabrications"] == 1


def test_owner_in_notes_but_not_in_quote_is_unsupported_not_fabricated():
    """Pronoun resolution is legitimate extraction, not invention."""
    extraction = _extraction([("audit the error budget", "Priya")])
    score = score_fixture(EXPECTED, extraction, gaps=[],
                          notes="Priya said she would audit the error budget")
    assert score["fabrications"] == 0
    assert score["unsupported_owners"] == 1


def test_score_fixture_records_the_pass_count():
    extraction = _extraction([("audit the error budget", None)])
    score = score_fixture(EXPECTED, extraction, gaps=[], passes=2)
    assert score["passes"] == 2


def test_pass2_gain_is_the_recall_difference():
    """Reported, not assumed. A loop that changes nothing must say so."""
    before = _extraction([("audit the error budget", None)])
    after = _extraction([("audit the error budget", None),
                         ("rewrite the on-call rota", None)])
    gain = pass2_gain(EXPECTED, before, after)
    assert gain["recall_before"] == 0.5
    assert gain["recall_after"] == 1.0
    assert gain["recall_delta"] == 0.5
