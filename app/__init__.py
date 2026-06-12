from fastapi import FastAPI
from .utils import logger

from .api.routes import router

app = FastAPI(
    title="Workmate",
    description="Workmate is a platform for AI-powered agents to help you with your work.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

app.include_router(router)