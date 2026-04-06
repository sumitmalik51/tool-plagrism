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
from app.utils.logger import setup_logging, get_logger

STATIC_DIR = Path(__file__).parent / "static"

_logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: runs setup on startup and teardown on shutdown."""
    setup_logging(settings.log_level)
    # Preload the embedding model in background so the app answers health
    # checks immediately (Azure kills containers that don't respond in 10 min).
    import threading
    from app.tools.embedding_tool import preload_model
    threading.Thread(target=preload_model, daemon=True, name="model-preload").start()
    # Initialise database schema (creates tables if needed).
    # Non-fatal: if Azure SQL is temporarily unavailable the app still starts
    # and will connect lazily on first request.
    try:
        from app.services.database import get_db
        get_db()
    except Exception as exc:
        _logger.warning("db_init_deferred", error=str(exc)[:120])
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
_allowed_origins = [
    "https://plagiarismguard-jl6yu5wij5mu4.azurewebsites.net",
]
if settings.debug:
    _allowed_origins.extend([
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GZip compression for API responses ---
from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

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
async def serve_landing() -> FileResponse:
    """Serve the lightweight landing page for guests / SEO."""
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/app", include_in_schema=False)
async def serve_app() -> FileResponse:
    """Serve the full application (dashboard + tools + report)."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
async def serve_login() -> FileResponse:
    """Serve the login page."""
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/signup", include_in_schema=False)
async def serve_signup() -> FileResponse:
    """Serve the signup page."""
    return FileResponse(STATIC_DIR / "signup.html")


@app.get("/admin", include_in_schema=False)
async def serve_admin() -> FileResponse:
    """Serve the admin dashboard page."""
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/history", include_in_schema=False)
async def serve_history() -> FileResponse:
    """Serve the scan history dashboard."""
    return FileResponse(STATIC_DIR / "history.html")


@app.get("/api-docs", include_in_schema=False)
async def serve_api_docs() -> FileResponse:
    """Serve the branded API documentation page."""
    return FileResponse(STATIC_DIR / "api-docs.html")


@app.get("/batch", include_in_schema=False)
async def serve_batch() -> FileResponse:
    """Serve the batch upload page."""
    return FileResponse(STATIC_DIR / "batch.html")


@app.get("/highlight", include_in_schema=False)
async def serve_highlight() -> FileResponse:
    """Serve the Turnitin-style highlight comparison view."""
    return FileResponse(STATIC_DIR / "highlight.html")


@app.get("/compare", include_in_schema=False)
async def serve_compare() -> FileResponse:
    """Serve the scan comparison page."""
    return FileResponse(STATIC_DIR / "compare.html")


@app.get("/pricing", include_in_schema=False)
async def serve_pricing() -> FileResponse:
    """Serve the pricing / subscription page."""
    return FileResponse(STATIC_DIR / "pricing.html")


@app.get("/terms", include_in_schema=False)
async def serve_terms() -> FileResponse:
    """Serve the Terms of Service page."""
    return FileResponse(STATIC_DIR / "terms.html")


@app.get("/privacy", include_in_schema=False)
async def serve_privacy() -> FileResponse:
    """Serve the Privacy Policy page."""
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/forgot-password", include_in_schema=False)
async def serve_forgot_password() -> FileResponse:
    """Serve the forgot-password page."""
    return FileResponse(STATIC_DIR / "forgot-password.html")


@app.get("/verify-email", include_in_schema=False)
async def serve_verify_email() -> FileResponse:
    """Serve the email verification landing page."""
    return FileResponse(STATIC_DIR / "verify-email.html")


@app.get("/robots.txt", include_in_schema=False)
async def serve_robots() -> FileResponse:
    """Serve robots.txt for search engine crawlers."""
    return FileResponse(STATIC_DIR / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def serve_sitemap() -> FileResponse:
    """Serve sitemap.xml for search engine indexing."""
    return FileResponse(STATIC_DIR / "sitemap.xml", media_type="application/xml")


# --- Health check -------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health_check() -> dict[str, Any]:
    """Minimal health check for load balancers and uptime monitors."""
    start = time.time()

    # Quick database connectivity check
    db_status = "connected"
    try:
        from app.services.database import get_db
        db = get_db()
        db.fetch_one("SELECT 1", ())
    except Exception:
        db_status = "error"

    elapsed_ms = round((time.time() - start) * 1000, 1)

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "version": settings.app_version,
        "response_time_ms": elapsed_ms,
    }
