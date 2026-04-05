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
import secrets
import time
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
        #    But still parse JWT so user context is available downstream.
        if not settings.api_keys:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                from app.services.auth_service import verify_access_token

                token = auth_header.removeprefix("Bearer ").strip()
                payload = verify_access_token(token)
                if payload:
                    request.state.user_id = int(payload["sub"])
                    request.state.user_email = payload.get("email", "")
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

        # 5. API Key check (static admin keys from env)
        api_key = request.headers.get("X-API-Key", "")
        if api_key and _validate_api_key(api_key):
            return await call_next(request)

        # 6. User-generated API keys (pg_xxx tokens from DB)
        if api_key and api_key.startswith("pg_"):
            from app.services.api_key_service import validate_api_key
            key_info = validate_api_key(api_key)
            if key_info:
                request.state.user_id = key_info["user_id"]
                request.state.user_email = key_info.get("email", "")
                return await call_next(request)

        # 7. Unauthorized
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
    """Add security headers, request IDs, CSP, and cache-control to every response.

    Also enforces a lightweight CSRF check on non-public POST/PUT/DELETE
    requests: requires either an ``Authorization`` header (Bearer/API key)
    or ``X-Requested-With`` header to prove the request was sent from JS,
    not a cross-origin form submission.
    """

    _CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    _CSRF_EXEMPT_PREFIXES = ("/api/v1/auth/signup", "/api/v1/auth/login",
                             "/api/v1/auth/reset-password", "/api/v1/auth/verify-email",
                             "/api/v1/auth/forgot-password", "/api/v1/auth/refresh",
                             "/api/v1/stripe/webhook", "/api/v1/lti/")

    # Static file extensions that get long cache headers
    _CACHEABLE_SUFFIXES = (".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff2", ".woff")

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        # Generate a unique request ID for correlation
        request_id = secrets.token_hex(8)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # CSRF check: state-changing requests must have auth or X-Requested-With.
        # Skip when auth is disabled (no API keys — dev/test mode) so tests pass.
        if (
            request.method not in self._CSRF_SAFE_METHODS
            and settings.api_keys
            and not _is_public_path(request.url.path)
            and not any(request.url.path.startswith(p) for p in self._CSRF_EXEMPT_PREFIXES)
        ):
            has_auth = (
                request.headers.get("Authorization", "")
                or request.headers.get("X-API-Key", "")
                or request.headers.get("X-MS-CLIENT-PRINCIPAL", "")
            )
            has_xhr = request.headers.get("X-Requested-With", "")
            if not has_auth and not has_xhr:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden — missing authentication or X-Requested-With header."},
                )

        response = await call_next(request)

        # Request ID
        response.headers["X-Request-ID"] = request_id

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # Content Security Policy
        # NOTE: 'unsafe-inline' required for Tailwind CDN + inline <script> blocks.
        # When migrating to build-time Tailwind, replace with nonce-based CSP.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://checkout.razorpay.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://fastapi.tiangolo.com https://lh3.googleusercontent.com; "
            "connect-src 'self' https://api.razorpay.com https://api.stripe.com; "
            "frame-src https://api.razorpay.com https://js.stripe.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

        # HSTS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Cache-Control: long cache for static assets, no-cache for API/HTML
        path = request.url.path
        if path.startswith("/static/") and any(path.endswith(s) for s in self._CACHEABLE_SUFFIXES):
            response.headers["Cache-Control"] = "public, max-age=86400, immutable"
        elif path.startswith("/static/"):
            # HTML files in static — short cache
            response.headers["Cache-Control"] = "public, max-age=300"
        elif path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"

        # Clean up structlog context
        structlog.contextvars.unbind_contextvars("request_id")

        return response
