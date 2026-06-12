from __future__ import annotations

import streamlit as st

import api_client
from messages import (
    render_ai_text_message,
    render_tool_call_message,
    render_tool_result_message,
    render_shared_files_message,
)


def execute_pending_stream() -> None:
    pending = st.session_state.pending_stream
    if not pending:
        return

    session_id = st.session_state.session_id

    # ------------------------------------------------------------------
    # 1. Consume the entire SSE stream without touching any Streamlit
    #    widgets. This prevents mid-stream widget interactions from
    #    triggering a rerun (which would disconnect the HTTP connection
    #    and leave the LangGraph checkpoint with an unanswered tool call).
    # ------------------------------------------------------------------
    collected: list[dict] = []   # ordered list of events to render
    error_text: str | None = None

    with st.chat_message("assistant"):
        with st.status("Thinking…", expanded=False) as status:
            try:
                for event in api_client.stream_chat(
                    session_id=session_id,
                    user_query=pending["user_query"],
                    uploaded_files=pending["uploaded_files"],
                ):
                    if "token" in event:
                        # Accumulate text tokens into the last text chunk
                        if collected and collected[-1].get("_type") == "_text_buf":
                            collected[-1]["content"] += event["token"]
                        else:
                            collected.append({"_type": "_text_buf", "content": event["token"]})

                    elif event.get("end_message"):
                        # Flush text chunk — token may also carry a last fragment
                        extra = event.get("token", "")
                        if collected and collected[-1].get("_type") == "_text_buf":
                            collected[-1]["content"] += extra
                        elif extra:
                            collected.append({"_type": "_text_buf", "content": extra})

                    elif "message" in event:
                        msg = event["message"]
                        # If there's a buffered text chunk before a tool call, seal it first
                        if collected and collected[-1].get("_type") == "_text_buf":
                            buf = collected[-1]
                            buf["_type"] = "ai"
                            buf["tool_calls"] = []
                        collected.append(msg)

                    elif "shared_files" in event:
                        collected.append({
                            "_type": "shared_files",
                            "files": event["shared_files"],
                            "turn_id": pending["turn_id"],
                        })

                    elif "error" in event:
                        error_text = event["error"]
                        break

                    elif event.get("end_of_stream"):
                        break

            except api_client.ApiError as exc:
                error_text = str(exc)

            status.update(label="Done", state="complete", expanded=False)

    # ------------------------------------------------------------------
    # 2. Now that the stream is fully consumed, render everything in order.
    #    All widgets created here are stable — no more streaming happening.
    # ------------------------------------------------------------------
    agent_messages: list[dict] = []    # messages to persist to session state
    shared_files_all: list[dict] = []  # flat list of files for session state

    if error_text:
        with st.chat_message("assistant"):
            st.error(f"Stream error: {error_text}")

    for item in collected:
        item_type = item.get("_type") or item.get("type")

        if item_type == "_text_buf":
            # Plain AI text response
            content = item.get("content", "").strip()
            if content:
                msg = {"type": "ai", "content": content}
                with st.chat_message("assistant"):
                    render_ai_text_message(msg)
                agent_messages.append(msg)

        elif item_type == "ai":
            # AI message with tool_calls
            if item.get("tool_calls"):
                with st.chat_message("assistant"):
                    render_tool_call_message(item)
                agent_messages.append({
                    "type": "ai",
                    "content": item.get("content", ""),
                    "tool_calls": item.get("tool_calls", []),
                })
            else:
                content = item.get("content", "").strip()
                if content:
                    with st.chat_message("assistant"):
                        render_ai_text_message(item)
                    agent_messages.append({"type": "ai", "content": content})

        elif item_type == "tool":
            with st.chat_message("assistant"):
                render_tool_result_message(item)
            agent_messages.append({
                "type": "tool",
                "content": item.get("content", ""),
                "tool_call_id": item.get("tool_call_id", ""),
            })

        elif item_type == "shared_files":
            files = item.get("files", [])
            if files:
                shared_files_all.extend(files)
                st.session_state.session_agent_files.extend(files)
                files_msg = {
                    "type": "shared_files",
                    "files": files,
                    "turn_id": item.get("turn_id", ""),
                }
                with st.chat_message("assistant"):
                    render_shared_files_message(files_msg, session_id)
                agent_messages.append(files_msg)

    # ------------------------------------------------------------------
    # 3. Persist and rerun
    # ------------------------------------------------------------------
    st.session_state.messages.extend(agent_messages)
    st.session_state.pending_stream = None
    st.rerun()
