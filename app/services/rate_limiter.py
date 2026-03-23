"""In-memory scan rate limiter — tracks daily scan counts per user/IP.

Enforces per-day scan limits:
- Anonymous users (tracked by IP): configurable daily limit (default 3)
- Free registered users (tracked by user_id): configurable daily limit (default 3)
- Paid / Pro users: unlimited scans

Storage: in-memory dict for now, ready to swap for Redis.
Key format: ``scan_count:{identifier}:{YYYY-MM-DD}``

Usage::

    from app.services.rate_limiter import limiter

    remaining = limiter.check("user:42")   # raises LimitExceeded if 0
    limiter.increment("user:42")
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class UserTier(str, Enum):
    """User subscription tier."""
    ANONYMOUS = "anonymous"
    FREE = "free"
    PAID = "paid"


class LimitExceeded(Exception):
    """Raised when a user has exhausted their daily scan quota."""

    def __init__(self, limit: int, resets_at: str):
        self.limit = limit
        self.resets_at = resets_at
        super().__init__(f"Daily scan limit ({limit}) reached. Resets at {resets_at}.")


class ScanRateLimiter:
    """In-memory daily scan counter.

    Thread-safe. Automatically expires entries from previous days on access.
    Designed as a drop-in that can later be backed by Redis without changing
    the public API.
    """

    def __init__(self) -> None:
        self._store: dict[str, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()  # e.g. "2025-07-15"

    @staticmethod
    def _key(identifier: str, day: str | None = None) -> str:
        """Build a storage key.

        Args:
            identifier: ``ip:<addr>`` for anonymous or ``user:<id>`` for
                        authenticated users.
            day: ISO date string; defaults to today.
        """
        day = day or ScanRateLimiter._today()
        return f"scan_count:{identifier}:{day}"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get_count(self, identifier: str) -> int:
        """Return the current scan count for *identifier* today."""
        key = self._key(identifier)
        with self._lock:
            return self._store.get(key, 0)

    def increment(self, identifier: str) -> int:
        """Increment and return the new scan count for today."""
        key = self._key(identifier)
        with self._lock:
            current = self._store.get(key, 0) + 1
            self._store[key] = current
            logger.debug("rate_limit_increment", identifier=identifier, count=current)
            return current

    def get_remaining(self, identifier: str, tier: UserTier) -> int:
        """Return how many scans remain for *identifier* today.

        Returns ``-1`` for paid users (unlimited).
        """
        if tier == UserTier.PAID:
            return -1  # unlimited

        limit = self._limit_for_tier(tier)
        used = self.get_count(identifier)
        return max(limit - used, 0)

    def check(self, identifier: str, tier: UserTier) -> int:
        """Check whether *identifier* can still scan today.

        Returns the number of remaining scans.
        Raises ``LimitExceeded`` if 0 remaining.
        """
        if tier == UserTier.PAID:
            return -1  # unlimited

        remaining = self.get_remaining(identifier, tier)
        if remaining <= 0:
            limit = self._limit_for_tier(tier)
            # Next reset is midnight UTC tomorrow
            tomorrow = date.today().isoformat()
            raise LimitExceeded(limit=limit, resets_at=f"{tomorrow}T00:00:00Z (next day)")

        return remaining

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def cleanup_old_entries(self) -> int:
        """Remove entries from previous days. Returns count of removed keys."""
        today = self._today()
        with self._lock:
            old_keys = [k for k in self._store if not k.endswith(f":{today}")]
            for k in old_keys:
                del self._store[k]
            if old_keys:
                logger.info("rate_limit_cleanup", removed=len(old_keys))
            return len(old_keys)

    def reset(self) -> None:
        """Clear all entries (useful in tests)."""
        with self._lock:
            self._store.clear()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _limit_for_tier(tier: UserTier) -> int:
        if tier == UserTier.ANONYMOUS:
            return settings.scan_limit_anonymous
        if tier == UserTier.FREE:
            return settings.scan_limit_free
        return 0  # PAID — never called, but satisfy type checker


# ═══════════════════════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════════════════════

limiter = ScanRateLimiter()
