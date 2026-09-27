import json
import pytest
from pathlib import Path

from query.models import ChunkRecord, QueryFilters
from query.retrieval import (
    combined_score,
    eligible,
    normalized_fts_rank,
    retrieve,
    run_golden_queries,
)
from query.vector import NullVectorAdapter
from storage.meeting_knowledge import persist_chunks


GOLDEN_QUERY_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "technical_standardization"
    / "golden_queries.json"
)


def test_owner_filter_is_applied_before_semantic_ranking(indexed_conn, vector):
    """Dropping the SQL owner restriction must expose unrelated evidence."""
    result = retrieve(
        indexed_conn,
        "compatibility testing",
        QueryFilters(owner="Sia Moss"),
        vector=vector,
    )

    assert result.evidence
    assert {item.meeting_id for item in result.evidence} <= {
        "fx-interoperability",
        "fx-rollout-readiness",
    }
    assert result.trace.applied_filter_fields == ("owner",)


def test_all_structured_filters_narrow_candidates_before_retrieval(indexed_conn, vector):
    """Removing any structured predicate must never broaden a filtered request."""
    filters = QueryFilters(
        date_from="2026-09-12",
        date_to="2026-10-06",
        meeting_id="fx-rollout-readiness",
        participant="Sia Moss",
        owner="Sia Moss",
        record_type="risks",
        severity="high",
        program_phase="rollout_readiness",
    )

    result = retrieve(indexed_conn, "external consumers version negotiation", filters, vector=vector)

    assert result.trace.applied_filter_fields == (
        "date_from", "date_to", "meeting_id", "participant", "owner",
        "record_type", "severity", "program_phase",
    )
    assert result.trace.candidate_meeting_ids == ("fx-rollout-readiness",)
    assert result.evidence
    assert {item.meeting_id for item in result.evidence} == {"fx-rollout-readiness"}
    assert {item.record_type for item in result.structured_matches} == {"risks"}


def test_text_filters_casefold_and_normalize_internal_whitespace(indexed_conn, vector):
    """SQL text filtering must apply the same canonical form as the API boundary."""
    result = retrieve(
        indexed_conn,
        "external consumers version negotiation",
        QueryFilters(owner="  sIA   mOsS  "),
        vector=vector,
    )

    assert result.trace.candidate_meeting_ids == (
        "fx-interoperability", "fx-rollout-readiness"
    )
    assert {item.meeting_id for item in result.evidence} <= {
        "fx-interoperability", "fx-rollout-readiness"
    }


def test_every_candidate_must_individually_meet_lexical_coverage(indexed_conn, vector):
    """Aggregate term coverage must not re-admit low-coverage candidate chunks."""
    persist_chunks(
        indexed_conn,
        [
            ChunkRecord("coverage-alpha", "fx-kickoff", 0, "alpha", "test"),
            ChunkRecord("coverage-beta", "fx-kickoff", 1, "beta", "test"),
        ],
        meeting_id="fx-kickoff",
    )

    result = retrieve(indexed_conn, "alpha beta", QueryFilters(), vector=vector)

    assert result.evidence == []
    assert {"coverage-alpha", "coverage-beta"} <= set(result.trace.rejected_chunk_ids)


def test_cross_meeting_retrieval_returns_valid_related_chunk_metadata(indexed_conn, vector):
    """Relationship evidence must remain tied to persisted links and stored chunks."""
    result = retrieve(
        indexed_conn,
        "readiness continues revised roadmap",
        QueryFilters(),
        vector=vector,
    )

    linked_evidence = [item for item in result.evidence if item.relationship_label]
    stored_chunk_ids = {
        row["chunk_id"] for row in indexed_conn.execute("SELECT chunk_id FROM meeting_chunks")
    }
    linked_endpoints = {
        (link.source_meeting_id, link.target_meeting_id, link.link_type)
        for link in result.relationships
    }

    assert linked_evidence
    assert all(item.chunk_id in stored_chunk_ids for item in linked_evidence)
    assert all(
        any(
            item.relationship_label == link_type
            and item.meeting_id in {source_meeting_id, target_meeting_id}
            for source_meeting_id, target_meeting_id, link_type in linked_endpoints
        )
        for item in linked_evidence
    )


