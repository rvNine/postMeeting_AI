import json
from pathlib import Path
import re

import pytest

from agent.llm_client import LLMError
from query.models import AnswerDraft, QueryFilters
from query.retrieval import retrieve
from query.service import QueryService


GOLDEN_QUERY_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "technical_standardization"
    / "golden_queries.json"
)


def test_service_sends_only_retrieved_evidence_to_llm(indexed_conn, stub_client, vector):
    client = stub_client([AnswerDraft(status="answered", answer="Approved in rollout.", citation_ids=["c1"])])
    result = QueryService(indexed_conn, client, vector).ask("versioned event envelope", QueryFilters())
    assert result.status == "answered"
    assert "Approved in rollout." in result.answer
    bundle = retrieve(indexed_conn, "versioned event envelope", QueryFilters(), vector=vector)
    retrieved = {item.meeting_id for item in bundle.evidence}
    prompted = set(re.findall(r"meeting_id=(fx-[a-z-]+)", client.calls[0]["user"]))
    assert prompted == retrieved
    all_ids = {row["id"] for row in indexed_conn.execute("SELECT id FROM meetings")}
    assert all_ids - retrieved
    assert not any(meeting_id in client.calls[0]["user"] for meeting_id in all_ids - retrieved)


def test_service_abstains_without_calling_llm(indexed_conn, stub_client, vector):
    client = stub_client([])
    result = QueryService(indexed_conn, client, vector).ask("Was there a database migration deadline?", QueryFilters())
    assert result.status == "not_found"
    assert client.calls == []


def test_invalid_model_citation_becomes_error(indexed_conn, stub_client, vector):
    client = stub_client([AnswerDraft(status="answered", answer="made up", citation_ids=["fake"])])
    result = QueryService(indexed_conn, client, vector).ask("explicit schema_rev", QueryFilters())
    assert result.status == "error"
    assert "citation" in result.error.lower()


@pytest.mark.parametrize("question", ["", "   \n\t "])
def test_empty_question_is_rejected_without_calling_llm(indexed_conn, stub_client, vector, question):
    client = stub_client([])
    result = QueryService(indexed_conn, client, vector).ask(question, QueryFilters())
    assert result.status == "error"
    assert "question" in result.error.lower()
    assert client.calls == []


def test_question_whitespace_is_normalized_before_prompting(indexed_conn, stub_client, vector):
    client = stub_client([AnswerDraft(status="not_found")])
    QueryService(indexed_conn, client, vector).ask("  explicit \n\n  schema_rev  ", QueryFilters())
    assert "Question: explicit schema_rev\n" in client.calls[0]["user"]


def test_provider_failure_is_error_not_not_found(indexed_conn, stub_client, vector):
    client = stub_client([LLMError("Model call failed: Timeout")])
    result = QueryService(indexed_conn, client, vector).ask("explicit schema_rev", QueryFilters())
    assert result.status == "error"
    assert "Timeout" in result.error


def test_llm_is_called_with_low_temperature(indexed_conn, stub_client, vector):
    client = stub_client([AnswerDraft(status="not_found")])
    QueryService(indexed_conn, client, vector).ask("explicit schema_rev", QueryFilters())
    assert client.calls[0]["kind"] == "parse"
    assert client.calls[0]["temperature"] <= 0.2


def test_model_not_found_is_returned_as_not_found(indexed_conn, stub_client, vector):
    client = stub_client([AnswerDraft(status="not_found")])
    result = QueryService(indexed_conn, client, vector).ask("explicit schema_rev", QueryFilters())
    assert result.status == "not_found"
    assert result.citations == ()


def test_answered_result_carries_verified_citations(indexed_conn, stub_client, vector):
    client = stub_client([AnswerDraft(status="answered", answer="Use schema_rev.", citation_ids=["c1"])])
    result = QueryService(indexed_conn, client, vector).ask("explicit schema_rev", QueryFilters())
    assert result.status == "answered"
    assert [c.citation_id for c in result.citations] == ["c1"]
    assert result.citations[0].meeting_id.startswith("fx-")
    assert result.citations[0].quote


def test_not_found_without_filters_suggests_narrowing_filters(indexed_conn, stub_client, vector):
    result = QueryService(indexed_conn, stub_client([]), vector).ask(
        "database migration deadline", QueryFilters()
    )
    assert result.status == "not_found"
    assert set(result.suggested_filters) == {"record_type", "program_phase", "date_from", "date_to"}


