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
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _client_ip(request: Request) -> str:
    """Best-effort client IP (handles X-Forwarded-For behind proxies)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Use rightmost IP (appended by trusted Azure App Service proxy)
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        return parts[-1] if parts else (request.client.host if request.client else "unknown")
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


def record_usage(request: Request, tool_type: str = "scan", word_count: int = 0) -> int:
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
        word_count=word_count,
    )
    return limiter.get_remaining(identifier, tier)


# Legacy alias
def record_scan(request: Request) -> int:
    """Legacy shim — records a scan usage with word count."""
    wc = getattr(request.state, "scan_word_count", 0)
    return record_usage(request, tool_type="scan", word_count=wc)


def get_request_plan_type(request: Request) -> str:
    """Return the current caller's plan type, resolving from JWT/DB if needed."""
    user_id: int | None = getattr(request.state, "user_id", None)
    token_plan: str | None = getattr(request.state, "plan_type", None)
    if user_id is None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            from app.services.auth_service import verify_access_token
            token = auth_header.removeprefix("Bearer ").strip()
            payload = verify_access_token(token)
            if payload:
                user_id = int(payload["sub"])
                request.state.user_id = user_id
                token_plan = payload.get("plan_type") or token_plan

    if user_id is not None:
        user = get_user_by_id(user_id)
        if user:
            plan = user.get("plan_type", "free")
            request.state.plan_type = plan
            return str(plan)

    if token_plan:
        return str(token_plan)

    return "free"


def get_request_tier(request: Request) -> UserTier:
    """Return the current caller's subscription tier."""
    tier = getattr(request.state, "rate_limit_tier", None)
    if isinstance(tier, UserTier):
        return tier
    return PLAN_TO_TIER.get(get_request_plan_type(request), UserTier.FREE)


def enforce_word_quota(request: Request, word_count: int, what: str = "text") -> dict:
    """Raise 429 if the current authenticated user lacks monthly word quota.

    Anonymous callers remain governed by daily IP limits; registered users are
    checked against their tier's monthly word quota.  The word count is stashed
    on ``request.state`` so ``record_scan`` can persist it.
    """
    request.state.scan_word_count = max(int(word_count or 0), 0)

    user_id: int | None = getattr(request.state, "user_id", None)
    if user_id is None:
        _resolve_identity(request)
        user_id = getattr(request.state, "user_id", None)

    if user_id is None:
        return {"allowed": True, "used": 0, "limit": 0, "remaining": -1}

    tier = get_request_tier(request)
    quota = limiter.check_word_quota(user_id, tier, word_count=word_count)
    if quota["allowed"]:
        try:
            from app.services.auth_service import get_word_topup_balance
            quota["topup_remaining"] = get_word_topup_balance(user_id)
        except Exception:
            quota["topup_remaining"] = 0
        return quota

    # Base monthly quota is exhausted or insufficient.  Purchased scan word
    # top-ups cover only the deficit beyond the base monthly allowance, so a
    # user with 1,000 base words remaining and a 2,500-word document spends
    # 1,500 purchased words.
    try:
        from app.services.auth_service import deduct_word_topup, get_word_topup_balance
        deficit = max(int(word_count or 0) - int(quota.get("remaining", 0) or 0), 0)
        topup_balance = get_word_topup_balance(user_id)
        if deficit > 0 and topup_balance >= deficit and deduct_word_topup(user_id, deficit):
            quota["allowed"] = True
            quota["topup_used"] = deficit
            quota["topup_remaining"] = topup_balance - deficit
            return quota
        quota["topup_remaining"] = topup_balance
    except Exception as exc:
        logger.warning("word_topup_check_failed", user_id=user_id, error=str(exc)[:120])

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "word_quota_exceeded",
            "message": (
                f"Monthly word limit reached ({quota['limit']:,} words). "
                f"Used {quota['used']:,}, this {what} has {word_count:,} words."
            ),
            "used": quota["used"],
            "limit": quota["limit"],
            "remaining": quota["remaining"],
            "topup_remaining": quota.get("topup_remaining", 0),
            "upgrade_url": "/pricing",
        },
    )


def stored_text_excerpt(text: str) -> str:
    """Return the bounded document text stored in DB history."""
    limit = max(settings.document_text_storage_chars, 0)
    if limit == 0:
        return text
    return text[:limit]


def enforce_rw_limit(tool_type: str):
    """Factory that returns a FastAPI dependency enforcing a per-tool daily limit.

    When the daily limit is exhausted, falls back to deducting from the
    user's purchased RW credit pack (if any) before raising 429.

    Usage::

        @router.post("/generate", dependencies=[Depends(enforce_rw_limit("rw_generate"))])
        async def generate(...):
            ...
    """
    async def _check(request: Request) -> None:
        identifier, tier = _resolve_identity(request)
        request.state.rate_limit_identifier = identifier
        request.state.rate_limit_tier = tier

        try:
            remaining = limiter.check(identifier, tier, tool_type=tool_type)
            request.state.rate_limit_remaining = remaining
            return
        except LimitExceeded as exc:
            # Daily limit exhausted — try credit pack fallback
            user_id: int | None = getattr(request.state, "user_id", None)
            if user_id is not None:
                from app.config import settings
                from app.services.auth_service import deduct_rw_credit, get_rw_credits

                _cost_map = {
                    "rw_generate": settings.rw_credit_cost_generate,
                    "rw_check": settings.rw_credit_cost_check,
                    "rw_expand": settings.rw_credit_cost_expand,
                    "rw_improve": settings.rw_credit_cost_improve,
                    "rw_caption": settings.rw_credit_cost_caption,
                }
                cost = _cost_map.get(tool_type, 1)
                credits_available = get_rw_credits(user_id)

                if credits_available >= cost:
                    if deduct_rw_credit(user_id, cost):
                        logger.info(
                            "rw_credit_used",
                            user_id=user_id,
                            tool_type=tool_type,
                            cost=cost,
                            credits_after=credits_available - cost,
                        )
                        request.state.rate_limit_remaining = -2  # sentinel: credit used
                        return

            logger.warning(
                "rw_limit_reached",
                identifier=identifier,
                tier=tier.value,
                tool_type=tool_type,
                limit=exc.limit,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "limit_reached",
                    "message": f"Daily {tool_type} limit ({exc.limit}) reached. "
                               f"Purchase a credit pack or upgrade your plan.",
                    "limit": exc.limit,
                    "remaining": 0,
                    "resets_at": exc.resets_at,
                    "upgrade_url": "/pricing",
                },
            )

    return _check
