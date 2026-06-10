from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fastapi import HTTPException, UploadFile

from ...utils.constants import (
    COMPOSE_FILE,
    CONTAINER_NAME,
    CONTAINER_OUTPUT_DIR,
    CONTAINER_SCRATCHPAD_DIR,
    CONTAINER_UPLOADS_DIR,
    FILES_ROOT,
    PROJECT_ROOT,
)
from ...utils import logger


class FileUploadError(Exception):
    pass


def _validate_session_id(session_id: str) -> str:
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if session_id in {".", ".."} or "/" in session_id or "\\" in session_id:
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return session_id


def _sanitize_filename(filename: str | None) -> str:
    name = Path(filename or "upload").name
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return name


def _resolve_unique_filename(filename: str, taken_names: set[str]) -> str:
    if filename not in taken_names:
        return filename

    path = Path(filename)
    stem = path.stem or "upload"
    suffix = path.suffix
    counter = 1
    while True:
        candidate = f"{stem}_{counter}{suffix}"
        if candidate not in taken_names:
            return candidate
        counter += 1


def _existing_local_file_names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir() if path.is_file()}


def _existing_local_upload_names(uploads_dir: Path) -> set[str]:
    return _existing_local_file_names(uploads_dir)


def _existing_container_upload_names() -> set[str]:
    list_result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "exec",
            "-T",
            CONTAINER_NAME,
            "sh",
            "-c",
            f"ls -1 {CONTAINER_UPLOADS_DIR} 2>/dev/null || true",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if list_result.returncode != 0:
        raise FileUploadError(
            list_result.stderr.strip() or "Failed to list container upload directory"
        )
    return {line.strip() for line in list_result.stdout.splitlines() if line.strip()}


def ensure_session_dirs(session_id: str) -> tuple[Path, Path]:
    session_id = _validate_session_id(session_id)
    session_dir = FILES_ROOT / session_id
    uploads_dir = session_dir / "uploads"
    downloads_dir = session_dir / "downloads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir, downloads_dir


def _copy_to_container(local_path: Path, filename: str) -> str:
    container_path = f"{CONTAINER_UPLOADS_DIR}/{filename}"

    copy_result = subprocess.run(
        ["docker", "cp", str(local_path), f"{CONTAINER_NAME}:{container_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if copy_result.returncode != 0:
        raise FileUploadError(
            copy_result.stderr.strip() or "Failed to copy file into container"
        )

    return container_path


def _validate_container_output_path(container_filepath: str) -> str:
    raw_path = container_filepath.strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="container_filepath is required")

    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(CONTAINER_OUTPUT_DIR) / path

    if ".." in path.parts:
        raise HTTPException(status_code=400, detail="Invalid container file path")

    container_path = path.as_posix()
    output_dir = CONTAINER_OUTPUT_DIR.rstrip("/")
    if container_path != output_dir and not container_path.startswith(f"{output_dir}/"):
        raise HTTPException(
            status_code=400,
            detail="Only files from /usr-data/output can be downloaded",
        )

    if not path.name or path.name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid container file path")

    return container_path


def _container_file_exists(container_path: str) -> bool:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "exec",
            "-T",
            CONTAINER_NAME,
            "test",
            "-f",
            container_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def copy_file_from_container_to_local_storage(
    session_id: str,
    container_filepath: str,
) -> dict[str, str]:
    session_id = _validate_session_id(session_id)
    container_path = _validate_container_output_path(container_filepath)

    if not _container_file_exists(container_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found in container: {container_path}",
        )

    _, downloads_dir = ensure_session_dirs(session_id)
    filename = _resolve_unique_filename(
        _sanitize_filename(Path(container_path).name),
        _existing_local_file_names(downloads_dir),
    )
    dest_path = downloads_dir / filename

    copy_result = subprocess.run(
        ["docker", "cp", f"{CONTAINER_NAME}:{container_path}", str(dest_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if copy_result.returncode != 0:
        logger.error(
            "Failed to copy %s from container to %s: %s",
            container_path,
            dest_path,
            copy_result.stderr.strip(),
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to copy file from container to local storage",
        )

    return {
        "file_name": filename,
        "file_path": str(dest_path.relative_to(PROJECT_ROOT)),
        "container_path": container_path,
    }


def _run_compose_command(args: list[str], *, error_message: str) -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FileUploadError(result.stderr.strip() or error_message)


def _clear_container_data() -> None:
    _run_compose_command(
        [
            "exec",
            "-u",
            "root",
            "-T",
            CONTAINER_NAME,
            "sh",
            "-c",
            (
                f"rm -rf {CONTAINER_UPLOADS_DIR}/* "
                f"{CONTAINER_OUTPUT_DIR}/* "
                f"{CONTAINER_SCRATCHPAD_DIR}/*"
            ),
        ],
        error_message="Failed to clear container session data",
    )


def refresh_session(session_id: str) -> dict[str, str | bool]:
    session_id = _validate_session_id(session_id)

    try:
        _clear_container_data()
    except FileUploadError as exc:
        logger.error("Failed to refresh session %s: %s", session_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh session: {exc}",
        ) from exc

    return {
        "session_id": session_id,
        "container_cleared": True,
    }


async def upload_file(session_id: str, file: UploadFile) -> dict[str, str]:
    session_id = _validate_session_id(session_id)
    uploads_dir, _ = ensure_session_dirs(session_id)

    try:
        taken_names = _existing_local_upload_names(uploads_dir) | _existing_container_upload_names()
    except FileUploadError as exc:
        logger.error("Failed to resolve existing upload names: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check existing uploads: {exc}",
        ) from exc

    filename = _resolve_unique_filename(_sanitize_filename(file.filename), taken_names)
    dest_path = uploads_dir / filename

    try:
        with dest_path.open("xb") as dest:
            shutil.copyfileobj(file.file, dest)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="File already exists") from exc
    except OSError as exc:
        logger.exception("Failed to save uploaded file to %s", dest_path)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file") from exc

    try:
        container_path = _copy_to_container(dest_path, filename)
    except FileUploadError as exc:
        dest_path.unlink(missing_ok=True)
        logger.error("Failed to copy upload to container: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"File saved locally but failed to copy to container: {exc}",
        ) from exc

    return {
        "file_name": filename,
        "file_path": str(dest_path.relative_to(PROJECT_ROOT)),
        "container_path": container_path,
    }


def download_file(session_id: str, container_filepath: str) -> dict[str, str]:
    return copy_file_from_container_to_local_storage(session_id, container_filepath)
