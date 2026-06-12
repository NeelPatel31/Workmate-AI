from __future__ import annotations

import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ...utils.constants import (
    COMPOSE_FILE,
    CONTAINER_NAME,
    CONTAINER_OUTPUT_DIR,
    CONTAINER_SCRATCHPAD_DIR,
    CONTAINER_UPLOADS_DIR,
    DEFAULT_TIMEOUT,
    FILES_DIR,
    MAX_LINES,
    TIMEOUT_EXIT_CODE,
    TIMEOUT_KILL_AFTER,
    TIMEOUT_PYTHON_GRACE,
)
from ...utils import logger


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


def _shell_single_quote(value: str) -> str:
    """Quote a string for safe inclusion in a bash single-quoted argument."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _wrap_command_with_timeout(command: str, timeout: float) -> str:
    """Wrap a command with GNU timeout so hung processes are killed."""
    duration = max(1, int(timeout))
    quoted = _shell_single_quote(command)
    return (
        f"timeout --foreground --signal=TERM --kill-after={TIMEOUT_KILL_AFTER} "
        f"{duration}s bash -c {quoted}"
    )


class BashSession:
    """Persistent /bin/bash session running inside a Docker container via compose exec."""

    def __init__(
        self,
        *,
        service: str = CONTAINER_NAME,
        cwd: str = FILES_DIR,
        compose_file: Path = COMPOSE_FILE,
    ) -> None:
        self.service = service
        self.cwd = cwd
        self.compose_file = compose_file
        self._stdout_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self._stderr_queue: queue.Queue[str | None] = queue.Queue()
        self._readers: list[threading.Thread] = []
        self._closed = False
        self._start()

    def _docker_exec_cmd(self) -> list[str]:
        return [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "exec",
            "-T",
            "-w",
            self.cwd,
            self.service,
            "/bin/bash",
        ]

    def _start(self) -> None:
        try:
            self.process = subprocess.Popen(
                self._docker_exec_cmd(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Docker CLI not found. Install Docker and ensure it is on PATH."
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"Failed to start bash session in container '{self.service}': {exc}"
            ) from exc

        if self.process.stdout is None or self.process.stderr is None or self.process.stdin is None:
            raise RuntimeError("Failed to open stdio pipes for bash session.")

        self._readers = [
            threading.Thread(
                target=self._read_stream,
                args=(self.process.stdout, self._stdout_queue, "stdout"),
                daemon=True,
            ),
            threading.Thread(
                target=self._read_stream,
                args=(self.process.stderr, self._stderr_queue, "stderr"),
                daemon=True,
            ),
        ]
        for reader in self._readers:
            reader.start()

    @staticmethod
    def _read_stream(
        stream,
        output_queue: queue.Queue[tuple[str, str | None]] | queue.Queue[str | None],
        label: str,
    ) -> None:
        try:
            while True:
                line = stream.readline()
                if line == "":
                    break
                if label == "stdout":
                    output_queue.put((label, line))  # type: ignore[union-attr]
                else:
                    output_queue.put(line)  # type: ignore[union-attr]
        finally:
            if label == "stdout":
                output_queue.put((label, None))  # type: ignore[union-attr]
            else:
                output_queue.put(None)  # type: ignore[union-attr]

    @property
    def is_alive(self) -> bool:
        return not self._closed and self.process.poll() is None

    def restart(self) -> None:
        self.close()
        self._closed = False
        self._stdout_queue = queue.Queue()
        self._stderr_queue = queue.Queue()
        self._start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.stdin:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def execute_command(self, command: str, timeout: float = DEFAULT_TIMEOUT) -> CommandResult:
        if not self.is_alive:
            raise RuntimeError(
                f"Bash session is not running. Container service '{self.service}' may be stopped."
            )

        marker = f"__BASH_DONE_{uuid.uuid4().hex}__"
        timed_command = _wrap_command_with_timeout(command, timeout)
        wrapped = f"{timed_command}; printf '%s%d\\n' '{marker}' $?\n"

        try:
            self.process.stdin.write(wrapped)
            self.process.stdin.flush()
        except OSError as exc:
            raise RuntimeError(f"Failed to send command to bash session: {exc}") from exc

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        exit_code: int | None = None
        reader_deadline = time.monotonic() + timeout + TIMEOUT_KILL_AFTER + TIMEOUT_PYTHON_GRACE

        while time.monotonic() < reader_deadline:
            self._drain_stderr(stderr_lines)

            try:
                _label, line = self._stdout_queue.get(timeout=0.05)
            except queue.Empty:
                if self.process.poll() is not None and exit_code is None:
                    break
                continue

            if line is None:
                break

            stripped = line.rstrip("\n")
            if stripped.startswith(marker):
                suffix = stripped[len(marker) :]
                if suffix.isdigit() or (suffix.startswith("-") and suffix[1:].isdigit()):
                    exit_code = int(suffix)
                else:
                    exit_code = 0
                break

            stdout_lines.append(stripped)

        self._drain_stderr(stderr_lines)

        if exit_code is None:
            logger.warning(
                "Command safety timeout after %s seconds (marker missing): %s",
                timeout,
                command[:200],
            )
            try:
                self.restart()
            except Exception:
                logger.exception("Failed to restart bash session after safety timeout")
            return CommandResult(
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines),
                exit_code=-1,
                timed_out=True,
            )

        timed_out = exit_code == TIMEOUT_EXIT_CODE
        if timed_out:
            logger.warning("Command timed out after %s seconds: %s", timeout, command[:200])
            return CommandResult(
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines),
                exit_code=-1,
                timed_out=True,
            )

        return CommandResult(
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
            exit_code=exit_code,
        )

    def _drain_stderr(self, stderr_lines: list[str]) -> None:
        while True:
            try:
                line = self._stderr_queue.get_nowait()
            except queue.Empty:
                break
            if line is None:
                break
            stderr_lines.append(line.rstrip("\n"))


def truncate_head(text: str, max_lines: int) -> tuple[str, bool]:
    if not text:
        return "", False
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    truncated = "\n".join(lines[:max_lines])
    notice = f"... stdout truncated ({len(lines)} total lines, showing first {max_lines}) ..."
    return f"{truncated}\n\n{notice}", True


def truncate_tail(text: str, max_lines: int) -> tuple[str, bool]:
    if not text:
        return "", False
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    truncated = "\n".join(lines[-max_lines:])
    notice = f"... stderr truncated ({len(lines)} total lines, showing last {max_lines}) ..."
    return f"{notice}\n\n{truncated}", True


def format_command_output(
    result: CommandResult,
    *,
    max_lines: int = MAX_LINES,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    parts: list[str] = []

    if result.stdout:
        stdout_text, _ = truncate_head(result.stdout, max_lines)
        parts.append(f"=== stdout ===\n{stdout_text}")

    if result.stderr:
        stderr_text, _ = truncate_tail(result.stderr, max_lines)
        parts.append(f"=== stderr ===\n{stderr_text}")

    if not parts:
        parts.append("(no output)")

    parts.append(f"exit code: {result.exit_code}")
    body = "\n\n".join(parts)

    if result.timed_out:
        return f"Error: Command timed out after {timeout} seconds\n\n{body}"

    return body


class BashSessionManager:
    """In-process registry keyed by bash_session_id stored in agent state."""

    def __init__(self) -> None:
        self._sessions: dict[str, BashSession] = {}

    def get_or_create(self, session_id: str) -> BashSession:
        session = self._sessions.get(session_id)
        if session is None or not session.is_alive:
            if session is not None:
                session.close()
            session = BashSession()
            self._sessions[session_id] = session
            logger.info("Created bash session %s", session_id)
        return session

    def restart(self, session_id: str) -> BashSession:
        session = self._sessions.get(session_id)
        if session is not None:
            session.restart()
        else:
            session = BashSession()
            self._sessions[session_id] = session
        logger.info("Restarted bash session %s", session_id)
        return session

    def close(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()

    def close_all(self) -> None:
        for session_id in list(self._sessions):
            self.close(session_id)


bash_session_manager = BashSessionManager()


ALLOWED_CONTAINER_ROOTS = (
    CONTAINER_SCRATCHPAD_DIR,
    CONTAINER_OUTPUT_DIR,
    CONTAINER_UPLOADS_DIR,
)


class ContainerFileError(Exception):
    """Raised when a container file operation fails."""


def resolve_container_path(path: str) -> str:
    """Resolve and validate a path inside the container filesystem."""
    raw = path.strip()
    if not raw:
        raise ContainerFileError("path is required")

    resolved = Path(raw)
    if not resolved.is_absolute():
        resolved = Path(FILES_DIR) / resolved

    if ".." in resolved.parts:
        raise ContainerFileError("Invalid path: directory traversal not allowed")

    container_path = resolved.as_posix()
    for root in ALLOWED_CONTAINER_ROOTS:
        root_norm = root.rstrip("/")
        if container_path == root_norm or container_path.startswith(f"{root_norm}/"):
            if not resolved.name and container_path != root_norm:
                raise ContainerFileError("Invalid path")
            return container_path

    roots = ", ".join(ALLOWED_CONTAINER_ROOTS)
    raise ContainerFileError(f"Invalid path: must be under {roots}")


def _docker_exec(
    command: list[str],
    *,
    stdin: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> CommandResult:
    """Run a one-off command inside the container via docker compose exec."""
    cmd = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "exec",
        "-T",
        CONTAINER_NAME,
        *command,
    ]
    try:
        completed = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ContainerFileError(f"Command timed out after {timeout} seconds") from exc
    except FileNotFoundError as exc:
        raise ContainerFileError(
            "Docker CLI not found. Install Docker and ensure it is on PATH."
        ) from exc
    except OSError as exc:
        raise ContainerFileError(f"Failed to run container command: {exc}") from exc

    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )


def _path_exists_in_container(path: str) -> bool:
    return _docker_exec(["test", "-e", path]).exit_code == 0


def _is_file_in_container(path: str) -> bool:
    return _docker_exec(["test", "-f", path]).exit_code == 0


def _is_dir_in_container(path: str) -> bool:
    return _docker_exec(["test", "-d", path]).exit_code == 0


def read_container_file(path: str) -> str:
    """Read the full contents of a file in the container."""
    result = _docker_exec(["cat", path])
    if result.exit_code != 0:
        if result.exit_code == 1:
            raise ContainerFileError(f"File not found: {path}")
        detail = result.stderr.strip() or "Failed to read file"
        raise ContainerFileError(detail)
    return result.stdout


def write_container_file(path: str, content: str) -> None:
    """Write content to a file in the container, creating parent directories as needed."""
    parent = Path(path).parent.as_posix()
    script = (
        "import sys, os\n"
        f"os.makedirs({parent!r}, exist_ok=True)\n"
        f"with open({path!r}, 'w') as f:\n"
        "    f.write(sys.stdin.read())\n"
    )
    result = _docker_exec(["python3", "-c", script], stdin=content)
    if result.exit_code != 0:
        detail = result.stderr.strip() or "Failed to write file"
        raise ContainerFileError(detail)


def list_container_directory(path: str) -> str:
    """List the contents of a directory in the container."""
    result = _docker_exec(["ls", "-la", path])
    if result.exit_code != 0:
        if result.exit_code == 2:
            raise ContainerFileError(f"Directory not found: {path}")
        detail = result.stderr.strip() or "Failed to list directory"
        raise ContainerFileError(detail)
    return result.stdout


def _format_lines_with_numbers(lines: list[str], start_line: int = 1) -> str:
    return "\n".join(f"{index}: {line}" for index, line in enumerate(lines, start=start_line))


def _apply_view_range(content: str, view_range: list[int] | None) -> tuple[str, int]:
    lines = content.splitlines()
    if not view_range:
        return _format_lines_with_numbers(lines), 1

    if len(view_range) != 2:
        raise ContainerFileError("view_range must contain exactly two integers")

    start, end = view_range
    if start < 1:
        raise ContainerFileError("view_range start must be >= 1")

    if start > len(lines):
        return "", start

    if end == -1:
        selected = lines[start - 1 :]
    else:
        if end < start:
            raise ContainerFileError("view_range end must be >= start")
        selected = lines[start - 1 : end]

    return _format_lines_with_numbers(selected, start_line=start), start


def view_container_path(
    path: str,
    *,
    view_range: list[int] | None = None,
    max_characters: int | None = None,
) -> str:
    """View a file with line numbers or list a directory in the container."""
    container_path = resolve_container_path(path)

    if _is_dir_in_container(container_path):
        if view_range is not None:
            raise ContainerFileError("view_range is only supported when viewing files")
        return list_container_directory(container_path)

    if not _is_file_in_container(container_path):
        raise ContainerFileError(f"File not found: {container_path}")

    content = read_container_file(container_path)
    formatted, _ = _apply_view_range(content, view_range)

    if max_characters is not None and len(formatted) > max_characters:
        formatted = (
            formatted[:max_characters]
            + f"\n\n... output truncated ({len(formatted)} total characters, "
            f"showing first {max_characters}) ..."
        )

    return formatted


def create_container_file(path: str, file_text: str) -> str:
    """Create a new file in the container."""
    container_path = resolve_container_path(path)

    if _path_exists_in_container(container_path):
        raise ContainerFileError(f"File already exists: {container_path}")

    write_container_file(container_path, file_text)
    return f"File created successfully at {container_path}"


def str_replace_in_container(path: str, old_str: str, new_str: str) -> str:
    """Replace exactly one occurrence of old_str with new_str in a container file."""
    container_path = resolve_container_path(path)

    if not _is_file_in_container(container_path):
        raise ContainerFileError(f"File not found: {container_path}")

    content = read_container_file(container_path)
    count = content.count(old_str)
    if count == 0:
        raise ContainerFileError(
            "No match found for replacement. Please check your text and try again."
        )
    if count > 1:
        raise ContainerFileError(
            f"Found {count} matches for replacement text. "
            "Please provide more context to make a unique match."
        )

    write_container_file(container_path, content.replace(old_str, new_str, 1))
    return "Successfully replaced text at exactly one location."


def insert_in_container(path: str, insert_line: int, insert_text: str) -> str:
    """Insert text after a given line number in a container file."""
    container_path = resolve_container_path(path)

    if not _is_file_in_container(container_path):
        raise ContainerFileError(f"File not found: {container_path}")

    if insert_line < 0:
        raise ContainerFileError("insert_line must be >= 0")

    content = read_container_file(container_path)
    lines = content.splitlines()
    text_lines = insert_text.splitlines()

    if insert_line == 0:
        new_lines = text_lines + lines
    elif insert_line > len(lines):
        raise ContainerFileError(
            f"insert_line {insert_line} is beyond the end of the file ({len(lines)} lines)"
        )
    else:
        new_lines = lines[:insert_line] + text_lines + lines[insert_line:]

    write_container_file(container_path, "\n".join(new_lines) + ("\n" if content.endswith("\n") else ""))
    return f"Successfully inserted text after line {insert_line}."
