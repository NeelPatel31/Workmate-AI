from typing import List

from fastapi import APIRouter, File, Form, UploadFile as FastAPIUploadFile
from pydantic import BaseModel, Field

from ..controllers.file_operations import (
    download_file,
    refresh_session as refresh_session_controller,
    upload_file as upload_file_controller,
)

router = APIRouter()

class UploadedFile(BaseModel):
    file_name: str
    file_path: str

class ChatRequest(BaseModel):
    user_query: str
    session_id: str
    uploaded_files: List[UploadedFile] = Field(default_factory=list)

@router.post("/chat")
async def chat(request: ChatRequest):
    return {"message": "Hello World"}


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