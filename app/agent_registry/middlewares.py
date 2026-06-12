from collections.abc import Callable

from langchain.agents.middleware import wrap_tool_call
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command
from langgraph.config import get_stream_writer

from ..utils import logger

@wrap_tool_call
def monitor_tool(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    logger.info(request.tool_call)
    writer = get_stream_writer()

    current_tool_call = request.tool_call
    writer(current_tool_call)
    try:
        result = handler(request)
        logger.info(result.pretty_repr())
        writer(result.to_json())
        return result
    except Exception as e:
        logger.error(f"Tool failed: {e}")
        raise
