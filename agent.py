import os
from langchain.agents import create_agent

from agent_registry.state import DeepAgentState
from agent_registry.tools import bash_tool, str_replace, present_files, write_todos, read_todos, think_tool, _create_task_tool
from agent_registry.llms import llm
from agent_registry.subagents import visual_designer_sub_agent
from agent_registry.prompts import TODO_USAGE_INSTRUCTIONS, TASK_DELEGATION_INSTRUCTIONS

from dotenv import load_dotenv

load_dotenv()

sub_agent_tools = [bash_tool, str_replace, present_files, think_tool]
built_in_tools = [bash_tool, str_replace, present_files, write_todos, read_todos, think_tool]

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
    + TASK_DELEGATION_INSTRUCTIONS
)

agent = create_agent(
    llm,
    all_tools,
    system_prompt=INSTRUCTIONS,
    state_schema=DeepAgentState,
)