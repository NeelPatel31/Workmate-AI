from __future__ import annotations

from typing import Generator
import json
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from ...utils import logger
from ...agent_registry import workmate_agent

def build_agent_query(user_query: str, uploaded_files: list[dict]) -> str:
    main_query = ""
    if uploaded_files:
        main_query += "<uploaded_files>\n"
        for file in uploaded_files:
            main_query += "<file>\n"
            main_query += f"  <name>{file['file_name']}</name>\n"
            main_query += f"  <path>{file['file_path']}</path>\n"
            main_query += "</file>\n"
        main_query += "</uploaded_files>\n"
    main_query += f"<user_query>\n{user_query}\n</user_query>\n"
    return main_query.strip()


def serialize_message(msg: BaseMessage) -> dict:
    if isinstance(msg, HumanMessage):
        return {"type": "human", "content": msg.content or ""}
    if isinstance(msg, AIMessage):
        result: dict = {"type": "ai", "content": msg.content or ""}
        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                }
                for tc in msg.tool_calls
            ]
        return result
    if isinstance(msg, ToolMessage):
        return {
            "type": "tool",
            "content": msg.content or "",
            "tool_call_id": msg.tool_call_id or "",
        }
    return {"type": "unknown", "content": str(msg.content)}


def _format_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def stream_graph(
    session_id: str,
    user_query: str,
    uploaded_files: list[dict],
) -> Generator[str, None, None]:
    if not user_query.strip() and not uploaded_files:
        raise ValueError("Either user_query or uploaded_files must be provided")

    config = {"configurable": {"thread_id": session_id}}
    prior_state = workmate_agent.get_state(config)
    prior_presented_count = len((prior_state.values or {}).get("presented_files", []))
    prior_widget_count = len((prior_state.values or {}).get("presented_widget", []))

    agent_query = build_agent_query(user_query, uploaded_files)
    hm = HumanMessage(content=agent_query)
    logger.debug(hm.pretty_repr())
    graph_state = {
        "messages": [hm],
        "presented_files": [],
        "presented_widget": [],
    }

    def _stream() -> Generator[str, None, None]:
        text_buffer = ""
        text_chunk_count = 0
        had_text_this_turn = False
        sent_presented_count = prior_presented_count
        sent_widget_count = prior_widget_count

        try:
            for chunk in workmate_agent.stream(
                graph_state,
                config=config,
                stream_mode=["messages", "updates"],
                version="v2",
            ):
                events: list[dict] = []

                if chunk["type"] == "messages":
                    token, metadata = chunk["data"]
                    if metadata.get("langgraph_node") != "model":
                        continue
                    if not isinstance(token, AIMessageChunk):
                        continue

                    if token.text:
                        text_buffer += token.text
                        text_chunk_count += 1
                        had_text_this_turn = True

                    if text_chunk_count >= 5 and text_buffer:
                        events.append({"token": text_buffer})
                        text_buffer = ""
                        text_chunk_count = 0

                    if token.usage_metadata and had_text_this_turn:
                        event: dict = {
                            "end_message": True,
                            "usage_metadata": token.usage_metadata,
                        }
                        if text_buffer:
                            event["token"] = text_buffer
                            text_buffer = ""
                            text_chunk_count = 0
                        events.append(event)
                        had_text_this_turn = False

                elif chunk["type"] == "updates":
                    for source, update in chunk["data"].items():
                        if source == "model":
                            messages = update.get("messages", [])
                            if not messages:
                                continue
                            last_message = messages[-1]
                            if isinstance(last_message, AIMessage) and last_message.tool_calls:
                                events.append({"message": serialize_message(last_message)})
                        elif source == "tools":
                            for message in update.get("messages", []):
                                if isinstance(message, ToolMessage):
                                    events.append({"message": serialize_message(message)})

                            presented_files = update.get("presented_files")
                            if presented_files and len(presented_files) > sent_presented_count:
                                new_files = presented_files[sent_presented_count:]
                                sent_presented_count = len(presented_files)
                                events.append({"shared_files": new_files})

                            presented_widgets = update.get("presented_widget")
                            if presented_widgets and len(presented_widgets) > sent_widget_count:
                                new_widgets = presented_widgets[sent_widget_count:]
                                sent_widget_count = len(presented_widgets)
                                for w in new_widgets:
                                    events.append({"widget": w})

                for event in events:
                    logger.debug(f"Stream event: {event}")
                    yield _format_sse(event)

        except Exception as e:
            logger.error(f"Error streaming graph: {e}")
            yield _format_sse({"error": str(e)})
        finally:
            if text_buffer:
                yield _format_sse({"token": text_buffer})
            yield _format_sse({"end_of_stream": True})

    return _stream()