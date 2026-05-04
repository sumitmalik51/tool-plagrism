"""Tests for the Research Writer Credit Pack add-on."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.auth_service import (
    add_rw_credits,
    deduct_rw_credit,
    get_rw_credits,
    signup,
)
from app.services.database import get_db

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_db():
    db = get_db()
    db.execute("DELETE FROM rw_credits")
    db.execute("DELETE FROM usage_logs")
    db.execute("DELETE FROM payments")
    db.execute("DELETE FROM shared_reports")
    db.execute("DELETE FROM document_fingerprints")
    db.execute("DELETE FROM scans")
    db.execute("DELETE FROM documents")
    db.execute("DELETE FROM user_api_keys")
    db.execute("DELETE FROM users")
    yield


@pytest.fixture()
def user_token():
    """Create a user and return (user_id, token) tuple."""
    result = signup("Credits Test", "credits@test.com", "secret123")
    return result["user"]["id"], result["token"]


@pytest.fixture()
def _configure_razorpay():
    """Temporarily set razorpay keys for testing."""
    original_id = settings.razorpay_key_id
    original_secret = settings.razorpay_key_secret
    original_webhook = getattr(settings, "razorpay_webhook_secret", "")
    object.__setattr__(settings, "razorpay_key_id", "rzp_test_123")
    object.__setattr__(settings, "razorpay_key_secret", "test_secret_key")
    object.__setattr__(settings, "razorpay_webhook_secret", "test_secret_key")
    yield "test_secret_key"
    object.__setattr__(settings, "razorpay_key_id", original_id)
    object.__setattr__(settings, "razorpay_key_secret", original_secret)
    object.__setattr__(settings, "razorpay_webhook_secret", original_webhook)


# ---------------------------------------------------------------------------
# Credit helper unit tests
# ---------------------------------------------------------------------------

class TestCreditHelpers:
    def test_get_rw_credits_empty(self, user_token):
        uid, _ = user_token
        assert get_rw_credits(uid) == 0

    def test_add_and_get_credits(self, user_token):
        uid, _ = user_token
        total = add_rw_credits(uid, 100, "order_test_1", "pay_test_1")
        assert total == 100
        assert get_rw_credits(uid) == 100

    def test_deduct_credit_success(self, user_token):
        uid, _ = user_token
        add_rw_credits(uid, 100, "order_test_2", "pay_test_2")
        assert deduct_rw_credit(uid, 2) is True
        assert get_rw_credits(uid) == 98

    def test_deduct_credit_insufficient(self, user_token):
        uid, _ = user_token
        add_rw_credits(uid, 1, "order_test_3", "pay_test_3")
        assert deduct_rw_credit(uid, 5) is False

    def test_deduct_zero_credits(self, user_token):
        uid, _ = user_token
        # No credits added — deduction should fail
        assert deduct_rw_credit(uid) is False

    def test_fifo_deduction(self, user_token):
        """Credits should be deducted from the oldest pack first."""
        uid, _ = user_token
        add_rw_credits(uid, 3, "order_old", "pay_old")
        add_rw_credits(uid, 10, "order_new", "pay_new")

        assert get_rw_credits(uid) == 13
        deduct_rw_credit(uid, 5)  # Takes 3 from old + 2 from new
        assert get_rw_credits(uid) == 8

        # Verify the old pack is zeroed out
        db = get_db()
        old = db.fetch_one(
            "SELECT credits_remaining FROM rw_credits WHERE razorpay_order_id = 'order_old'",
        )
        assert old["credits_remaining"] == 0

    def test_multiple_packs_accumulate(self, user_token):
        uid, _ = user_token
        add_rw_credits(uid, 50, "order_a", "pay_a")
        add_rw_credits(uid, 50, "order_b", "pay_b")
        assert get_rw_credits(uid) == 100


# ---------------------------------------------------------------------------
# Rate limit credit fallback tests
# ---------------------------------------------------------------------------

class TestCreditFallbackInRateLimit:
    def test_limiter_blocks_after_limit(self, user_token):
        """Verify limiter raises LimitExceeded after daily limit is used."""
        uid, _ = user_token

        from app.services.rate_limiter import limiter, UserTier, LimitExceeded

        for _ in range(settings.rw_generate_limit_free):
            limiter.record_usage(f"user:{uid}", "rw_generate", user_id=uid)

        with pytest.raises(LimitExceeded):
            limiter.check(f"user:{uid}", UserTier.FREE, "rw_generate")

    def test_enforce_rw_limit_uses_credits_on_exhaust(self, user_token):
        """The enforce_rw_limit dependency should deduct credits when
        daily limit is exhausted instead of raising 429."""
        uid, token = user_token
        add_rw_credits(uid, 10, "order_rl_1", "pay_rl_1")

        from unittest.mock import MagicMock
        from app.dependencies.rate_limit import enforce_rw_limit
        from app.services.rate_limiter import LimitExceeded
        import asyncio

        mock_state = MagicMock()
        mock_state.user_id = uid
        mock_request = MagicMock()
        mock_request.state = mock_state
        mock_request.headers = {"Authorization": f"Bearer {token}"}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        dep = enforce_rw_limit("rw_generate")

        # Mock limiter.check to raise LimitExceeded (simulates exhausted daily limit)
        with patch(
            "app.dependencies.rate_limit.limiter.check",
            side_effect=LimitExceeded(limit=3, resets_at="2099-01-01"),
        ):
            loop = asyncio.new_event_loop()
            loop.run_until_complete(dep(mock_request))
            loop.close()

        # Credits should have been deducted (cost=2 for generate)
        remaining = get_rw_credits(uid)
        assert remaining == 10 - settings.rw_credit_cost_generate
        # Sentinel value should be set on request state
        assert mock_request.state.rate_limit_remaining == -2

    def test_enforce_rw_limit_429_when_no_credits(self, user_token):
        """When daily limit exhausted AND no credits, should raise 429."""
        uid, token = user_token

        from unittest.mock import MagicMock
        from app.dependencies.rate_limit import enforce_rw_limit
        from app.services.rate_limiter import LimitExceeded
        from fastapi import HTTPException
        import asyncio

        mock_state = MagicMock()
        mock_state.user_id = uid
        mock_request = MagicMock()
        mock_request.state = mock_state
        mock_request.headers = {"Authorization": f"Bearer {token}"}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        dep = enforce_rw_limit("rw_generate")

        # Mock limiter.check to raise LimitExceeded and no credits purchased
        with patch(
            "app.dependencies.rate_limit.limiter.check",
            side_effect=LimitExceeded(limit=3, resets_at="2099-01-01"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(dep(mock_request))
                finally:
                    loop.close()
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestGetCreditsEndpoint:
    def test_returns_zero_for_new_user(self, user_token):
        _, token = user_token
        resp = client.get(
            "/api/v1/auth/rw-credits",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["credits"] == 0

    def test_returns_credit_balance(self, user_token):
        uid, token = user_token
        add_rw_credits(uid, 50, "order_ep_1", "pay_ep_1")

        resp = client.get(
            "/api/v1/auth/rw-credits",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["credits"] == 50

    def test_unauthenticated(self):
        resp = client.get("/api/v1/auth/rw-credits")
        assert resp.status_code in (401, 403)


class TestCreateAddonOrderEndpoint:
    def test_unauthenticated(self):
        resp = client.post("/api/v1/auth/create-addon-order")
        assert resp.status_code in (401, 403)

    def test_creates_order(self, user_token, _configure_razorpay):
        _, token = user_token

        mock_order = {"id": "order_addon_test"}
        with patch("app.routes.auth._get_razorpay_client") as mock_client:
            mock_client.return_value.order.create.return_value = mock_order
            resp = client.post(
                "/api/v1/auth/create-addon-order",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["order_id"] == "order_addon_test"
        assert data["amount"] == settings.rw_credit_pack_amount
        assert data["credits"] == settings.rw_credit_pack_size
        assert data["addon"] == "rw_credit_pack"
        assert data["razorpay_key"] == "rzp_test_123"

        # Verify DB record created with status='created'
        db = get_db()
        row = db.fetch_one(
            "SELECT * FROM rw_credits WHERE razorpay_order_id = 'order_addon_test'",
        )
        assert row is not None
        assert row["status"] == "created"
        assert row["credits_remaining"] == 0  # Not yet paid


class TestVerifyAddonPaymentEndpoint:
    def test_valid_signature_activates_credits(self, user_token, _configure_razorpay):
        uid, token = user_token
        secret = _configure_razorpay

        # Insert a pending credit pack
        db = get_db()
        db.execute(
            "INSERT INTO rw_credits (user_id, credits_remaining, credits_purchased, "
            "razorpay_order_id, status) VALUES (?, 0, 100, 'order_vp_1', 'created')",
            (uid,),
        )

        # Build valid signature
        order_id = "order_vp_1"
        payment_id = "pay_vp_1"
        message = f"{order_id}|{payment_id}"
        sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

        resp = client.post(
            "/api/v1/auth/verify-addon-payment",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": sig,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["credits_added"] == 100
        assert data["total_credits"] == 100

        # DB record should be 'paid' with credits_remaining filled
        row = db.fetch_one(
            "SELECT * FROM rw_credits WHERE razorpay_order_id = 'order_vp_1'",
        )
        assert row["status"] == "paid"
        assert row["credits_remaining"] == 100

    def test_invalid_signature_rejects(self, user_token, _configure_razorpay):
        uid, token = user_token

        db = get_db()
        db.execute(
            "INSERT INTO rw_credits (user_id, credits_remaining, credits_purchased, "
            "razorpay_order_id, status) VALUES (?, 0, 100, 'order_vp_2', 'created')",
            (uid,),
        )

        resp = client.post(
            "/api/v1/auth/verify-addon-payment",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "razorpay_order_id": "order_vp_2",
                "razorpay_payment_id": "pay_vp_2",
                "razorpay_signature": "invalid_signature",
            },
        )
        assert resp.status_code == 400

        # DB should be marked failed
        row = db.fetch_one(
            "SELECT status FROM rw_credits WHERE razorpay_order_id = 'order_vp_2'",
        )
        assert row["status"] == "failed"

    def test_valid_signature_rejects_wrong_owner(self, user_token, _configure_razorpay):
        owner_uid, _ = user_token
        other = signup("Other Credits", "other-credits@test.com", "secret123")
        other_token = other["token"]
        secret = _configure_razorpay

        db = get_db()
        db.execute(
            "INSERT INTO rw_credits (user_id, credits_remaining, credits_purchased, "
            "razorpay_order_id, status) VALUES (?, 0, 100, 'order_wrong_owner', 'created')",
            (owner_uid,),
        )

        order_id = "order_wrong_owner"
        payment_id = "pay_wrong_owner"
        message = f"{order_id}|{payment_id}"
        sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

        resp = client.post(
            "/api/v1/auth/verify-addon-payment",
            headers={
                "Authorization": f"Bearer {other_token}",
                "Content-Type": "application/json",
            },
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": sig,
            },
        )

        assert resp.status_code == 400
        row = db.fetch_one(
            "SELECT status, credits_remaining FROM rw_credits WHERE razorpay_order_id = 'order_wrong_owner'",
        )
        assert row["status"] == "created"
        assert row["credits_remaining"] == 0

    def test_idempotent_double_verify(self, user_token, _configure_razorpay):
        """Verifying same payment twice should not double credits."""
        uid, token = user_token
        secret = _configure_razorpay

        db = get_db()
        db.execute(
            "INSERT INTO rw_credits (user_id, credits_remaining, credits_purchased, "
            "razorpay_order_id, status) VALUES (?, 0, 100, 'order_vp_3', 'created')",
            (uid,),
        )

        order_id = "order_vp_3"
        payment_id = "pay_vp_3"
        message = f"{order_id}|{payment_id}"
        sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

        body = {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": sig,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        resp1 = client.post("/api/v1/auth/verify-addon-payment", headers=headers, json=body)
        resp2 = client.post("/api/v1/auth/verify-addon-payment", headers=headers, json=body)

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Credits should still be 100, not 200
        assert get_rw_credits(uid) == 100


class TestWebhookAddonCredits:
    """Test that the Razorpay webhook handles addon credit pack payments."""

    def test_webhook_activates_credits(self, user_token, _configure_razorpay):
        uid, token = user_token
        secret = _configure_razorpay

        db = get_db()
        db.execute(
            "INSERT INTO rw_credits (user_id, credits_remaining, credits_purchased, "
            "razorpay_order_id, status) VALUES (?, 0, 100, 'order_wh_addon', 'created')",
            (uid,),
        )

        payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_wh_addon",
                        "order_id": "order_wh_addon",
                        "notes": {
                            "user_id": str(uid),
                            "addon": "rw_credit_pack",
                            "credits": "100",
                        },
                    }
                }
            },
        }
        raw = json.dumps(payload, separators=(",", ":"))
        sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()

        resp = client.post(
            "/api/v1/auth/razorpay-webhook",
            content=raw,
            headers={
                "X-Razorpay-Signature": sig,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

        # Credits should now be active
        row = db.fetch_one(
            "SELECT * FROM rw_credits WHERE razorpay_order_id = 'order_wh_addon'",
        )
        assert row["status"] == "paid"
        assert row["credits_remaining"] == 100


class TestConfigDefaults:
    def test_credit_pack_config(self):
        assert settings.rw_credit_pack_size == 100
        assert settings.rw_credit_pack_amount == 14900
        assert settings.rw_credit_cost_generate == 2
        assert settings.rw_credit_cost_check == 1
        assert settings.rw_credit_cost_expand == 1
        assert settings.rw_credit_cost_improve == 1
        assert settings.rw_credit_cost_caption == 1
