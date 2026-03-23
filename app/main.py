"""PlagiarismGuard — FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.middleware import AuthMiddleware, SecurityHeadersMiddleware
from app.routes.analyze import router as analyze_router
from app.routes.rewrite import router as rewrite_router
from app.routes.tools import router as tools_router
from app.routes.upload import router as upload_router
from app.routes.writing import router as writing_router
from app.utils.logger import setup_logging, get_logger

STATIC_DIR = Path(__file__).parent / "static"

_logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: runs setup on startup and teardown on shutdown."""
    setup_logging(settings.log_level)
    # Preload the embedding model so first request doesn't timeout
    from app.tools.embedding_tool import preload_model
    preload_model()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered multi-agent plagiarism detection system",
    lifespan=lifespan,
)

# --- CORS (needed for Foundry agents calling cross-origin) -------------------
_allowed_origins = [
    "https://plagiarismguard-jl6yu5wij5mu4.azurewebsites.net",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
if settings.debug:
    _allowed_origins = ["*"]  # wide-open in dev mode

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Security middleware (outermost = runs last, innermost = runs first) ------
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuthMiddleware)

# --- Register routers --------------------------------------------------------
app.include_router(upload_router)
app.include_router(analyze_router)
app.include_router(rewrite_router)
app.include_router(tools_router)
app.include_router(writing_router)


# --- Global exception handler ------------------------------------------------
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions — return sanitized 500 response."""
    _logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."},
    )


# --- OpenAPI Foundry spec -----------------------------------------------------
@app.get("/openai-foundry.json", include_in_schema=False)
async def get_openapi_foundry() -> JSONResponse:
    """Serve the OpenAPI spec for Azure Foundry Agent."""
    import json
    import logging

    # Try multiple candidate paths (covers local dev + Azure App Service)
    candidates = [
        Path(__file__).resolve().parent.parent / "openai-foundry.json",   # relative to app/
        Path("/home/site/wwwroot/openai-foundry.json"),                   # Azure absolute
        Path.cwd() / "openai-foundry.json",                              # cwd-relative
    ]

    for spec_path in candidates:
        if spec_path.is_file():
            with open(spec_path, "r") as f:
                data = json.load(f)
            return JSONResponse(content=data)

    tried = [str(p) for p in candidates]
    logging.error("openai-foundry.json not found. Tried: %s", tried)
    return JSONResponse(content={"error": "spec not found", "searched": tried}, status_code=404)


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
