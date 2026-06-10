from __future__ import annotations

import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..custom_logger import logger

CONTAINER_NAME = "sandbox-env"
OUTPUT_DIR = "/usr-data/output"
UPLOADS_DIR = "/usr-data/uploads"
FILES_DIR = "/scratchpad"
MAX_LINES = 400
DEFAULT_TIMEOUT = 30
TIMEOUT_EXIT_CODE = 124  # GNU timeout(1) when the duration is exceeded
TIMEOUT_KILL_AFTER = 5  # seconds between SIGTERM and SIGKILL
TIMEOUT_PYTHON_GRACE = 3  # reader deadline beyond kill-after

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILE = _PROJECT_ROOT / "filesystem-env" / "docker-compose.yml"


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
        compose_file: Path = _COMPOSE_FILE,
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
