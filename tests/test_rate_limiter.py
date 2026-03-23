"""Tests for the scan rate limiter and rate-limit dependency."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse

from app.services.rate_limiter import ScanRateLimiter, UserTier, LimitExceeded, limiter
from app.dependencies.rate_limit import enforce_scan_limit, record_scan


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests — ScanRateLimiter
# ═══════════════════════════════════════════════════════════════════════════


class TestScanRateLimiter:
    """Tests for the in-memory rate limiter."""

    def setup_method(self):
        self.rl = ScanRateLimiter()

    # --- Basic counter ---

    def test_initial_count_is_zero(self):
        assert self.rl.get_count("user:1") == 0

    def test_increment(self):
        assert self.rl.increment("user:1") == 1
        assert self.rl.increment("user:1") == 2
        assert self.rl.get_count("user:1") == 2

    def test_separate_identifiers(self):
        self.rl.increment("user:1")
        self.rl.increment("ip:10.0.0.1")
        assert self.rl.get_count("user:1") == 1
        assert self.rl.get_count("ip:10.0.0.1") == 1

    # --- Remaining scans ---

    @patch("app.services.rate_limiter.settings")
    def test_remaining_free(self, mock_settings):
        mock_settings.scan_limit_free = 3
        self.rl.increment("user:1")
        assert self.rl.get_remaining("user:1", UserTier.FREE) == 2

    @patch("app.services.rate_limiter.settings")
    def test_remaining_anonymous(self, mock_settings):
        mock_settings.scan_limit_anonymous = 3
        assert self.rl.get_remaining("ip:1.2.3.4", UserTier.ANONYMOUS) == 3

    def test_remaining_paid_is_unlimited(self):
        assert self.rl.get_remaining("user:99", UserTier.PAID) == -1

    @patch("app.services.rate_limiter.settings")
    def test_remaining_never_negative(self, mock_settings):
        mock_settings.scan_limit_free = 2
        self.rl.increment("user:1")
        self.rl.increment("user:1")
        self.rl.increment("user:1")  # over limit
        assert self.rl.get_remaining("user:1", UserTier.FREE) == 0

    # --- Check (raises) ---

    @patch("app.services.rate_limiter.settings")
    def test_check_allows_under_limit(self, mock_settings):
        mock_settings.scan_limit_free = 3
        remaining = self.rl.check("user:1", UserTier.FREE)
        assert remaining == 3

    @patch("app.services.rate_limiter.settings")
    def test_check_raises_at_limit(self, mock_settings):
        mock_settings.scan_limit_free = 2
        self.rl.increment("user:1")
        self.rl.increment("user:1")
        with pytest.raises(LimitExceeded) as exc_info:
            self.rl.check("user:1", UserTier.FREE)
        assert exc_info.value.limit == 2

    def test_check_paid_always_passes(self):
        # Even with lots of scans, paid users are unlimited
        for _ in range(100):
            self.rl.increment("user:pro")
        assert self.rl.check("user:pro", UserTier.PAID) == -1

    @patch("app.services.rate_limiter.settings")
    def test_check_anonymous_at_limit(self, mock_settings):
        mock_settings.scan_limit_anonymous = 3
        for _ in range(3):
            self.rl.increment("ip:5.5.5.5")
        with pytest.raises(LimitExceeded):
            self.rl.check("ip:5.5.5.5", UserTier.ANONYMOUS)

    # --- Cleanup ---

    def test_cleanup_removes_old_entries(self):
        # Manually insert an "old" key
        self.rl._store["scan_count:user:1:2020-01-01"] = 5
        self.rl.increment("user:2")  # today's entry
        removed = self.rl.cleanup_old_entries()
        assert removed == 1
        assert "scan_count:user:1:2020-01-01" not in self.rl._store
        assert self.rl.get_count("user:2") == 1

    def test_reset_clears_all(self):
        self.rl.increment("user:1")
        self.rl.increment("ip:1.1.1.1")
        self.rl.reset()
        assert self.rl.get_count("user:1") == 0
        assert self.rl.get_count("ip:1.1.1.1") == 0


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests — FastAPI dependency
# ═══════════════════════════════════════════════════════════════════════════


def _make_test_app():
    """Create a tiny FastAPI app with rate-limited endpoint for testing."""
    app = FastAPI()

    @app.post("/scan", dependencies=[Depends(enforce_scan_limit)])
    async def scan(request: Request):
        remaining = record_scan(request)
        return {"ok": True, "remaining": remaining}

    return app


class TestRateLimitDependency:
    """Integration tests using a TestClient."""

    def setup_method(self):
        limiter.reset()

    @patch("app.dependencies.rate_limit.get_user_by_id", return_value=None)
    @patch("app.services.rate_limiter.settings")
    def test_anonymous_allowed_within_limit(self, mock_settings, mock_get_user):
        mock_settings.scan_limit_anonymous = 3
        mock_settings.scan_limit_free = 3
        app = _make_test_app()
        client = TestClient(app)
        resp = client.post("/scan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["remaining"] == 2

    @patch("app.dependencies.rate_limit.get_user_by_id", return_value=None)
    @patch("app.services.rate_limiter.settings")
    def test_anonymous_blocked_at_limit(self, mock_settings, mock_get_user):
        mock_settings.scan_limit_anonymous = 2
        mock_settings.scan_limit_free = 2
        app = _make_test_app()
        client = TestClient(app)
        # Use up quotas
        client.post("/scan")
        client.post("/scan")
        # Third should be blocked
        resp = client.post("/scan")
        assert resp.status_code == 429
        detail = resp.json()["detail"]
        assert detail["error"] == "limit_reached"
        assert detail["remaining"] == 0

    @patch("app.dependencies.rate_limit.get_user_by_id", return_value={"id": 1, "is_paid": 0})
    @patch("app.services.rate_limiter.settings")
    def test_free_user_blocked_at_limit(self, mock_settings, mock_get_user):
        mock_settings.scan_limit_free = 1
        mock_settings.scan_limit_anonymous = 1
        app = _make_test_app()
        client = TestClient(app)

        # Simulate authenticated user by setting state
        @app.middleware("http")
        async def set_user(request: Request, call_next):
            request.state.user_id = 1
            return await call_next(request)

        client = TestClient(app)
        client.post("/scan")
        resp = client.post("/scan")
        assert resp.status_code == 429

    @patch("app.dependencies.rate_limit.get_user_by_id", return_value={"id": 2, "is_paid": 1})
    @patch("app.services.rate_limiter.settings")
    def test_paid_user_unlimited(self, mock_settings, mock_get_user):
        mock_settings.scan_limit_free = 1
        mock_settings.scan_limit_anonymous = 1
        app = _make_test_app()

        @app.middleware("http")
        async def set_user(request: Request, call_next):
            request.state.user_id = 2
            return await call_next(request)

        client = TestClient(app)
        # Even many scans should not be blocked
        for _ in range(10):
            resp = client.post("/scan")
            assert resp.status_code == 200
            assert resp.json()["remaining"] == -1


# ═══════════════════════════════════════════════════════════════════════════
# UserTier enum
# ═══════════════════════════════════════════════════════════════════════════


class TestUserTier:
    def test_values(self):
        assert UserTier.ANONYMOUS == "anonymous"
        assert UserTier.FREE == "free"
        assert UserTier.PAID == "paid"

    def test_is_string_enum(self):
        assert isinstance(UserTier.ANONYMOUS, str)
