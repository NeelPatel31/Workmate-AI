from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from .state import DeepAgentState
from .tools import (
    bash_tool,
    create_file,
    display_widget,
    insert,
    present_files,
    read_todos,
    str_replace,
    think_tool,
    view_file,
    write_todos,
    _create_task_tool,
)
from .llms import llm
from .subagents import visual_designer_sub_agent
from .prompts import (
    FILESYSTEM_INSTRUCTIONS,
    MAIN_AGENT_DESCRIPTION,
    SUBAGENT_USAGE_INSTRUCTIONS,
    TODO_USAGE_INSTRUCTIONS,
    SEPARATOR
)
from .middlewares import SkillsMiddleware


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
    display_widget,
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


INSTRUCTIONS = (
    MAIN_AGENT_DESCRIPTION
    + SEPARATOR
    + FILESYSTEM_INSTRUCTIONS
    + SEPARATOR
    + TODO_USAGE_INSTRUCTIONS
    + SEPARATOR
    + SUBAGENT_USAGE_INSTRUCTIONS
)

checkpointer = InMemorySaver()

workmate_agent = create_agent(
    llm,
    all_tools,
    system_prompt=INSTRUCTIONS,
    state_schema=DeepAgentState,
    checkpointer=checkpointer,
    middleware=[
        SkillsMiddleware()
    ]
)