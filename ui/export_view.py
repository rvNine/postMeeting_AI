"""Draft generation, approval, export, and the AI-vs-human diff (PRD F15)."""
import streamlit as st

from agent.gaps import GateBlockedError
from agent.llm_client import LLMError, OpenAILLMClient
from agent.pipeline import run_draft
from agent.schemas import ActionItem, Decision, Gap
from storage import db
from ui.markdown_export import build_export, export_filename
from ui.state import Stage, clear_draft


def render(conn):
    meeting_id = st.session_state["meeting_id"]
    meeting = next(m for m in db.list_meetings(conn) if m["id"] == meeting_id)
    items = db.load_action_items(conn, meeting_id)
    decisions = db.load_decisions(conn, meeting_id)

    st.subheader("3. Approve and send")

    # Generate at most once per attempt. An LLMError never sets "draft", so
    # without the error latch every Streamlit rerun re-issued a billable call.
    if "draft" not in st.session_state and "draft_error" not in st.session_state:
        _generate_draft(conn, meeting, items, decisions)

    if "draft" not in st.session_state:
        # No draft was produced. Approve and Download must not render: approving
        # would save an empty draft as the approved message, and build_export
        # would hand the manager a finished document assembled from the very DB
        # rows the gate just refused to draft from.
        st.error(st.session_state.get("draft_error", "No draft was produced."))
        col1, col2 = st.columns([1, 1])
        if col1.button("Try again"):
            st.session_state.pop("draft_error", None)
            st.rerun()
        if col2.button("← Back to review"):
            clear_draft(st.session_state)
            st.session_state["stage"] = Stage.REVIEW
            st.rerun()
        return

    draft = st.session_state["draft"]
    final = st.text_area("Follow-up message (edit before approving)",
                         value=draft, height=350)

    col1, col2 = st.columns([1, 1])
    if col1.button("Approve", type="primary"):
        db.save_approval(conn, meeting_id, draft_text=draft, final_text=final)
        st.success("Approved and saved.")

    col2.download_button(
        "Download Markdown",
        data=build_export(meeting, decisions, items, final),
        file_name=export_filename(meeting),
        mime="text/markdown",
    )

    _render_diff(conn, meeting_id)

    if st.button("← Back to review"):
        clear_draft(st.session_state)
        st.session_state["stage"] = Stage.REVIEW
        st.rerun()


def _generate_draft(conn, meeting, items, decisions):
    # `items` here is db.load_action_items(conn, meeting_id) — the same loader
    # the review view gates draft_blocked() on. run_draft's own gate rejects
    # any item with a blank owner/deadline independently of gaps, so sourcing
    # this list any other way (or filtering it differently) would let the
    # button and the gate diverge.
    gaps = [Gap(**{k: v for k, v in row.items()
                   if k in {"id", "type", "severity", "target_id",
                            "explanation", "suggested_question"}})
            for row in db.load_gaps(conn, meeting["id"])]
    resolved = db.resolved_gap_ids(conn, meeting["id"])
    try:
        client = OpenAILLMClient()
        with st.spinner("Drafting the follow-up…"):
            outcome = run_draft(
                meeting_title=meeting["title"],
                decisions=[Decision(id=d["id"], decision=d["decision"],
                                    rationale=d["rationale"],
                                    source_quote=d["source_quote"] or "",
                                    confidence=d["confidence"] or 0.0)
                           for d in decisions],
                action_items=[ActionItem(id=i["id"], task=i["task"], owner=i["owner"],
                                         deadline=i["deadline"],
                                         source_quote=i["source_quote"] or "",
                                         confidence=i["confidence"] or 0.0)
                              for i in items],
                gaps=gaps, resolved_ids=resolved, client=client)
        st.session_state["draft"] = outcome.text
        st.session_state.pop("draft_error", None)
    except GateBlockedError as exc:
        # Recorded, not rendered here: render() decides what to show, and the
        # presence of this key is what suppresses Approve/Download and stops the
        # next rerun from re-issuing the call.
        st.session_state["draft_error"] = (
            f"{exc}\n\nGo back to review and resolve the flagged items.")
    except LLMError as exc:
        st.session_state["draft_error"] = f"Drafting failed: {exc}"


def _render_diff(conn, meeting_id):
    edits = db.human_edits(conn, meeting_id)
    with st.expander(f"What you changed from the agent's output ({len(edits)})"):
        if not edits:
            st.write("You accepted the agent's output unchanged.")
            return
        # Technical edits carry a "kind"; action-item edits keep their original
        # shape without one.
        st.table([{"Kind": e.get("kind", "action item"),
                   "Item": e["item_id"], "Field": e["field"],
                   "Agent said": e["ai_value"] or "— (nothing)",
                   "You set": e["human_value"]} for e in edits])
