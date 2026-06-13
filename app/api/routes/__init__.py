import json
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile as FastAPIUploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..controllers.chat_operations import stream_graph as stream_graph_controller
from ..controllers.file_operations import (
    delete_upload as delete_upload_controller,
    refresh_session as refresh_session_controller,
    upload_file as upload_file_controller,
)

router = APIRouter()


class UploadedFile(BaseModel):
    file_name: str
    file_path: str


class ChatRequest(BaseModel):
    user_query: str = ""
    session_id: str
    uploaded_files: List[UploadedFile] = Field(default_factory=list)


@router.post("/upload-file")
async def upload_file_endpoint(
    session_id: str = Form(..., description="The session ID"),
    file: FastAPIUploadFile = File(..., description="The file to upload"),
):

    # {
    #     "message": "File uploaded successfully",
    #     "file_name": "test.png",
    #     "file_path": "files/hello/uploads/test.png",
    #     "container_path": "/usr-data/uploads/test.png"
    # }

    result = await upload_file_controller(session_id, file)
    return {"message": "File uploaded successfully", **result}


@router.get("/refresh-session")
async def refresh_session(session_id: str):
    # {
    #     "message": "Session refreshed successfully",
    #     "session_id": "hellod",
    #     "container_cleared": true
    # }
    result = refresh_session_controller(session_id)
    return {"message": "Session refreshed successfully", **result}


@router.delete("/delete-upload")
async def delete_upload_endpoint(session_id: str, file_name: str):
    result = delete_upload_controller(session_id, file_name)
    return {"message": "File deleted successfully", **result}



@router.post("/stream-graph")
async def stream_graph_endpoint(request: ChatRequest):
    try:
        obj = stream_graph_controller(
            session_id=request.session_id,
            user_query=request.user_query,
            uploaded_files=[f.model_dump() for f in request.uploaded_files],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(obj, media_type="text/event-stream")