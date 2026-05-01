"""PlagiarismGuard — FastAPI application entry point."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.middleware import AuthMiddleware, SecurityHeadersMiddleware
from app.routes.admin import router as admin_router
from app.routes.analyze import router as analyze_router
from app.routes.auth import router as auth_router
from app.routes.rewrite import router as rewrite_router
from app.routes.tools import router as tools_router
from app.routes.upload import router as upload_router
from app.routes.writing import router as writing_router
from app.routes.advanced import router as advanced_router
from app.routes.teams import router as teams_router
from app.routes.webhooks import router as webhooks_router
from app.routes.lms import router as lms_router
from app.routes.stripe_payments import router as stripe_router
from app.routes.chatbot import router as chatbot_router
from app.routes.research_writer import router as research_writer_router
from app.routes.jobs import router as jobs_router
from app.utils.logger import setup_logging, get_logger

STATIC_DIR = Path(__file__).parent / "static"

_logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: runs setup on startup and teardown on shutdown."""
    setup_logging(settings.log_level)
    import threading

    # Preload the embedding model in background so the app answers health
    # checks immediately (Azure kills containers that don't respond in 10 min).
    from app.tools.embedding_tool import preload_model
    threading.Thread(target=preload_model, daemon=True, name="model-preload").start()

    # Initialise database in background — Azure SQL serverless can take
    # 10-15 s to wake from auto-pause; doing this synchronously blocks the
    # entire app startup.  First request that needs the DB will wait via
    # the get_db() lazy singleton, so nothing is lost.
    def _init_db():
        try:
            from app.services.database import get_db
            get_db()
        except Exception as exc:
            _logger.warning("db_init_deferred", error=str(exc)[:120])

    threading.Thread(target=_init_db, daemon=True, name="db-init").start()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered multi-agent plagiarism detection system",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# --- CORS (needed for Foundry agents calling cross-origin) -------------------
# Origins are derived from settings (env-driven) so a domain change is not a
# code change. `app_base_url` is the canonical prod origin; `cors_extra_origins`
# (comma-separated) lets ops add staging / preview hosts without redeploying
# code. Debug mode adds local dev origins.
_allowed_origins: list[str] = []
if settings.app_base_url:
    _allowed_origins.append(settings.app_base_url.rstrip("/"))
if settings.cors_extra_origins:
    _allowed_origins.extend(
        o.strip().rstrip("/") for o in settings.cors_extra_origins.split(",") if o.strip()
    )
if settings.debug:
    _allowed_origins.extend([
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])
# De-dupe while preserving order.
_allowed_origins = list(dict.fromkeys(_allowed_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GZip compression for API responses (skip SSE streams) ---
from starlette.middleware.gzip import GZipMiddleware


class _SSEAwareGZip(GZipMiddleware):
    """GZip that skips text/event-stream responses (SSE must not be compressed)."""

    async def __call__(self, scope, receive, send):  # type: ignore[override]
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/v1/scan-progress"):
            # Bypass gzip entirely so SSE events are flushed immediately
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


app.add_middleware(_SSEAwareGZip, minimum_size=1000)

# --- Security middleware (outermost = runs last, innermost = runs first) ------
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuthMiddleware)

# --- Register routers --------------------------------------------------------
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(upload_router)
app.include_router(analyze_router)
app.include_router(rewrite_router)
app.include_router(tools_router)
app.include_router(writing_router)
app.include_router(advanced_router)
app.include_router(teams_router)
app.include_router(webhooks_router)
app.include_router(lms_router)
app.include_router(stripe_router)
app.include_router(chatbot_router)
app.include_router(research_writer_router)
app.include_router(jobs_router)


# --- Custom OpenAPI schema with security schemes -----------------------------
def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token from /api/v1/auth/login. Enter: YOUR_TOKEN (no 'Bearer' prefix needed)",
        },
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key from your dashboard (pg_xxx…)",
        },
    }
    # Apply both auth methods globally so the Authorize button works for all endpoints
    schema["security"] = [
        {"BearerAuth": []},
        {"ApiKeyAuth": []},
    ]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi  # type: ignore[assignment]
