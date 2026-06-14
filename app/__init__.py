from fastapi import FastAPI
from .utils import logger

from .api.routes import router

app = FastAPI(
    title="Workmate-AI",
    description="Claude-style AI workspace for working with files. Upload documents, execute tools, generate artifacts, run code in a sandbox, and build complex workflows through an extensible agent architecture.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

app.include_router(router)