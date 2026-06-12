import os
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from .agent_registry.state import DeepAgentState
from .agent_registry.tools import (
    bash_tool,
    create_file,
    insert,
    present_files,
    read_todos,
    str_replace,
    think_tool,
    view_file,
    write_todos,
    _create_task_tool,
)
from .agent_registry.llms import llm
from .agent_registry.subagents import visual_designer_sub_agent
from .agent_registry.prompts import TODO_USAGE_INSTRUCTIONS, SUBAGENT_USAGE_INSTRUCTIONS


sub_agent_tools = [
    bash_tool,
    view_file,
    str_replace,
    create_file,
    insert,
    present_files,
    think_tool,
]
built_in_tools = [
    bash_tool,
    view_file,
    str_replace,
    create_file,
    insert,
    present_files,
    write_todos,
    read_todos,
    think_tool,
]

# Create task tool to delegate tasks to sub-agents
task_tool = _create_task_tool(
    sub_agent_tools, [visual_designer_sub_agent], llm, DeepAgentState
)

delegation_tools = [task_tool]
all_tools = built_in_tools + delegation_tools


SEPARATOR = "\n\n" + "=" * 80 + "\n\n"
INSTRUCTIONS = (
    "# TODO MANAGEMENT\n"
    + TODO_USAGE_INSTRUCTIONS
    + SEPARATOR
    + "# TASK DELEGATION\n"
    + SUBAGENT_USAGE_INSTRUCTIONS
)

checkpointer = InMemorySaver()

workmate_agent = create_agent(
    llm,
    all_tools,
    system_prompt=INSTRUCTIONS,
    state_schema=DeepAgentState,
    checkpointer=checkpointer,
)