# --- Global exception handlers -----------------------------------------------
@app.exception_handler(Exception)
async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle custom application exceptions with structured responses."""
    from app.exceptions import AppError
    
    if isinstance(exc, AppError):
        _logger.warning(
            f"{exc.error_type}_raised",
            path=request.url.path,
            method=request.method,
            error_type=exc.error_type,
            detail=str(exc),
            extra=getattr(exc, 'extra', {}),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "type": exc.error_type,
                "status_code": exc.status_code,
                **getattr(exc, 'extra', {})
            },
        )
    
    # Fallback for unhandled exceptions
    _logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error. Please try again later.",
            "type": "internal_error",
            "status_code": 500,
        },
    )


# --- OpenAPI Foundry spec -----------------------------------------------------
@app.get("/openai-foundry.json", include_in_schema=False)
async def get_openapi_foundry() -> JSONResponse:
    """Serve the OpenAPI spec for Azure Foundry Agent."""
    import json
    import logging

    # Try multiple candidate paths (covers local dev + Azure App Service).
    # We deliberately do NOT include `Path.cwd()` — if the process happens to
    # be launched from a writable / world-readable directory, that becomes a
    # path-confusion footgun. The two pinned candidates cover every supported
    # deployment.
    candidates = [
        Path(__file__).resolve().parent.parent / "openai-foundry.json",   # relative to app/
        Path("/home/site/wwwroot/openai-foundry.json"),                   # Azure absolute
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


# Map URL path -> (filename, optional media type). Drives both the route
# registration loop below AND any future page-listing UI. Adding a page is a
# one-line edit instead of an 8-line handler block.
_STATIC_PAGES: list[tuple[str, str, str | None]] = [
    ("/",                "landing.html",         None),
    ("/app",             "index.html",           None),
    ("/login",           "login.html",           None),
    ("/signup",          "signup.html",          None),
    ("/admin",           "admin.html",           None),
    ("/history",         "history.html",         None),
    ("/api-docs",        "api-docs.html",        None),
    ("/batch",           "batch.html",           None),
    ("/highlight",       "highlight.html",       None),
    ("/compare",         "compare.html",         None),
    ("/research-writer", "research-writer.html", None),
    ("/pricing",         "pricing.html",         None),
    ("/terms",           "terms.html",           None),
    ("/privacy",         "privacy.html",         None),
    ("/about",           "about.html",           None),
    ("/forgot-password", "forgot-password.html", None),
    ("/verify-email",    "verify-email.html",    None),
    ("/robots.txt",      "robots.txt",           "text/plain"),
    ("/sitemap.xml",     "sitemap.xml",          "application/xml"),
]


def _make_static_handler(filename: str, media_type: str | None):
    """Build a closure that serves a single file. Closure captures by value
    via default args so all 19 routes don't end up serving the last filename
    in the loop (Python late-binding gotcha)."""
    target = STATIC_DIR / filename

    if media_type:
        async def _handler(_filename: str = filename, _mt: str = media_type) -> FileResponse:
            return FileResponse(target, media_type=_mt)
    else:
        async def _handler(_filename: str = filename) -> FileResponse:
            return FileResponse(target)

    _handler.__name__ = f"serve_{filename.replace('.', '_').replace('-', '_')}"
    _handler.__doc__ = f"Serve static page {filename}."
    return _handler


for _path, _file, _mt in _STATIC_PAGES:
    app.add_api_route(
        _path,
        _make_static_handler(_file, _mt),
        methods=["GET"],
        include_in_schema=False,
    )


# --- Health check -------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health_check() -> JSONResponse:
    """Liveness probe — always cheap, never blocks the event loop.

    Returns 200 when the process is up. Database connectivity is reported
    in the body but does not affect status (use /health/ready for that).
    """
    return JSONResponse(
        content={
            "status": "healthy",
            "version": settings.app_version,
        },
    )


@app.get("/health/ready", tags=["system"])
async def readiness_check() -> JSONResponse:
    """Readiness probe — 503 when DB is unreachable so load balancers depool us.

    The DB call is dispatched to a worker thread so an Azure SQL serverless
    cold start (30–60 s) does not block uvicorn's event loop.
    """
    import asyncio

    start = time.time()
    db_status = "connected"
    try:
        from app.services.database import get_db

        def _ping() -> None:
            db = get_db()
            db.fetch_one("SELECT 1", ())

        await asyncio.wait_for(asyncio.to_thread(_ping), timeout=5.0)
    except Exception:
        db_status = "error"

    elapsed_ms = round((time.time() - start) * 1000, 1)
    body = {
        "status": "healthy" if db_status == "connected" else "degraded",
        "version": settings.app_version,
        "db": db_status,
        "response_time_ms": elapsed_ms,
    }
    return JSONResponse(content=body, status_code=200 if db_status == "connected" else 503)
