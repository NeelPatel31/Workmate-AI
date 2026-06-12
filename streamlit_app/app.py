"""Workmate AI Streamlit chat app.

Run with:
    uv run streamlit run streamlit_app/app.py

Start the API (separate terminal):
    uv run python main.py
"""

import streamlit as st

from components.chat import render_chat
from components.chat_input import render_chat_input
from components.file_panel import render_file_panel
from components.header import render_header
from state import init_session_state
from streaming import execute_pending_stream


def main() -> None:
    st.set_page_config(
        page_title="Workmate AI",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    init_session_state()

    render_header()

    if st.session_state.show_files_panel:
        chat_col, panel_col = st.columns([3, 1])
        with chat_col:
            render_chat()
            if st.session_state.pending_stream:
                execute_pending_stream()
            render_chat_input()
        with panel_col:
            render_file_panel()
    else:
        render_chat()
        if st.session_state.pending_stream:
            execute_pending_stream()
        render_chat_input()



if __name__ == "__main__":
    main()
