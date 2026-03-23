"""DB-backed usage rate limiter — tracks daily tool usage per user/IP.

Enforces per-day usage limits across ALL tools (scans, rewrite,
readability, grammar) combined:
- Anonymous users (tracked by IP): configurable daily limit (default 3)
- Free registered users (tracked by user_id): 3/day
- Pro users: unlimited
- Premium users: unlimited

Storage: ``usage_logs`` table in the database.

Usage::

    from app.services.rate_limiter import limiter

    remaining = limiter.check("user:42", UserTier.FREE)
    limiter.record_usage("user:42", "scan", user_id=42)
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class UserTier(str, Enum):
    """User subscription tier."""
    ANONYMOUS = "anonymous"
    FREE = "free"
    PRO = "pro"
    PREMIUM = "premium"


# Backwards-compat alias so existing code referencing PAID keeps working
UserTier.PAID = UserTier.PRO  # type: ignore[attr-defined]


# Map plan_type strings → UserTier
PLAN_TO_TIER: dict[str, UserTier] = {
    "free": UserTier.FREE,
    "pro": UserTier.PRO,
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
    """

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get_count(self, identifier: str) -> int:
        """Return the total tool‐usage count for *identifier* today."""
        from app.services.database import get_db
        db = get_db()
        today = self._today()

        if identifier.startswith("user:"):
            raw = identifier.split(":", 1)[1]
            try:
                user_id = int(raw)
                row = db.fetch_one(
                    "SELECT COUNT(*) AS cnt FROM usage_logs "
                    "WHERE user_id = ? AND CAST(created_at AS DATE) = CAST(? AS DATE)",
                    (user_id, today),
                )
            except ValueError:
                # Non-numeric user identifier (e.g. tests with "user:pro")
                # Fall back to ip_address-based lookup using the raw identifier
                row = db.fetch_one(
                    "SELECT COUNT(*) AS cnt FROM usage_logs "
                    "WHERE ip_address = ? AND CAST(created_at AS DATE) = CAST(? AS DATE)",
                    (identifier, today),
                )
        else:
            # ip:x.x.x.x
            ip = identifier.split(":", 1)[1]
            row = db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM usage_logs "
                "WHERE ip_address = ? AND user_id IS NULL "
                "AND CAST(created_at AS DATE) = CAST(? AS DATE)",
                (ip, today),
            )

        return row["cnt"] if row else 0

    def record_usage(
        self,
        identifier: str,
        tool_type: str,
        *,
        user_id: int | None = None,
        ip_address: str | None = None,
    ) -> int:
        """Insert a usage_log row and return the new daily count."""
        from app.services.database import get_db
        db = get_db()

        db.execute(
            "INSERT INTO usage_logs (user_id, ip_address, tool_type) VALUES (?, ?, ?)",
            (user_id, ip_address, tool_type),
        )

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

    def get_remaining(self, identifier: str, tier: UserTier) -> int:
        """Return how many uses remain for *identifier* today.

        Returns ``-1`` for pro/premium users (unlimited).
        """
        if tier in (UserTier.PRO, UserTier.PREMIUM):
            return -1  # unlimited

        limit = self._limit_for_tier(tier)
        used = self.get_count(identifier)
        return max(limit - used, 0)

    def check(self, identifier: str, tier: UserTier) -> int:
        """Check whether *identifier* can still use tools today.

        Returns the number of remaining uses.
        Raises ``LimitExceeded`` if 0 remaining.
        """
        if tier in (UserTier.PRO, UserTier.PREMIUM):
            return -1  # unlimited

        remaining = self.get_remaining(identifier, tier)
        if remaining <= 0:
            limit = self._limit_for_tier(tier)
            tomorrow = date.today().isoformat()
            raise LimitExceeded(
                limit=limit,
                resets_at=f"{tomorrow}T00:00:00Z (next day)",
            )

        return remaining

    # ------------------------------------------------------------------
    # Housekeeping (kept for API compat / tests)
    # ------------------------------------------------------------------

    def cleanup_old_entries(self) -> int:
        """No-op — DB handles retention. Kept for API compatibility."""
        return 0

    def reset(self) -> None:
        """Clear all usage_logs (useful in tests)."""
        from app.services.database import get_db
        try:
            db = get_db()
            db.execute("DELETE FROM usage_logs")
        except Exception:
            pass  # DB not initialised yet

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    @staticmethod
    def _limit_for_tier(tier: UserTier) -> int:
        if tier == UserTier.ANONYMOUS:
            return settings.scan_limit_anonymous
        if tier == UserTier.FREE:
            return settings.scan_limit_free
        return 0  # PRO/PREMIUM — never called


# Backwards-compatible alias
ScanRateLimiter = UsageRateLimiter

# ═══════════════════════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════════════════════

limiter = UsageRateLimiter()
