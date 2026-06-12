from __future__ import annotations

import json
from typing import Any, Generator

import httpx

from config import API_BASE_URL


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    detail = response.text
    try:
        payload = response.json()
        detail = payload.get("detail", detail)
    except Exception:
        pass
    raise ApiError(str(detail), response.status_code)


def upload_file(session_id: str, file_name: str, file_bytes: bytes) -> dict[str, str]:
    with httpx.Client(base_url=API_BASE_URL, timeout=120.0) as client:
        response = client.post(
            "/upload-file",
            data={"session_id": session_id},
            files={"file": (file_name, file_bytes)},
        )
        _raise_for_status(response)
        return response.json()


def _parse_sse_events(response: httpx.Response) -> Generator[dict[str, Any], None, None]:
    buffer = ""
    for chunk in response.iter_text():
        buffer += chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            for line in block.split("\n"):
                if line.startswith("data: "):
                    yield json.loads(line[6:])


def stream_chat(
    session_id: str,
    user_query: str,
    uploaded_files: list[dict[str, str]],
) -> Generator[dict[str, Any], None, None]:
    with httpx.Client(base_url=API_BASE_URL, timeout=600.0) as client:
        with client.stream(
            "POST",
            "/stream-graph",
            json={
                "session_id": session_id,
                "user_query": user_query,
                "uploaded_files": uploaded_files,
            },
        ) as response:
            _raise_for_status(response)
            yield from _parse_sse_events(response)


def refresh_session(session_id: str) -> dict[str, Any]:
    with httpx.Client(base_url=API_BASE_URL, timeout=60.0) as client:
        response = client.get("/refresh-session", params={"session_id": session_id})
        _raise_for_status(response)
        return response.json()


def delete_upload(session_id: str, file_name: str) -> dict[str, str]:
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        response = client.delete(
            "/delete-upload",
            params={"session_id": session_id, "file_name": file_name},
        )
        _raise_for_status(response)
        return response.json()
