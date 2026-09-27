"""Read-only question answering over retrieved, verified meeting evidence."""
from dataclasses import replace
import sqlite3

from agent.llm_client import LLMClient, LLMError
from query.models import AnswerDraft, FilterOptions, QueryFilters, QueryResult
from query.prompts import build_answer_prompt
from query.retrieval import retrieve
from query.vector import VectorAdapter
from query.verification import CitationVerificationError, verify_answer
from storage.meeting_knowledge import MeetingLink, list_filter_options, list_meeting_links


ANSWER_TEMPERATURE = 0.1
# Suggested when an unfiltered question finds nothing: fields that narrow scope.
_NARROWING_FILTERS = ("record_type", "program_phase", "date_from", "date_to")


class QueryService:
    """The only boundary UI callers use to ask questions about meetings."""

    def __init__(self, conn: sqlite3.Connection, llm: LLMClient, vector: VectorAdapter):
        self.conn = conn
        self.llm = llm
        self.vector = vector

    def ask(self, question: str, filters: QueryFilters) -> QueryResult:
        normalized = " ".join(question.split())
        if not normalized:
            return QueryResult("error", None, (), error="Enter a question to search the meetings.")
        bundle = retrieve(self.conn, normalized, filters, vector=self.vector)
        applied = bundle.trace.applied_filter_fields
        not_found = QueryResult(
            "not_found", None, (), applied_filters=applied,
            suggested_filters=applied or _NARROWING_FILTERS,
        )
        # Only chunk evidence that met the retrieval threshold opens the gate;
        # structured records ride along but never justify an LLM call alone.
        if not bundle.evidence:
            return not_found
        evidence = [*bundle.evidence, *bundle.structured_matches]
        shown = tuple(evidence)
        system, user = build_answer_prompt(normalized, evidence)
        try:
            draft = self.llm.parse(system, user, AnswerDraft, temperature=ANSWER_TEMPERATURE).value
            if not isinstance(draft, AnswerDraft):
                raise LLMError("Model returned no parseable answer.")
            verified = verify_answer(draft, evidence, self.conn)
        except LLMError as exc:
            return QueryResult("error", None, (), error=str(exc), applied_filters=applied,
                               evidence=shown)
        except CitationVerificationError as exc:
            return QueryResult(
                "error", None, (), applied_filters=applied, evidence=shown,
                error=f"Answer rejected because a citation failed verification: {exc}",
            )
        if verified.status == "not_found":
            return replace(not_found, evidence=shown)
        return QueryResult("answered", verified.answer, verified.citations,
                           applied_filters=applied, evidence=shown)

    def related_meetings(self, meeting_id: str) -> list[MeetingLink]:
        return list_meeting_links(self.conn, meeting_id)

    def filter_options(self) -> FilterOptions:
        options = list_filter_options(self.conn)
        return FilterOptions(
            meetings=tuple(options["meetings"]),
            participants=tuple(options["participants"]),
            owners=tuple(options["owners"]),
            severities=tuple(options["severities"]),
            program_phases=tuple(options["program_phases"]),
        )
