import uuid

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent_registry.tools.executor import (
    DEFAULT_TIMEOUT,
    bash_session_manager,
    format_command_output,
)


@tool(parse_docstring=True)
def bash_tool(
    description: str,
    runtime: ToolRuntime,
    command: str | None = None,
    restart: bool = False,
    timeout: int | None = None,
) -> Command:
    """Run a bash command in the persistent Docker container session.

    Commands execute inside the filesystem container, not on the host.
    Session state (cwd, env vars) persists across calls and is shared with sub-agents.

    Args:
        description: Short explanation of why this command is being run.
        command: Bash command to execute. Required unless restart is true.
        restart: When true, restart the bash session and reset cwd/env.
        timeout: Optional command timeout in seconds (max 30, default 30).
    """
    session_id = runtime.config.get("configurable", {}).get("thread_id")
    effective_timeout = DEFAULT_TIMEOUT if timeout is None else min(timeout, DEFAULT_TIMEOUT)

    if restart:
        bash_session_manager.restart(session_id)
        msg = "Bash session restarted."
        return Command(
            update={
                "messages": [ToolMessage(msg, tool_call_id=runtime.tool_call_id)],
            }
        )

    if not command:
        msg = "Error: provide either command or restart=true."
        return Command(
            update={
                "messages": [
                    ToolMessage(msg, tool_call_id=runtime.tool_call_id, status="error")
                ],
            }
        )

    try:
        session = bash_session_manager.get_or_create(session_id)
        result = session.execute_command(command, timeout=effective_timeout)
        msg = format_command_output(result, timeout=effective_timeout)
        is_error = result.timed_out or result.exit_code != 0
    except RuntimeError as exc:
        msg = f"Error: {exc}"
        is_error = True

    return Command(
        update={
            "messages": [
                ToolMessage(
                    msg,
                    tool_call_id=runtime.tool_call_id,
                    status="error" if is_error else "success",
                )
            ],
        }
    )


def str_replace(filepath: str, old_string: str, new_string: str, description: str, runtime: ToolRuntime) -> str:
    """Replace a string in a file."""
    pass


def present_files(filepath: str, description: str, runtime: ToolRuntime) -> str:
    """Present the contents of a file."""
    pass
