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

    Commands execute inside a Linux-based Docker container, not on the host.
    Session state (cwd, environment variables) persists across calls and is shared with sub-agents. Refer to the filesystem instructions in the system prompt for directory layout and access rules.

    When to use bash vs. python:
        Use standard bash commands (ls, cp, mv, grep, cat, head, etc.) for routine filesystem tasks. For anything involving data processing, parsing, or object-format files (PDF, DOCX, PPTX, XLSX), use a Python script instead.

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


@tool(parse_docstring=True)
def view_file(
    path: str,
    description: str,
    runtime: ToolRuntime,
    view_range: list[int] | None = None,
    max_characters: int | None = None,
) -> Command:
    """View a plain-text file or list a directory inside the container.

    Returns file contents with line numbers (e.g. "1: content") to support targeted edits with str_replace or insert. When given a directory path, returns a listing of its contents instead.

    This tool only works with plain-text files (e.g. .txt, .py, .csv, .json, .html, .md, .yaml, .sh, .log). It CANNOT read object-format files such as PDF, DOCX, PPTX, or XLSX — use bash_tool with a Python script for those.

    Args:
        path: Path to the file or directory in the container. Relative paths resolve from /scratchpad. Must be under /scratchpad, /usr-data/output, or /usr-data/uploads.
        description: Short explanation of why this file or directory is being viewed.
        view_range: Optional 1-indexed [start, end] line range. Use -1 for end to read to the end of the file. Only applies to files, not directories.
        max_characters: Optional maximum number of characters to return.
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
    """Replace a unique string in a plain-text file inside the container.

    The old_string must appear exactly once in the file. The match is exact, including all whitespace, indentation, and newlines. Use view_file first to see the current file contents and identify the precise text to replace.

    This tool only works with plain-text files. It CANNOT edit object-format files (PDF, DOCX, PPTX, XLSX) — use bash_tool with a Python script for those.

    Args:
        path: Path to the file in the container. Relative paths resolve from /scratchpad. Must be under /scratchpad, /usr-data/output, or /usr-data/uploads.
        old_string: The exact text to find and replace. Must match exactly once.
        new_string: The replacement text.
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
    """Create a new plain-text file in the container filesystem.

    Writes file_text to a new file at the given path. Fails if the file already
    exists — use str_replace or insert to modify existing files.

    This tool only creates plain-text files (e.g. .txt, .py, .csv, .json, .html, .md). To create object-format files (PDF, DOCX, PPTX, XLSX), use bash_tool with a Python script and the appropriate library.

    If the created file is intended for the user, write it to /usr-data/output and then call the present_files tool to deliver it.

    Args:
        path: Path where the new file should be created. Relative paths resolve from /scratchpad. Must be under /scratchpad, /usr-data/output, or /usr-data/uploads.
        file_text: The full text content to write to the new file.
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
    """Insert text at a specific line number in a plain-text file.

    Inserts insert_text after the specified line number. Use view_file first to
    see the current line numbers and determine where to insert.

    This tool only works with plain-text files. It CANNOT edit object-format files (PDF, DOCX, PPTX, XLSX) — use bash_tool with a Python script for those.

    Args:
        path: Path to the file in the container. Relative paths resolve from /scratchpad. Must be under /scratchpad, /usr-data/output, or /usr-data/uploads.
        insert_line: Line number after which to insert text. Use 0 to insert at the beginning of the file.
        insert_text: The text to insert.
        description: Short explanation of why this insertion is being made.
    """
    try:
        msg = insert_in_container(path, insert_line, insert_text)
    except ContainerFileError as exc:
        return _file_tool_response(runtime, f"Error: {exc}", is_error=True)

    return _file_tool_response(runtime, msg)


@tool(parse_docstring=True)
def present_files(filepath: str, description: str, runtime: ToolRuntime) -> Command:
    """Deliver a file from the container to the user's local downloads folder.

    Call this tool after creating or modifying a file in /usr-data/output to make it available for the user to download. Only files under /usr-data/output can be presented.

    Typical workflow:
        1. Create/generate the file in /usr-data/output (via create_file or bash_tool).
        2. Call present_files to deliver it to the user.

    Args:
        filepath: Path to the file inside the container. Absolute paths or paths relative to /usr-data/output are accepted.
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