def test_not_found_with_filters_suggests_relaxing_the_applied_ones(indexed_conn, stub_client, vector):
    result = QueryService(indexed_conn, stub_client([]), vector).ask(
        "explicit schema_rev", QueryFilters(owner="Nobody Here")
    )
    assert result.status == "not_found"
    assert result.applied_filters == ("owner",)
    assert result.suggested_filters == ("owner",)


def test_structured_records_are_supplied_but_cannot_open_the_gate_alone(indexed_conn, stub_client, vector):
    client = stub_client([])
    result = QueryService(indexed_conn, client, vector).ask(
        "database migration deadline", QueryFilters(record_type="dependencies")
    )
    assert result.status == "not_found"
    assert client.calls == []


def test_structured_record_citations_are_verifiable(indexed_conn, stub_client, vector):
    client = stub_client([AnswerDraft(status="answered", answer="QuartzRelay is open.", citation_ids=["r1"])])
    result = QueryService(indexed_conn, client, vector).ask(
        "unresolved dependency QuartzRelay owner", QueryFilters(record_type="dependencies")
    )
    assert "[r1]" in client.calls[0]["user"]
    assert result.status == "answered"
    assert result.citations[0].record_type == "dependencies"
    assert result.citations[0].record_id


def test_ask_never_mutates_the_database(indexed_conn, stub_client, vector):
    before = indexed_conn.total_changes
    client = stub_client([AnswerDraft(status="answered", answer="x", citation_ids=["c1"])])
    QueryService(indexed_conn, client, vector).ask("explicit schema_rev", QueryFilters())
    assert indexed_conn.total_changes == before


def test_related_meetings_returns_directed_links_for_one_meeting(indexed_conn, stub_client, vector):
    links = QueryService(indexed_conn, stub_client([]), vector).related_meetings("fx-kickoff")
    assert links
    assert all("fx-kickoff" in (link.source_meeting_id, link.target_meeting_id) for link in links)
    assert links == sorted(links, key=lambda x: (x.source_meeting_id, x.target_meeting_id, x.link_type))


def test_related_meetings_for_unknown_meeting_is_empty(indexed_conn, stub_client, vector):
    assert QueryService(indexed_conn, stub_client([]), vector).related_meetings("missing") == []


def test_golden_queries_through_the_service(golden_query_service):
    cases = json.loads(GOLDEN_QUERY_PATH.read_text())
    failures = []
    for case in cases:
        service = golden_query_service(case)
        result = service.ask(case["question"], QueryFilters(**case["filters"]))
        expected_status = "answered" if case["answerable"] else "not_found"
        cited_meetings = {c.meeting_id for c in result.citations}
        quotes = " ".join(c.quote for c in result.citations).casefold()
        ok = (
            result.status == expected_status
            and set(result.applied_filters) == set(case["filters_expected"])
            and (not case["answerable"] or (
                set(case["expected_meetings"]) & cited_meetings
                and any(p.casefold() in quotes for p in case["expected_phrases"])
            ))
        )
        if case["answerable"] is False:
            ok = ok and service.llm.calls == []
        if not ok:
            failures.append((case["question"], result.status, result.error, sorted(cited_meetings)))
    assert failures == []


def test_filter_options_list_the_values_each_filter_can_take(indexed_conn, stub_client, vector):
    options = QueryService(indexed_conn, stub_client([]), vector).filter_options()
    assert ("fx-kickoff", "2026-09-01 · LatticeBridge kickoff and vocabulary") in options.meetings
    assert "Sia Moss" in options.participants
    assert "Sia Moss" in options.owners
    assert "high" in options.severities
    assert "rollout_readiness" in options.program_phases
    assert options.record_types == ("action_items", "decisions", "risks", "dependencies", "learnings")
    assert list(options.participants) == sorted(options.participants)


def test_result_exposes_the_evidence_the_model_saw(indexed_conn, stub_client, vector):
    client = stub_client([AnswerDraft(status="answered", answer="x", citation_ids=["c1"])])
    result = QueryService(indexed_conn, client, vector).ask("explicit schema_rev", QueryFilters())
    assert result.evidence
    assert all(f"[{item.citation_id}]" in client.calls[0]["user"] for item in result.evidence)


def test_result_before_retrieval_has_no_evidence(indexed_conn, stub_client, vector):
    result = QueryService(indexed_conn, stub_client([]), vector).ask("database migration deadline", QueryFilters())
    assert result.evidence == ()
