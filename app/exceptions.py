"""Custom application exceptions with structured error responses.

Provides consistent HTTP status codes and error schemas across all endpoints.
"""

from __future__ import annotations


class AppError(Exception):
    """Base application exception."""

    status_code: int = 500
    error_type: str = "internal_error"
    detail: str = "An unexpected error occurred"

    def __init__(self, detail: str | None = None, **kwargs):
        if detail:
            self.detail = detail
        self.extra = kwargs
        super().__init__(self.detail)


class ValidationError(AppError):
    """Input validation failed (HTTP 400)."""

    status_code = 400
    error_type = "validation_error"
    detail = "Input validation failed"


class AuthenticationError(AppError):
    """Authentication failed — invalid token or missing credentials (HTTP 401)."""

    status_code = 401
    error_type = "authentication_error"
    detail = "Authentication failed"


class AuthorizationError(AppError):
    """Authorization failed — user lacks required permissions (HTTP 403)."""

    status_code = 403
    error_type = "authorization_error"
    detail = "Insufficient permissions"


class NotFoundError(AppError):
    """Resource not found (HTTP 404)."""

    status_code = 404
    error_type = "not_found_error"
    detail = "Resource not found"


class RateLimitError(AppError):
    """Rate limit exceeded (HTTP 429)."""

    status_code = 429
    error_type = "rate_limit_error"
    detail = "Daily usage limit exceeded"

    def __init__(self, limit: int, resets_at: str, **kwargs):
        super().__init__(
            f"Usage limit ({limit}) exceeded. Resets at {resets_at}.",
            limit=limit,
            resets_at=resets_at,
            **kwargs
        )


class ExternalServiceError(AppError):
    """External API call failed (HTTP 503)."""

    status_code = 503
    error_type = "external_service_error"
    detail = "External service unavailable"

    def __init__(self, service_name: str | None = None, detail: str | None = None, **kwargs):
        if service_name:
            msg = f"{service_name} service unavailable"
            if detail:
                msg = f"{msg}: {detail}"
            super().__init__(msg, service=service_name, **kwargs)
        else:
            super().__init__(detail or self.detail, **kwargs)


class InternalError(AppError):
    """Internal server error (HTTP 500)."""

    status_code = 500
    error_type = "internal_error"
    detail = "Internal server error"
