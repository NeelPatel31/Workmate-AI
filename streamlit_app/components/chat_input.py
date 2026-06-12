import hashlib

import streamlit as st

import api_client
from state import queue_stream_turn


def _file_key(file_name: str, file_bytes: bytes) -> str:
    digest = hashlib.md5(file_bytes).hexdigest()
    return f"{file_name}:{digest}"


def _handle_file_upload(uploaded_files: list) -> None:
    # Detect newly added files and upload them
    for uploaded in uploaded_files:
        file_bytes = uploaded.getvalue()
        key = _file_key(uploaded.name, file_bytes)
        if key in st.session_state.uploaded_file_keys:
            continue

        try:
            result = api_client.upload_file(
                st.session_state.session_id,
                uploaded.name,
                file_bytes,
            )
        except api_client.ApiError as exc:
            st.error(f"Failed to upload {uploaded.name}: {exc}")
            continue

        file_entry = {
            "file_name": result["file_name"],
            "file_path": result["file_path"],
            "container_path": result.get("container_path", ""),
            "_key": key,
        }
        st.session_state.pending_uploads.append(file_entry)
        st.session_state.session_uploaded_files.append(file_entry)
        st.session_state.uploaded_file_keys.add(key)


def _handle_file_removals(uploaded_files: list) -> None:
    """Detect files removed from the uploader widget and delete them from local + container."""
    if not st.session_state.pending_uploads:
        return

    current_keys = {
        _file_key(f.name, f.getvalue()) for f in uploaded_files
    }

    remaining_pending: list[dict] = []
    for entry in st.session_state.pending_uploads:
        entry_key = entry.get("_key", "")
        if entry_key and entry_key not in current_keys:
            # File was removed by the user — delete it
            try:
                api_client.delete_upload(
                    st.session_state.session_id,
                    entry["file_name"],
                )
            except api_client.ApiError as exc:
                st.warning(f"Could not delete {entry['file_name']} from server: {exc}")

            # Remove from session_uploaded_files too
            st.session_state.session_uploaded_files = [
                f for f in st.session_state.session_uploaded_files
                if f.get("file_name") != entry["file_name"]
            ]
            # Remove from uploaded_file_keys so re-uploading same file works
            st.session_state.uploaded_file_keys.discard(entry_key)
        else:
            remaining_pending.append(entry)

    st.session_state.pending_uploads = remaining_pending


def _handle_send(user_query: str) -> None:
    query = user_query.strip()
    pending = st.session_state.pending_uploads

    if not query and not pending:
        st.warning("Enter a message or upload at least one file before sending.")
        return

    uploaded_for_chat = [
        {"file_name": f["file_name"], "file_path": f["container_path"]} for f in pending
    ]

    queue_stream_turn(user_query=query, uploaded_files=uploaded_for_chat)
    st.rerun()


def render_chat_input() -> None:
    uploaded = st.file_uploader(
        "Attach files (optional)",
        accept_multiple_files=True,
        key=f"file_uploader_{st.session_state.file_uploader_key}",
    )

    # Always check for removals first, then handle new uploads
    _handle_file_removals(uploaded or [])
    if uploaded:
        _handle_file_upload(uploaded)

    if st.session_state.pending_uploads:
        names = [f["file_name"] for f in st.session_state.pending_uploads]
        st.caption("📎 Ready to send: " + ", ".join(names))

    # st.chat_input auto-clears after submission and pins to the bottom of the page
    user_query = st.chat_input("Type your message here…")
    if user_query is not None:
        _handle_send(user_query)

