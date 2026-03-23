"""FastAPI dependency for scan rate limiting.

Inject ``Depends(enforce_scan_limit)`` on any scan endpoint to enforce
daily quotas.  The dependency resolves the user tier (anonymous / free /
paid), checks the in-memory counter, and raises 429 if the limit is
exhausted.

After a successful scan, call ``record_scan(request)`` to increment the
counter.

The dependency also stashes rate-limit metadata on ``request.state`` so the
route can include ``X-RateLimit-*`` headers in the response.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.auth_service import get_user_by_id
from app.services.rate_limiter import LimitExceeded, UserTier, limiter
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

    Returns:
        (identifier, tier) — e.g. (``"user:42"``, ``UserTier.FREE``)
        or (``"ip:1.2.3.4"``, ``UserTier.ANONYMOUS``).
    """
    user_id: int | None = getattr(request.state, "user_id", None)

    if user_id is not None:
        # Authenticated — check if paid
        user = get_user_by_id(user_id)
        if user and user.get("is_paid"):
            return f"user:{user_id}", UserTier.PAID
        return f"user:{user_id}", UserTier.FREE

    # Anonymous — track by IP
    ip = _client_ip(request)
    return f"ip:{ip}", UserTier.ANONYMOUS


async def enforce_scan_limit(request: Request) -> None:
    """FastAPI dependency — raises 429 if the caller has exceeded their
    daily scan limit.

    Stashes ``rate_limit_identifier``, ``rate_limit_tier``, and
    ``rate_limit_remaining`` on ``request.state`` for downstream use.
    """
    identifier, tier = _resolve_identity(request)

    # Stash for later use by record_scan / response headers
    request.state.rate_limit_identifier = identifier
    request.state.rate_limit_tier = tier

    try:
        remaining = limiter.check(identifier, tier)
    except LimitExceeded as exc:
        logger.warning(
            "scan_limit_reached",
            identifier=identifier,
            tier=tier.value,
            limit=exc.limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "limit_reached",
                "message": f"Daily scan limit ({exc.limit}) reached. "
                           f"Resets at midnight UTC.",
                "limit": exc.limit,
                "remaining": 0,
                "resets_at": exc.resets_at,
            },
        )

    request.state.rate_limit_remaining = remaining


def record_scan(request: Request) -> int:
    """Increment the scan counter after a successful scan.

    Returns the new remaining count (or -1 for unlimited).
    """
    identifier: str = getattr(request.state, "rate_limit_identifier", "")
    tier: UserTier = getattr(request.state, "rate_limit_tier", UserTier.ANONYMOUS)

    if not identifier:
        return -1

    limiter.increment(identifier)
    return limiter.get_remaining(identifier, tier)
