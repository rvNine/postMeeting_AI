"""Streamlit entrypoint. Routing and session state only — no logic lives here."""
import streamlit as st

import config
from query.vector import database_signature, load_configured_vector_adapter
from storage import db
from storage.meeting_knowledge import index_unindexed_meetings
from ui import export_view, input_view, query_view, review_view
from ui.state import Stage, clear_meeting_state, clear_query_state

st.set_page_config(page_title="Meeting Follow-up Agent", page_icon="📝", layout="wide")


@st.cache_resource
def get_conn():
    conn = db.connect(config.DB_PATH)
    db.init_db(conn)
    # Meetings saved before Ask meetings existed (or whose indexing failed) have
    # no chunks and would silently never be found.
    index_unindexed_meetings(conn)
    return conn


@st.cache_resource
def get_vector_adapter(_conn, chunk_signature: str):
    """Cache the selected offline adapter until SQLite chunk content changes."""
    del chunk_signature  # Streamlit's cache key owns invalidation for this resource.
    return load_configured_vector_adapter(_conn)


def main():
    st.title("Meeting Follow-up Agent")

    if not config.get_api_key():
        st.error(
            "**OPENAI_API_KEY is not set.** Copy `.env.example` to `.env`, add your "
            "key, and restart the app."
        )

    st.session_state.setdefault("stage", Stage.INPUT)
    st.session_state.setdefault("meeting_id", None)

    conn = get_conn()
    vector = get_vector_adapter(conn, database_signature(conn))

    with st.sidebar:
        if st.button("🔎 Ask meetings"):
            st.session_state["stage"] = Stage.QUERY
            st.session_state["meeting_id"] = None
            clear_meeting_state(st.session_state)
            st.rerun()
        st.header("Past meetings")
        if st.button("＋ New meeting"):
            st.session_state["stage"] = Stage.INPUT
            st.session_state["meeting_id"] = None
            clear_meeting_state(st.session_state)
            clear_query_state(st.session_state)
            st.rerun()
        for meeting in db.list_meetings(conn):
            label = f"{meeting['meeting_date']} · {meeting['title']} ({meeting['status']})"
            if st.button(label, key=f"m_{meeting['id']}"):
                st.session_state["meeting_id"] = meeting["id"]
                st.session_state["stage"] = Stage.REVIEW
                clear_meeting_state(st.session_state)
                clear_query_state(st.session_state)
                st.rerun()

    stage = st.session_state["stage"]
    if stage == Stage.INPUT:
        input_view.render(conn)
    elif stage == Stage.REVIEW:
        review_view.render(conn)
    elif stage == Stage.QUERY:
        query_view.render(conn, vector)
    else:
        export_view.render(conn)


if __name__ == "__main__":
    main()
