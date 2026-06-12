import streamlit as st

from messages import render_chat_history


def render_chat() -> None:
    render_chat_history(
        st.session_state.messages,
        st.session_state.session_id,
    )
