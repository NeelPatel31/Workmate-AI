import streamlit as st


def _render_file_entry(file_info: dict) -> None:
    """Render a single file as a read-only info card (no download)."""
    file_name = file_info.get("file_name", "Unknown file")
    file_path = file_info.get("file_path", "")
    st.markdown(
        f"""
        <div style="
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 6px;
            padding: 8px 12px;
            margin-bottom: 6px;
        ">
            <div style="font-weight: 600; font-size: 0.88rem;">📄 {file_name}</div>
            <div style="font-size: 0.75rem; color: #888; word-break: break-all; margin-top: 2px;">{file_path}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_file_panel() -> None:
    st.subheader("Session Files")

    st.markdown("**📤 Uploaded by you**")
    uploads = st.session_state.get("session_uploaded_files", [])
    if uploads:
        for file_info in uploads:
            _render_file_entry(file_info)
    else:
        st.caption("No uploaded files yet.")

    st.divider()

    st.markdown("**📥 Shared by agent**")
    agent_files = st.session_state.get("session_agent_files", [])
    if agent_files:
        for file_info in agent_files:
            _render_file_entry(file_info)
    else:
        st.caption("No shared files yet.")
