"""FastAPI dependency for usage rate limiting (all tools).

Inject ``Depends(enforce_usage_limit)`` on any tool endpoint to enforce
daily quotas.  The dependency resolves the user tier (anonymous / free /
pro / premium) from the ``plan_type`` column, checks the DB-backed
counter, and raises 429 if the limit is exhausted.

After a successful tool use, call ``record_usage(request, tool_type)``
to insert a row into ``usage_logs``.

The dependency also stashes rate-limit metadata on ``request.state`` so
the route can include ``X-RateLimit-*`` headers in the response.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.auth_service import get_user_by_id
from app.services.rate_limiter import (
    PLAN_TO_TIER,
    LimitExceeded,
    UserTier,
    limiter,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _client_ip(request: Request) -> str:
    """Best-effort client IP (handles X-Forwarded-For behind proxies)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _resolve_identity(request: Request) -> tuple[str, UserTier]:
    """Determine the rate-limit identifier and user tier from the request.

    Works even when the auth middleware is disabled (dev mode) by
    falling back to direct JWT inspection from the Authorization header.

    Returns:
        (identifier, tier) — e.g. (``"user:42"``, ``UserTier.FREE``)
        or (``"ip:1.2.3.4"``, ``UserTier.ANONYMOUS``).
    """
    user_id: int | None = getattr(request.state, "user_id", None)

    # If the auth middleware didn't run (dev mode / no API keys),
    # try to extract user_id from the Bearer token directly.
    if user_id is None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            from app.services.auth_service import verify_access_token
            token = auth_header.removeprefix("Bearer ").strip()
            payload = verify_access_token(token)
            if payload:
                user_id = int(payload["sub"])
                # Stash it so downstream code (record_usage) picks it up
                request.state.user_id = user_id

    if user_id is not None:
        user = get_user_by_id(user_id)
        if user:
            plan = user.get("plan_type", "free")
            tier = PLAN_TO_TIER.get(plan, UserTier.FREE)
            return f"user:{user_id}", tier
        return f"user:{user_id}", UserTier.FREE

    # Anonymous — track by IP
    ip = _client_ip(request)
    return f"ip:{ip}", UserTier.ANONYMOUS


async def enforce_usage_limit(request: Request) -> None:
    """FastAPI dependency — raises 429 if the caller has exceeded their
    daily usage limit across all tools.

    Stashes ``rate_limit_identifier``, ``rate_limit_tier``, and
    ``rate_limit_remaining`` on ``request.state`` for downstream use.
    """
    identifier, tier = _resolve_identity(request)

    # Stash for later use by record_usage / response headers
    request.state.rate_limit_identifier = identifier
    request.state.rate_limit_tier = tier

    try:
        remaining = limiter.check(identifier, tier)
    except LimitExceeded as exc:
        logger.warning(
            "usage_limit_reached",
            identifier=identifier,
            tier=tier.value,
            limit=exc.limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "limit_reached",
                "message": f"Daily usage limit ({exc.limit}) reached. "
                           f"Upgrade your plan for unlimited access.",
                "limit": exc.limit,
                "remaining": 0,
                "resets_at": exc.resets_at,
                "upgrade_url": "/pricing",
            },
        )

    request.state.rate_limit_remaining = remaining


# Legacy alias — keeps existing route code working unchanged
enforce_scan_limit = enforce_usage_limit


def record_usage(request: Request, tool_type: str = "scan") -> int:
    """Record a tool usage after a successful operation.

    Returns the new remaining count (or -1 for unlimited).
    """
    identifier: str = getattr(request.state, "rate_limit_identifier", "")
    tier: UserTier = getattr(request.state, "rate_limit_tier", UserTier.ANONYMOUS)

    if not identifier:
        return -1

    # Determine user_id and ip for the DB row
    user_id: int | None = getattr(request.state, "user_id", None)
    ip_address = _client_ip(request)

    limiter.record_usage(
        identifier,
        tool_type,
        user_id=user_id,
        ip_address=ip_address,
    )
    return limiter.get_remaining(identifier, tier)


# Legacy alias
def record_scan(request: Request) -> int:
    """Legacy shim — records a scan usage."""
    return record_usage(request, tool_type="scan")