def test_relationship_query_never_fabricates_an_empty_chunk(indexed_conn):
    """A stored link alone is not evidence when no candidate chunk is eligible."""
    persist_chunks(
        indexed_conn,
        [
            ChunkRecord("relation-alpha", "fx-kickoff", 0, "alpha", "test"),
            ChunkRecord("relation-beta", "fx-kickoff", 1, "beta", "test"),
        ],
        meeting_id="fx-kickoff",
    )
    result = retrieve(
        indexed_conn,
        "history alpha beta",
        QueryFilters(),
        vector=NullVectorAdapter(),
    )

    assert result.evidence == []


def test_relationship_metadata_requires_stored_chunks_at_both_endpoints(indexed_conn, vector):
    """A link cannot label evidence after one of its endpoint chunks is removed."""
    indexed_conn.execute("DELETE FROM meeting_chunks WHERE meeting_id = ?", ("fx-design-review",))

    result = retrieve(
        indexed_conn,
        "compatibility work implements envelope decision",
        QueryFilters(),
        vector=vector,
    )

    assert not any(item.relationship_label == "implements" for item in result.evidence)


def test_relationship_expansion_cannot_bypass_owner_filter(indexed_conn, vector):
    """A linked meeting with another owner must remain outside a filtered request."""
    result = retrieve(
        indexed_conn,
        "compatibility testing",
        QueryFilters(owner="Sia Moss"),
        vector=vector,
    )

    assert {item.meeting_id for item in result.evidence} <= {
        "fx-interoperability",
        "fx-rollout-readiness",
    }


def test_retrieval_order_is_stable_on_repeated_calls(indexed_conn, vector):
    """Changing a tie breaker would make citations non-repeatable."""
    first = retrieve(indexed_conn, "batch size", QueryFilters(), vector=vector)
    second = retrieve(indexed_conn, "batch size", QueryFilters(), vector=vector)

    assert [(item.chunk_id, item.score) for item in first.evidence] == [
        (item.chunk_id, item.score) for item in second.evidence
    ]


def test_fts_query_with_punctuation_is_tokenized_safely(indexed_conn, vector):
    """Passing raw punctuation to FTS5 must not turn user input into syntax."""
    result = retrieve(
        indexed_conn,
        'schema_rev:2 "sent_at" *',
        QueryFilters(),
        vector=vector,
    )

    assert result.evidence
    assert result.trace.normalized_terms == ("schema_rev", "2", "sent_at")


def test_lexical_coverage_boundary_is_explicit(indexed_conn, vector):
    """Lowering the relevance gate would answer an absent migration deadline."""
    result = retrieve(
        indexed_conn,
        "database migration deadline",
        QueryFilters(),
        vector=vector,
    )

    assert result.evidence == []
    assert result.trace.lexical_coverage_max < 0.75
    assert result.trace.eligible_chunk_ids == ()


def test_ranking_threshold_helpers_are_executable_boundaries():
    """Changing either cut-off must be caught at its exact boundary."""
    assert normalized_fts_rank(0.0) == 1.0
    assert normalized_fts_rank(-3.0) == 1.0
    assert eligible(lexical_coverage=0.75, fts_rank=0.35)
    assert not eligible(lexical_coverage=0.749, fts_rank=1.0)
    assert not eligible(lexical_coverage=1.0, fts_rank=0.349)
    score = combined_score(
        lexical_coverage=0.123456789123,
        fts_rank=0.234567891234,
        vector_score=0.345678912345,
    )
    assert score != round(score, 12)


