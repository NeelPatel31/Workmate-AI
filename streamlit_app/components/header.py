import streamlit as st

from state import refresh_session


def render_header() -> None:
    st.title("Workmate AI")

    col_id, col_refresh, col_files = st.columns([4, 1, 1])
    with col_id:
        st.markdown(f"**Session:** `{st.session_state.session_id}`")
    with col_refresh:
        if st.button("🔄 Refresh", use_container_width=True):
            refresh_session()
    with col_files:
        label = "📁 Files ✕" if st.session_state.get("show_files_panel") else "📁 Files"
        if st.button(label, use_container_width=True):
            st.session_state.show_files_panel = not st.session_state.show_files_panel
            st.rerun()
