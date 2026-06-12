from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from ...api.controllers.file_operations import copy_file_from_container_to_local_storage
from .executor import (
    DEFAULT_TIMEOUT,
    ContainerFileError,
    bash_session_manager,
    create_container_file,
    format_command_output,
    insert_in_container,
    str_replace_in_container,
    view_container_path,
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


def _file_tool_response(
    runtime: ToolRuntime,
    msg: str,
    *,
    is_error: bool = False,
) -> Command:
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


@tool(parse_docstring=False)
def view_file(
    path: str,
    description: str,
    runtime: ToolRuntime,
    view_range: list[int] | None = None,
    max_characters: int | None = None,
) -> Command:
    """View a file or list a directory in the container filesystem.

    Files are returned with line numbers (e.g. "1: content") to support targeted edits.
    Directories return a listing of their contents.

    Args:
        path: Path to the file or directory in the container. Relative paths are
            resolved from /scratchpad. Allowed roots: /scratchpad, /usr-data/output,
            /usr-data/uploads.
        description: Short explanation of why this file or directory is being viewed.
        view_range: Optional 1-indexed [start, end] line range. Use -1 for end to read
            to the end of the file. Only applies when viewing files.
        max_characters: Optional maximum characters to return when viewing a file.
    """
    try:
        msg = view_container_path(
            path,
            view_range=view_range,
            max_characters=max_characters,
        )
    except ContainerFileError as exc:
        return _file_tool_response(runtime, f"Error: {exc}", is_error=True)

    return _file_tool_response(runtime, msg)


@tool(parse_docstring=True)
def str_replace(
    path: str,
    old_string: str,
    new_string: str,
    description: str,
    runtime: ToolRuntime,
) -> Command:
    """Replace a unique string in a container file.

    The old_string must match exactly once, including whitespace and indentation.

    Args:
        path: Path to the file in the container.
        old_string: Exact text to replace.
        new_string: Replacement text.
        description: Short explanation of why this edit is being made.
    """
    try:
        msg = str_replace_in_container(path, old_string, new_string)
    except ContainerFileError as exc:
        return _file_tool_response(runtime, f"Error: {exc}", is_error=True)

    return _file_tool_response(runtime, msg)


@tool(parse_docstring=True)
def create_file(
    path: str,
    file_text: str,
    description: str,
    runtime: ToolRuntime,
) -> Command:
    """Create a new file in the container filesystem.

    Args:
        path: Path where the new file should be created.
        file_text: Content to write to the new file.
        description: Short explanation of why this file is being created.
    """
    try:
        msg = create_container_file(path, file_text)
    except ContainerFileError as exc:
        return _file_tool_response(runtime, f"Error: {exc}", is_error=True)

    return _file_tool_response(runtime, msg)


@tool(parse_docstring=True)
def insert(
    path: str,
    insert_line: int,
    insert_text: str,
    description: str,
    runtime: ToolRuntime,
) -> Command:
    """Insert text at a specific line in a container file.

    Args:
        path: Path to the file in the container.
        insert_line: Line number after which to insert text. Use 0 to insert at the
            beginning of the file.
        insert_text: Text to insert.
        description: Short explanation of why this insertion is being made.
    """
    try:
        msg = insert_in_container(path, insert_line, insert_text)
    except ContainerFileError as exc:
        return _file_tool_response(runtime, f"Error: {exc}", is_error=True)

    return _file_tool_response(runtime, msg)


@tool(parse_docstring=True)
def present_files(filepath: str, description: str, runtime: ToolRuntime) -> Command:
    """Present a file to the user by copying it from the container to local storage.

    Use this after creating or modifying files in the container output directory
    (/usr-data/output) so the user can download them from the session downloads folder.

    Args:
        filepath: Path to the file in the container. Absolute paths or paths relative
            to /usr-data/output are accepted.
        description: Short explanation of why this file is being presented.
    """
    session_id = runtime.config.get("configurable", {}).get("thread_id")
    if not session_id:
        msg = "Error: session thread_id is required."
        return Command(
            update={
                "messages": [
                    ToolMessage(msg, tool_call_id=runtime.tool_call_id, status="error")
                ],
            }
        )

    try:
        result = copy_file_from_container_to_local_storage(session_id, filepath)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        msg = f"Error: {detail}"
        return Command(
            update={
                "messages": [
                    ToolMessage(msg, tool_call_id=runtime.tool_call_id, status="error")
                ],
            }
        )

    presented_files = runtime.state.get("presented_files", []) + [result]
    msg = f"File named {result['file_name']} presented successfully."
    return Command(
        update={
            "presented_files": presented_files,
            "messages": [ToolMessage(msg, tool_call_id=runtime.tool_call_id)],
        }
    )
