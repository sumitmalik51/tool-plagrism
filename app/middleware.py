"""Authentication & security middleware for PlagiarismGuard.

Supports three authentication methods (checked in order):
1. **JWT Bearer token** — ``Authorization: Bearer <token>`` header.
   Issued by the signup/login endpoints for browser-based users.
2. **API Key** — ``X-API-Key`` header checked against ``PG_API_KEYS`` env var.
   For service-to-service calls, CI pipelines, and external integrations.
3. **Azure Easy Auth** — ``X-MS-CLIENT-PRINCIPAL`` header injected by
   App Service Authentication. For browser users signed in via Entra ID.

Public paths (health, docs, static assets, auth endpoints) bypass auth entirely.
"""

from __future__ import annotations

import hmac
import time
import uuid
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Paths that never require authentication
_PUBLIC_PATHS: set[str] = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/openai-foundry.json",
    "/",
    "/login",
    "/signup",
}

# Path prefixes that never require authentication
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/api/v1/auth/",
)


def _is_public_path(path: str) -> bool:
    """Return True if the path should bypass authentication."""
    if path in _PUBLIC_PATHS:
        return True
    return path.startswith(_PUBLIC_PREFIXES)


def _validate_api_key(provided_key: str) -> bool:
    """Constant-time comparison of the provided key against all configured keys."""
    for valid_key in settings.api_keys:
        if hmac.compare_digest(provided_key.encode(), valid_key.encode()):
            return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce authentication on non-public routes.

    Checks (in order):
    1. Is it a public path? → allow
    2. Is auth disabled (no keys configured + not in production)? → allow
    3. Does ``X-MS-CLIENT-PRINCIPAL`` exist? → Azure Easy Auth user → allow
    4. Does ``X-API-Key`` match a configured key? → allow
    5. Otherwise → 401 Unauthorized
    """

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        path = request.url.path

        # 1. Public paths bypass auth
        if _is_public_path(path):
            return await call_next(request)

        # 2. If no API keys are configured, auth is disabled (dev mode)
        if not settings.api_keys:
            return await call_next(request)

        # 3. JWT Bearer token (issued by /api/v1/auth/login & /signup)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            from app.services.auth_service import verify_access_token

            token = auth_header.removeprefix("Bearer ").strip()
            payload = verify_access_token(token)
            if payload:
                # Stash user info on request state for downstream use
                request.state.user_id = int(payload["sub"])
                request.state.user_email = payload.get("email", "")
                return await call_next(request)
            # Invalid/expired token — fall through to other checks

        # 4. Azure Easy Auth — App Service injects this header for
        #    authenticated browser users
        if request.headers.get("X-MS-CLIENT-PRINCIPAL"):
            return await call_next(request)

        # 5. API Key check
        api_key = request.headers.get("X-API-Key", "")
        if api_key and _validate_api_key(api_key):
            return await call_next(request)

        # 6. Unauthorized
        logger.warning(
            "auth_rejected",
            path=path,
            method=request.method,
            client=request.client.host if request.client else "unknown",
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized — provide a valid X-API-Key header."},
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request/response for tracing.

    The ID is read from the ``X-Request-ID`` header if provided by an
    upstream proxy; otherwise a new UUID is generated.  The ID is:

    * stored on ``request.state.request_id``
    * bound to structlog context vars (appears in every log line)
    * echoed back in the ``X-Request-ID`` response header
    """

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
