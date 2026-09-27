"""Notes entry and sample picker. Widgets wired to ui.state helpers."""
import streamlit as st

import config
from agent.llm_client import LLMError, OpenAILLMClient
from agent.loop import run_agent_loop
from agent.prompts import PROMPT_VERSION
from fixtures import loader
from storage import db
from storage.meeting_knowledge import rebuild_meeting_index
from ui.context_builder import build_context
from ui.state import Stage, can_analyze, notes_warning, truncate_notes
from ui.upload_helpers import UploadError, decode_uploaded_meeting, title_from_filename


def render(conn):
    st.subheader("1. Add your meeting notes")

    samples = loader.list_samples()
    choice = st.selectbox("Or load a sample meeting",
                          ["(none)"] + [s["title"] for s in samples])
    prefill = ""
    if choice != "(none)":
        prefill = next(s["notes"] for s in samples if s["title"] == choice)

    uploaded = st.file_uploader("Upload notes (.txt or .md)", type=["txt", "md"])
    uploaded_notes = ""
    uploaded_title = ""
    if uploaded is not None:
        try:
            uploaded_notes = decode_uploaded_meeting(uploaded.name, uploaded.getvalue())
            uploaded_title = title_from_filename(uploaded.name)
            st.caption(f"Loaded {uploaded.name}; you can edit the text below before analyzing.")
        except UploadError as exc:
            st.error(str(exc))

    col1, col2 = st.columns(2)
    default_title = uploaded_title or (choice if choice != "(none)" else "")
    title = col1.text_input("Meeting title", value=default_title)
    meeting_date = col2.date_input("Meeting date")

    notes = st.text_area("Meeting notes", value=uploaded_notes or prefill, height=400)

    warning = notes_warning(notes)
    if warning:
        st.warning(warning)

    if not can_analyze(notes):
        st.caption("Enter at least 50 characters of notes to continue.")

    if st.button("Analyze", type="primary", disabled=not can_analyze(notes)):
        _analyze(conn, title or "Untitled meeting", str(meeting_date), notes)


def _analyze(conn, title: str, meeting_date: str, notes: str):
    try:
        client = OpenAILLMClient()
    except LLMError as exc:
        st.error(str(exc))
        return

    # Only the copy sent to the model is truncated. `notes` — the manager's
    # original paste, line breaks and all — is what gets persisted: truncate_notes
    # joins the first 10,000 words with single spaces, so storing its output would
    # permanently lose both the tail and every line break of an over-long paste.
    model_notes = truncate_notes(notes)
    # Context is assembled before the meeting row exists, so nothing can match
    # this meeting; the id is a placeholder the queries simply will not find.
    context = build_context(conn, exclude_meeting_id="")
    try:
        with st.status("Working…", expanded=True) as status:
            status.write("Extracting decisions and action items…")
            outcome = run_agent_loop(model_notes, client, context=context)
            if outcome.passes > 1:
                status.write("Re-read the notes to resolve what it could…")
            status.update(label="Done", state="complete")
    except LLMError as exc:
        st.error(f"The model call failed: {exc}")
        st.info("Your notes are still here. Try Analyze again.")
        return

    meeting_id = db.save_meeting(conn, title=title, meeting_date=meeting_date,
                                 raw_notes=notes)
    try:
        db.save_extraction(conn, meeting_id, outcome.extraction, outcome.review,
                           model=config.DEFAULT_MODEL, prompt_version=PROMPT_VERSION,
                           processing_pass=outcome.passes,
                           tokens_used=outcome.tokens, latency_ms=outcome.latency_ms,
                           raw_response=outcome.raw)
    except Exception as exc:
        # save_meeting has already committed, so the meeting row outlives a failed
        # extraction write. An empty meeting is worse than none: it appears in the
        # sidebar and opens on "No blocking gaps. You can draft the follow-up." —
        # an enabled Draft button over an extraction that was never stored. Undo it.
        try:
            db.delete_meeting(conn, meeting_id)
        except Exception as cleanup_exc:
            # This is the recovery path for a failure — the worst place for a
            # second one. Surface a clean error and keep the user's notes rather
            # than let a cleanup failure raise an unhandled traceback on top of
            # the original save_extraction failure.
            st.error(f"Could not save the analysis: {type(exc).__name__}: {exc}")
            st.error(f"Also failed to clean up the orphan meeting: "
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}")
            st.info("Your notes are still here. Try Analyze again.")
            return
        st.error(f"Could not save the analysis: {type(exc).__name__}: {exc}")
        st.info("Your notes are still here. Try Analyze again.")
        return

    # The analysis is durable now. Indexing only makes it searchable in Ask
    # meetings, so a failure here must never undo the save; the app re-indexes
    # meetings without chunks the next time it starts.
    try:
        rebuild_meeting_index(conn, meeting_id)
    except Exception as exc:
        st.warning(f"Saved, but not yet searchable in Ask meetings "
                   f"({type(exc).__name__}). It will be indexed when the app restarts.")

    st.session_state["loop_notes"] = outcome.notes_for_manager
    st.session_state["corrected_item_ids"] = {
        f"{meeting_id}:item:{item_id}" for item_id in outcome.corrected_item_ids
    }
    st.session_state["owner_hints"] = context.owner_hints
    # Stored beside the hints, and cleared with them on a meeting switch. The
    # model was given these; the manager should see the same thing.
    st.session_state["prior_commitments"] = context.prior_commitments
    st.session_state["meeting_id"] = meeting_id
    st.session_state["stage"] = Stage.REVIEW
    st.rerun()
