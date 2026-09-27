"""Ask meetings: read-only questions over meeting notes, answered with citations.

Everything goes through QueryService. This view never reads SQL, never calls
retrieval or verification directly, and never changes a meeting.
"""
import streamlit as st

from agent.llm_client import LLMError, OpenAILLMClient
from query.models import QueryResult
from query.service import QueryService
from ui.state import build_query_filters, open_query_citation

_FILTER_LABELS = {
    "date_from": "start date", "date_to": "end date", "meeting_id": "meeting",
    "participant": "participant", "owner": "owner", "record_type": "record type",
    "severity": "severity", "program_phase": "program phase",
}


def _any(value) -> str:
    return "Any" if value is None else str(value)


def render(conn, vector, *, llm=None):
    """`llm` is injectable for tests; by default the client is built only on Ask."""
    st.subheader("Ask meetings")
    st.caption("Answers come only from the meeting notes, and every answer cites them. "
               "Nothing here changes a meeting.")

    options = QueryService(conn, llm, vector).filter_options()
    meeting_labels = dict(options.meetings)

    question = st.text_input("Question", key="query_question_input",
                             placeholder="e.g. Which risks were raised for the rollout?")
    with st.expander("Filters"):
        date_range = st.date_input("Meeting dates", value=(), key="query_dates")
        col1, col2 = st.columns(2)
        meeting_id = col1.selectbox("Meeting", [None, *meeting_labels], key="query_meeting",
                                    format_func=lambda v: _any(v and meeting_labels[v]))
        program_phase = col2.selectbox("Program phase", [None, *options.program_phases],
                                       key="query_phase", format_func=_any)
        participant = col1.selectbox("Participant", [None, *options.participants],
                                     key="query_participant", format_func=_any)
        owner = col2.selectbox("Owner", [None, *options.owners], key="query_owner",
                               format_func=_any)
        record_type = col1.selectbox("Record type", [None, *options.record_types],
                                     key="query_record_type", format_func=_any)
        severity = col2.selectbox("Risk severity", [None, *options.severities],
                                  key="query_severity", format_func=_any)

    if st.button("Ask", type="primary", key="query_ask", disabled=not question.strip()):
        filters = build_query_filters(
            date_range=date_range, meeting_id=meeting_id, participant=participant,
            owner=owner, record_type=record_type, severity=severity,
            program_phase=program_phase,
        )
        st.session_state["query_question"] = question
        st.session_state["query_filters"] = filters
        st.session_state.pop("query_error", None)
        try:
            client = llm or OpenAILLMClient()
        except LLMError as exc:
            st.session_state["query_error"] = str(exc)
            st.session_state.pop("query_result", None)
        else:
            with st.spinner("Searching the meetings…"):
                st.session_state["query_result"] = QueryService(conn, client, vector).ask(
                    question, filters)

    if st.session_state.get("query_error"):
        st.error(st.session_state["query_error"])
    result = st.session_state.get("query_result")
    if result is not None:
        _render_result(result)


def _render_result(result: QueryResult) -> None:
    if result.status == "error":
        st.error(result.error)
    elif result.status == "not_found":
        suggestions = ", ".join(_FILTER_LABELS[f] for f in result.suggested_filters)
        advice = ("Try relaxing these filters: " if result.applied_filters
                  else "Try narrowing with: ")
        st.info("No evidence in the meetings answers this question."
                + (f" {advice}{suggestions}." if suggestions else ""))
    else:
        st.markdown("### Answer")
        st.markdown(result.answer)
        st.markdown("#### Sources")
        for citation in result.citations:
            with st.container(border=True):
                relation = (f" · related meeting ({citation.relationship_label})"
                            if citation.relationship_label else "")
                st.markdown(f"**[{citation.citation_id}]** {citation.title} · "
                            f"{citation.meeting_date}{relation}")
                if citation.record_type:
                    st.caption(f"Record: {citation.record_type} · {citation.record_id}")
                st.caption(f"From the notes: “{citation.quote}”")
                if st.button("Open meeting review", key=f"query_open_{citation.citation_id}"):
                    open_query_citation(st.session_state, citation.meeting_id)
                    st.rerun()
    if result.evidence:
        with st.expander(f"Retrieved evidence ({len(result.evidence)})", expanded=False):
            for item in result.evidence:
                st.markdown(f"**[{item.citation_id}]** {item.title} · {item.meeting_date}")
                st.caption(item.text_fragment)
