from langchain.agents.middleware import wrap_tool_call, AgentMiddleware, ModelRequest, ModelResponse, ToolCallRequest
from langchain.messages import SystemMessage, ToolMessage
from langgraph.types import Command
from langgraph.config import get_stream_writer
from typing import Callable

from ..utils import logger
from .skills_helper import CURRENTLY_AVAILABE_SKILLS
from .subagents import CURRENTLY_AVAILABLE_SUBAGENTS
from .prompts import SKILL_USAGE_INSTRUCTIONS, SEPARATOR, SUBAGENT_USAGE_INSTRUCTIONS

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

class SkillsMiddleware(AgentMiddleware):
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:

        if CURRENTLY_AVAILABE_SKILLS:
            skill_addendum = SEPARATOR + SKILL_USAGE_INSTRUCTIONS.format(
                loaded_skills=CURRENTLY_AVAILABE_SKILLS
            )
            # Use content_blocks to preserve existing structure and append new text
            new_content = list(request.system_message.content_blocks) + [
                {"type": "text", "text": skill_addendum}
            ]
            new_system_message = SystemMessage(content=new_content)
            request = request.override(system_message=new_system_message)

        return handler(request)
    
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        # Pass the tool call through if you don't need to intercept
        return handler(request)