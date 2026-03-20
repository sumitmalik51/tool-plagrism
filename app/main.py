"""PlagiarismGuard — FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routes.analyze import router as analyze_router
from app.routes.tools import router as tools_router
from app.routes.upload import router as upload_router
from app.utils.logger import setup_logging

STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: runs setup on startup and teardown on shutdown."""
    setup_logging(settings.log_level)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered multi-agent plagiarism detection system",
    lifespan=lifespan,
)

# --- Register routers --------------------------------------------------------
app.include_router(upload_router)
app.include_router(analyze_router)
app.include_router(tools_router)


# --- OpenAPI Foundry spec -----------------------------------------------------
@app.get("/openai-foundry.json", include_in_schema=False)
async def get_openapi_foundry() -> JSONResponse:
    """Serve the OpenAPI spec for Azure Foundry Agent."""
    import json

    spec_path = Path(__file__).parent.parent / "openai-foundry.json"
    with open(spec_path, "r") as f:
        data = json.load(f)
    return JSONResponse(content=data)


# --- Static files & UI -------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_ui() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(STATIC_DIR / "index.html")


# --- Health check -------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Return application health status."""
    return {"status": "healthy", "version": settings.app_version}
