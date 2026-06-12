from __future__ import annotations

import uuid

import streamlit as st

import api_client


def init_session_state() -> None:
    defaults = {
        "session_id": str(uuid.uuid4()),
        "messages": [],
        "pending_uploads": [],
        "pending_stream": None,
        "show_files_panel": False,
        "uploaded_file_keys": set(),
        "file_uploader_key": 0,
        "session_uploaded_files": [],  # Persistent list of all uploaded files this session
        "session_agent_files": [],     # Persistent list of all agent-shared files this session
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def refresh_session() -> None:
    try:
        api_client.refresh_session(st.session_state.session_id)
    except api_client.ApiError as exc:
        st.error(f"Failed to refresh session: {exc}")
        return

    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.pending_uploads = []
    st.session_state.pending_stream = None
    st.session_state.uploaded_file_keys = set()
    st.session_state.file_uploader_key = 0
    st.session_state.show_files_panel = False
    st.session_state.session_uploaded_files = []
    st.session_state.session_agent_files = []
    st.rerun()


def queue_stream_turn(
    user_query: str,
    uploaded_files: list[dict[str, str]],
) -> None:
    turn_id = str(uuid.uuid4())
    st.session_state.messages.append(
        {
            "type": "human",
            "content": user_query,
            "attached_files": [f["file_name"] for f in uploaded_files],
        }
    )
    st.session_state.pending_stream = {
        "user_query": user_query,
        "uploaded_files": uploaded_files,
        "turn_id": turn_id,
    }
    st.session_state.pending_uploads = []
    st.session_state.uploaded_file_keys = set()
    # Bump the key so Streamlit mounts a fresh, empty file uploader widget
    st.session_state.file_uploader_key = st.session_state.get("file_uploader_key", 0) + 1
