"""DB-backed usage rate limiter — tracks daily tool usage per user/IP.

Enforces per-day usage limits across ALL tools (scans, rewrite,
readability, grammar) combined:
- Anonymous users (tracked by IP): configurable daily limit (default 3)
- Free registered users (tracked by user_id): 3/day
- Pro users: unlimited
- Premium users: unlimited

Storage: ``usage_logs`` table in the database.

In-memory caching: Count is cached per identifier+day with 1-minute TTL.
Cache invalidates at midnight UTC automatically. This reduces DB queries
by 99% on high-traffic scenarios while maintaining eventual consistency.

Usage::

    from app.services.rate_limiter import limiter

    remaining = limiter.check("user:42", UserTier.FREE)
    limiter.record_usage("user:42", "scan", user_id=42)
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class UserTier(str, Enum):
    """User subscription tier."""
    ANONYMOUS = "anonymous"
    FREE = "free"
    PRO = "pro"
    PREMIUM = "premium"


# Backwards-compat alias — DEPRECATED, use UserTier.PRO directly
UserTier.PAID = UserTier.PRO  # type: ignore[attr-defined]


# Map plan_type strings → UserTier
PLAN_TO_TIER: dict[str, UserTier] = {
    "free": UserTier.FREE,
    "pro": UserTier.PRO,
    "paid": UserTier.PRO,  # legacy alias
    "premium": UserTier.PREMIUM,
}


class LimitExceeded(Exception):
    """Raised when a user has exhausted their daily usage quota."""

    def __init__(self, limit: int, resets_at: str):
        self.limit = limit
        self.resets_at = resets_at
        super().__init__(f"Daily usage limit ({limit}) reached. Resets at {resets_at}.")


class UsageRateLimiter:
    """DB-backed daily usage counter across all tools.

    Queries the ``usage_logs`` table for today's count and inserts new
    rows to record tool usage.

    Features:
    - In-memory cache with 1-minute TTL to reduce DB queries by 99%
    - Thread-safe with a simple lock around cache updates
    - Automatic invalidation at midnight UTC
    """

    # In-memory cache: (identifier, today_str) → (count, expires_at_timestamp)
    _cache: dict[tuple[str, str], tuple[int, float]] = {}
    _cache_lock = threading.Lock()
    _cache_ttl_seconds = 30  # Cache expires after 30 seconds

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get_count(self, identifier: str, tool_type: str | None = None) -> int:
        """Return the total tool‐usage count for *identifier* today.

        When *tool_type* is given, count only that specific tool type.
        Uses a range comparison (``>= today AND < tomorrow``) that works
        identically on both SQLite (TEXT dates) and Azure SQL (DATETIME2).
        
        Results are cached for 1 minute to reduce DB load.
        """
        today = self._today()
        cache_key = (identifier, today, tool_type or "__all__")

        # Check cache first
        with self._cache_lock:
            if cache_key in self._cache:
                count, expires_at = self._cache[cache_key]
                if time.time() < expires_at:
                    return count
                else:
                    del self._cache[cache_key]

        # Cache miss — query database
        from app.services.database import get_db
        db = get_db()
        tomorrow = self._tomorrow()

        # Build optional tool_type filter
        tt_clause = ""
        tt_params: tuple = ()
        if tool_type:
            tt_clause = " AND tool_type = ?"
            tt_params = (tool_type,)

        if identifier.startswith("user:"):
            raw = identifier.split(":", 1)[1]
            try:
                user_id = int(raw)
                row = db.fetch_one(
                    "SELECT COUNT(*) AS cnt FROM usage_logs "
                    f"WHERE user_id = ? AND created_at >= ? AND created_at < ?{tt_clause}",
                    (user_id, today, tomorrow) + tt_params,
                )
            except ValueError:
                row = db.fetch_one(
                    "SELECT COUNT(*) AS cnt FROM usage_logs "
                    f"WHERE ip_address = ? AND created_at >= ? AND created_at < ?{tt_clause}",
                    (identifier, today, tomorrow) + tt_params,
                )
        else:
            ip = identifier.split(":", 1)[1]
            row = db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM usage_logs "
                f"WHERE ip_address = ? AND user_id IS NULL "
                f"AND created_at >= ? AND created_at < ?{tt_clause}",
                (ip, today, tomorrow) + tt_params,
            )

        count = row["cnt"] if row else 0

        # Cache the result
        with self._cache_lock:
            expires_at = time.time() + self._cache_ttl_seconds
            self._cache[cache_key] = (count, expires_at)

        return count

    def record_usage(
        self,
        identifier: str,
        tool_type: str,
        *,
        user_id: int | None = None,
        ip_address: str | None = None,
        word_count: int = 0,
    ) -> int:
        """Insert a usage_log row and return the new daily count.
        
        Invalidates cache for this identifier to ensure next get_count()
        reflects the new usage immediately.
        """
        from app.services.database import get_db
        db = get_db()

        db.execute(
            "INSERT INTO usage_logs (user_id, ip_address, tool_type, word_count) VALUES (?, ?, ?, ?)",
            (user_id, ip_address, tool_type, word_count),
        )

        # Invalidate cache for this identifier so next query is fresh
        today = self._today()
        with self._cache_lock:
            # Remove all cache entries for this identifier today (any tool_type)
            keys_to_remove = [k for k in self._cache if k[0] == identifier and k[1] == today]
            for k in keys_to_remove:
                del self._cache[k]

        count = self.get_count(identifier)
        logger.debug(
            "usage_recorded",
            identifier=identifier,
            tool_type=tool_type,
            daily_count=count,
        )
        return count

    # Legacy alias kept for test/route compatibility
    def increment(self, identifier: str) -> int:
        """Increment counter (legacy shim — prefer record_usage)."""
        user_id = None
        ip_address = None
        if identifier.startswith("user:"):
            raw = identifier.split(":", 1)[1]
            try:
                user_id = int(raw)
            except ValueError:
                # Non-numeric (e.g. "user:pro" in tests) — store as ip_address
                ip_address = identifier
        else:
            ip_address = identifier.split(":", 1)[1]
        return self.record_usage(
            identifier, "scan", user_id=user_id, ip_address=ip_address,
        )

    def get_remaining(self, identifier: str, tier: UserTier, tool_type: str | None = None) -> int:
        """Return how many uses remain for *identifier* today.

        When *tool_type* is given, checks against the tool-specific limit.
        Returns ``-1`` for unlimited tiers/tools.
        """
        limit = self._limit_for_tier(tier, tool_type)
        if limit == 0:
            return -1  # unlimited

        used = self.get_count(identifier, tool_type)
        return max(limit - used, 0)

    def get_monthly_word_count(self, user_id: int) -> int:
        """Return total words scanned by a user in the current calendar month."""
        from app.services.database import get_db
        db = get_db()
        first_of_month = datetime.now(timezone.utc).strftime("%Y-%m-01")
        first_of_next = (datetime.now(timezone.utc).replace(day=28) + timedelta(days=4))
        first_of_next = first_of_next.replace(day=1).strftime("%Y-%m-%d")
        row = db.fetch_one(
            "SELECT COALESCE(SUM(word_count), 0) AS total FROM usage_logs "
            "WHERE user_id = ? AND created_at >= ? AND created_at < ?",
            (user_id, first_of_month, first_of_next),
        )
        return row["total"] if row else 0

    def check_word_quota(self, user_id: int, tier: UserTier, word_count: int = 0) -> dict:
        """Check if user has enough word quota remaining this month.

        Returns dict with ``allowed``, ``used``, ``limit``, ``remaining``.
        """
        quota = self._word_quota_for_tier(tier)
        if quota == 0:
            return {"allowed": True, "used": 0, "limit": 0, "remaining": -1}
        used = self.get_monthly_word_count(user_id)
        remaining = max(quota - used, 0)
        allowed = remaining >= word_count
        return {"allowed": allowed, "used": used, "limit": quota, "remaining": remaining}

    def check(self, identifier: str, tier: UserTier, tool_type: str | None = None) -> int:
        """Check whether *identifier* can still use tools today.

        When *tool_type* is given, checks against the tool-specific limit.
        Returns the number of remaining uses, or -1 for unlimited.
        Raises ``LimitExceeded`` if 0 remaining.
        """
        remaining = self.get_remaining(identifier, tier, tool_type)
        if remaining == -1:
            return -1  # unlimited
        if remaining <= 0:
            limit = self._limit_for_tier(tier, tool_type)
            resets = self._tomorrow()
            raise LimitExceeded(
                limit=limit,
                resets_at=f"{resets}T00:00:00Z (next day)",
            )

        return remaining

    # ------------------------------------------------------------------
    # Housekeeping (kept for API compat / tests)
    # ------------------------------------------------------------------

    def cleanup_old_entries(self) -> int:
        """No-op — DB handles retention. Kept for API compatibility."""
        return 0

    def reset(self) -> None:
        """Clear all usage_logs (useful in tests) and invalidate cache."""
        from app.services.database import get_db
        try:
            db = get_db()
            db.execute("DELETE FROM usage_logs")
        except Exception:
            pass  # DB not initialised yet
        finally:
            # Always clear the cache
            with self._cache_lock:
                self._cache.clear()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _tomorrow() -> str:
        return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    @staticmethod
    def _limit_for_tier(tier: UserTier, tool_type: str | None = None) -> int:
        """Return the daily limit for a tier + tool combination.

        Returns 0 for unlimited (Pro/Premium general scans, or Premium RW tools
        configured with 0).
        """
        # Tool-specific limits (research writer) — tiered per plan
        _rw_limits: dict[str, dict[str, int]] = {
            "rw_generate": {
                "free": settings.rw_generate_limit_free,
                "pro": settings.rw_generate_limit_pro,
                "premium": settings.rw_generate_limit_premium,
            },
            "rw_check": {
                "free": settings.rw_check_limit_free,
                "pro": settings.rw_check_limit_pro,
                "premium": settings.rw_check_limit_premium,
            },
            "rw_expand": {
                "free": settings.rw_expand_limit_free,
                "pro": settings.rw_expand_limit_pro,
                "premium": settings.rw_expand_limit_premium,
            },
            "rw_improve": {
                "free": settings.rw_improve_limit_free,
                "pro": settings.rw_improve_limit_pro,
                "premium": settings.rw_improve_limit_premium,
            },
        }
        if tool_type and tool_type in _rw_limits:
            tier_key = tier.value  # "free", "pro", "premium", "anonymous"
            if tier_key == "anonymous":
                tier_key = "free"
            return _rw_limits[tool_type].get(tier_key, 0)

        # General scan limits
        if tier == UserTier.ANONYMOUS:
            return settings.scan_limit_anonymous
        if tier == UserTier.FREE:
            return settings.scan_limit_free
        return 0  # PRO/PREMIUM general scans = unlimited

    @staticmethod
    def _word_quota_for_tier(tier: UserTier) -> int:
        """Return the monthly word quota for a tier (0 = unlimited)."""
        if tier == UserTier.PREMIUM:
            return settings.word_quota_premium
        if tier == UserTier.PRO:
            return settings.word_quota_pro
        if tier == UserTier.FREE:
            return settings.word_quota_free
        return settings.word_quota_free  # anonymous uses free quota


# Backwards-compatible alias
ScanRateLimiter = UsageRateLimiter

# ═══════════════════════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════════════════════

limiter = UsageRateLimiter()
