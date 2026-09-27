from fixtures import loader


def test_five_samples_are_available():
    samples = loader.list_samples()
    assert len(samples) == 5


def test_every_sample_has_notes_and_a_title():
    for sample in loader.list_samples():
        assert sample["notes"].strip()
        assert sample["title"]


def test_every_sample_has_a_gold_answer():
    for sample in loader.list_samples():
        expected = loader.load_expected(sample["slug"])
        assert "expected_blocking_gap_count" in expected


def test_clean_fixture_expects_no_blocking_gaps():
    assert loader.load_expected("1_clean_sprint_review")["expected_blocking_gap_count"] == 0


def test_no_owners_fixture_expects_six_missing_owners():
    expected = loader.load_expected("2_no_owners_planning")
    assert expected["expected_missing_owner_count"] == 6
