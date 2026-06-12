from __future__ import annotations

import streamlit as st


# ---------------------------------------------------------------------------
# Individual renderers
# ---------------------------------------------------------------------------

def render_human_message(message: dict) -> None:
    content = message.get("content", "").strip()
    attached = message.get("attached_files", [])
    if content:
        st.markdown(content)
    if attached:
        st.caption("Attached files: " + ", ".join(attached))


def render_ai_text_message(message: dict) -> None:
    """Render a plain AI text message (no tool calls)."""
    content = message.get("content", "").strip()
    if content:
        st.markdown(content)


def render_tool_call_message(message: dict) -> None:
    """Render an AI message that contains tool calls as a JSON expander."""
    tool_calls = message.get("tool_calls", [])
    for tc in tool_calls:
        label = f"🔧 Tool call: `{tc.get('name', 'unknown')}`"
        with st.expander(label, expanded=False):
            st.json({
                "id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            })


def render_tool_result_message(message: dict) -> None:
    """Render a tool result message as a JSON expander."""
    tool_call_id = message.get("tool_call_id", "")
    content = message.get("content", "")
    label = f"📤 Tool result: `{tool_call_id}`"
    with st.expander(label, expanded=False):
        # Try to parse as JSON for prettier display; fall back to plain text
        try:
            import json as _json
            parsed = _json.loads(content)
            st.json(parsed)
        except Exception:
            st.text(content)


def render_shared_files_message(message: dict, session_id: str) -> None:
    """Render agent-shared files as a JSON expander."""
    files = message.get("files", [])
    if not files:
        return
    with st.expander(f"📁 Agent shared {len(files)} file(s)", expanded=True):
        for file_info in files:
            st.json(file_info)


# ---------------------------------------------------------------------------
# Top-level message dispatcher
# ---------------------------------------------------------------------------

def render_message(message: dict, session_id: str) -> None:
    """Render a single stored message using native st.chat_message blocks."""
    msg_type = message.get("type")

    if msg_type == "human":
        with st.chat_message("user"):
            render_human_message(message)

    elif msg_type == "ai":
        if message.get("tool_calls"):
            # Tool-call AI messages: render as assistant expander (always visible)
            with st.chat_message("assistant"):
                render_tool_call_message(message)
        else:
            content = message.get("content", "").strip()
            if content:
                with st.chat_message("assistant"):
                    render_ai_text_message(message)

    elif msg_type == "tool":
        with st.chat_message("assistant"):
            render_tool_result_message(message)

    elif msg_type == "shared_files":
        with st.chat_message("assistant"):
            render_shared_files_message(message, session_id)


def render_chat_history(messages: list[dict], session_id: str) -> None:
    """Render the full stored chat history in sequence."""
    for message in messages:
        render_message(message, session_id)