def test_golden_query_regression_cases_execute_without_an_llm(indexed_conn, vector):
    """Removing a fixture case or bypassing retrieval must fail the offline gate."""
    cases = json.loads(GOLDEN_QUERY_PATH.read_text())

    assert 30 <= len(cases) <= 35
    assert all(
        {"question", "filters", "answerable", "expected_meetings", "expected_phrases", "filters_expected"}
        <= case.keys()
        for case in cases
    )

    results = run_golden_queries(indexed_conn, cases, vector)

    assert len(results) == len(cases)
    assert all(result.passed for result in results)


def test_golden_queries_compare_expected_filter_fields_with_the_trace(indexed_conn, vector):
    """A fixture must fail when it claims a filter field retrieval did not apply."""
    case = {
        "question": "compatibility tests",
        "filters": {"owner": "Sia Moss"},
        "answerable": True,
        "expected_meetings": ["fx-interoperability"],
        "expected_phrases": ["compatibility tests against schema revisions"],
        "filters_expected": {"participant": "Sia Moss"},
    }

    result = run_golden_queries(indexed_conn, [case], vector)[0]

    assert not result.passed


@pytest.mark.parametrize(
    ("question", "meeting_id", "phrase"),
    [
        ("What was approved?", "fx-rollout-readiness", "Approve a staged rollout"),
        ("What was superseded?", "fx-change-control", "Supersede the original 500-event pilot target"),
        ("What changed in change control?", "fx-change-control", "Supersede the original 500-event pilot target"),
        ("Which risks were raised for the rollout?", "fx-rollout-readiness", "External consumers may have untested version negotiation"),
        ("What did we decide about the envelope?", "fx-kickoff", "Use one versioned event envelope"),
        ("Who owns the compatibility tests?", "fx-interoperability", "compatibility tests"),
    ],
)
def test_conversational_questions_reach_the_matching_meeting(indexed_conn, vector, question, meeting_id, phrase):
    """Inflected or conversational wording must not hide evidence the notes contain."""
    result = retrieve(indexed_conn, question, QueryFilters(), vector=vector)

    matching = [item for item in result.evidence if item.meeting_id == meeting_id]
    assert matching, (question, [item.meeting_id for item in result.evidence])
    assert any(phrase.casefold() in item.text_fragment.casefold() for item in matching)


@pytest.mark.parametrize(
    "question",
    [
        "Which vendor was chosen?",
        "Was a production incident declared during rollout?",
        "Did the meetings mention a database migration deadline?",
        "What real world patent number was cited?",
    ],
)
def test_conversational_questions_about_absent_topics_still_abstain(indexed_conn, vector, question):
    """Better normalization must not turn absent topics into answers."""
    assert retrieve(indexed_conn, question, QueryFilters(), vector=vector).evidence == []


def test_inflections_share_one_stem():
    """A question's inflection must match the notes' base form, and vice versa."""
    from query.retrieval import _stem

    for group in (("approve", "approved", "approves", "approving"),
                  ("supersede", "superseded", "supersedes"),
                  ("change", "changed", "changes", "changing"),
                  ("dependency", "dependencies"),
                  ("block", "blocked", "blocking"),
                  ("risk", "risks")):
        assert len({_stem(word) for word in group}) == 1, group


@pytest.mark.parametrize(
    "question",
    [
        "Who owns the database migration deadline?",
        "What was decided about the database migration deadline?",
        "What did Mira Vale decide about blockchain?",
        "slug fixture_set source_type",
    ],
)
def test_record_labels_and_front_matter_do_not_count_as_topic_matches(indexed_conn, vector, question):
    """'owner'/'decision' appear in nearly every chunk and front matter in every
    first chunk; neither may lift an absent topic over the coverage gate."""
    assert retrieve(indexed_conn, question, QueryFilters(), vector=vector).evidence == []


def test_direct_hits_carry_no_relationship_label(indexed_conn, vector):
    """Only meetings pulled in through a stored link are labelled as related."""
    result = retrieve(indexed_conn, "versioned event envelope", QueryFilters(), vector=vector)
    direct = [item for item in result.evidence if "versioned event envelope" in item.text_fragment.casefold()]
    assert direct
    assert all(item.relationship_label is None for item in direct)
    assert any(item.relationship_label for item in result.evidence)
