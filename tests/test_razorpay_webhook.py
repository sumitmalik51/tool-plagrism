"""Tests for the Razorpay webhook endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.auth_service import get_user_by_id, signup
from app.services.database import get_db

client = TestClient(app, raise_server_exceptions=False)

WEBHOOK_URL = "/api/v1/auth/razorpay-webhook"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_db():
    db = get_db()
    db.execute("DELETE FROM shared_reports")
    db.execute("DELETE FROM payments")
    db.execute("DELETE FROM document_fingerprints")
    db.execute("DELETE FROM scans")
    db.execute("DELETE FROM documents")
    db.execute("DELETE FROM user_api_keys")
    db.execute("DELETE FROM users")
    yield


@pytest.fixture()
def _configure_razorpay():
    """Temporarily set razorpay keys for testing."""
    original_id = settings.razorpay_key_id
    original_secret = settings.razorpay_key_secret
    original_webhook = getattr(settings, "razorpay_webhook_secret", "")
    object.__setattr__(settings, "razorpay_key_id", "rzp_test_123")
    object.__setattr__(settings, "razorpay_key_secret", "test_webhook_secret")
    object.__setattr__(settings, "razorpay_webhook_secret", "test_webhook_secret")
    yield "test_webhook_secret"
    object.__setattr__(settings, "razorpay_key_id", original_id)
    object.__setattr__(settings, "razorpay_key_secret", original_secret)
    object.__setattr__(settings, "razorpay_webhook_secret", original_webhook)


def _sign_payload(payload: dict, secret: str) -> str:
    """Generate a valid Razorpay webhook signature for a payload."""
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _make_payment_payload(event: str, order_id: str, payment_id: str,
                          user_id: str = "", plan: str = "") -> dict:
    """Build a Razorpay-style webhook payload."""
    return {
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "notes": {
                        "user_id": user_id,
                        "plan": plan,
                    },
                }
            }
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWebhookSignatureValidation:
    def test_missing_signature_header(self, _configure_razorpay):
        payload = _make_payment_payload("payment.captured", "order_1", "pay_1")
        resp = client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 400
        assert "Missing signature" in resp.json()["detail"]

    def test_invalid_signature(self, _configure_razorpay):
        payload = _make_payment_payload("payment.captured", "order_1", "pay_1")
        resp = client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-Razorpay-Signature": "bad_sig"},
        )
        assert resp.status_code == 400
        assert "Invalid signature" in resp.json()["detail"]

    def test_valid_signature_accepted(self, _configure_razorpay):
        secret = _configure_razorpay
        payload = _make_payment_payload("payment.captured", "order_1", "pay_1")
        sig = _sign_payload(payload, secret)
        resp = client.post(
            WEBHOOK_URL,
            content=json.dumps(payload, separators=(",", ":")),
            headers={
                "X-Razorpay-Signature": sig,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestWebhookPaymentCaptured:
    def test_upgrades_user_plan(self, _configure_razorpay):
        """payment.captured should upgrade the user's plan."""
        secret = _configure_razorpay
        result = signup("Test", "webhook@test.com", "secret123")
        user_id = result["user"]["id"]

        # Insert a payment record (simulates what create-order does)
        db = get_db()
        db.execute(
            "INSERT INTO payments (user_id, razorpay_order_id, plan_name, amount, currency, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, "order_wh_1", "pro", 29900, "INR", "created"),
        )

        payload = _make_payment_payload(
            "payment.captured", "order_wh_1", "pay_wh_1",
            user_id=str(user_id), plan="pro",
        )
        sig = _sign_payload(payload, secret)
        resp = client.post(
            WEBHOOK_URL,
            content=json.dumps(payload, separators=(",", ":")),
            headers={
                "X-Razorpay-Signature": sig,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

        # Verify user plan was upgraded
        from app.services.auth_service import get_user_by_id
        user = get_user_by_id(user_id)
        assert user["plan_type"] == "pro"

        # Verify payment record was updated
        payment = db.fetch_one(
            "SELECT status, razorpay_payment_id FROM payments WHERE razorpay_order_id = ?",
            ("order_wh_1",),
        )
        assert payment["status"] == "paid"
        assert payment["razorpay_payment_id"] == "pay_wh_1"

    def test_idempotent_double_webhook(self, _configure_razorpay):
        """Receiving the same webhook twice should not cause errors."""
        secret = _configure_razorpay
        result = signup("Test2", "webhook2@test.com", "secret123")
        user_id = result["user"]["id"]

        db = get_db()
        db.execute(
            "INSERT INTO payments (user_id, razorpay_order_id, plan_name, amount, currency, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, "order_wh_2", "premium", 59900, "INR", "created"),
        )

        payload = _make_payment_payload(
            "payment.captured", "order_wh_2", "pay_wh_2",
            user_id=str(user_id), plan="premium",
        )
        sig = _sign_payload(payload, secret)
        headers = {
            "X-Razorpay-Signature": sig,
            "Content-Type": "application/json",
        }
        body = json.dumps(payload, separators=(",", ":"))

        # Send twice
        resp1 = client.post(WEBHOOK_URL, content=body, headers=headers)
        resp2 = client.post(WEBHOOK_URL, content=body, headers=headers)
        assert resp1.status_code == 200
        assert resp2.status_code == 200

        user = get_user_by_id(user_id)
        assert user["plan_type"] == "premium"


class TestWebhookPaymentFailed:
    def test_marks_payment_as_failed(self, _configure_razorpay):
        """payment.failed should update the payment status."""
        secret = _configure_razorpay
        result = signup("Test3", "webhook3@test.com", "secret123")
        user_id = result["user"]["id"]

        db = get_db()
        # Ensure user starts on 'free' plan for this test
        db.execute("UPDATE users SET plan_type = 'free' WHERE id = ?", (user_id,))
        db.execute(
            "INSERT INTO payments (user_id, razorpay_order_id, plan_name, amount, currency, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, "order_wh_3", "pro", 29900, "INR", "created"),
        )

        payload = _make_payment_payload(
            "payment.failed", "order_wh_3", "pay_wh_3",
            user_id=str(user_id), plan="pro",
        )
        sig = _sign_payload(payload, secret)
        resp = client.post(
            WEBHOOK_URL,
            content=json.dumps(payload, separators=(",", ":")),
            headers={
                "X-Razorpay-Signature": sig,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

        payment = db.fetch_one(
            "SELECT status FROM payments WHERE razorpay_order_id = ?",
            ("order_wh_3",),
        )
        assert payment["status"] == "failed"

        # User should still be on free plan
        user = get_user_by_id(user_id)
        assert user["plan_type"] == "free"


class TestWebhookNotConfigured:
    def test_returns_503_when_no_secret(self):
        """Webhook should return 503 if no secret is configured."""
        original_secret = settings.razorpay_key_secret
        original_webhook = getattr(settings, "razorpay_webhook_secret", "")
        object.__setattr__(settings, "razorpay_key_secret", "")
        object.__setattr__(settings, "razorpay_webhook_secret", "")
        try:
            resp = client.post(WEBHOOK_URL, json={"event": "payment.captured"})
            assert resp.status_code == 503
        finally:
            object.__setattr__(settings, "razorpay_key_secret", original_secret)
            object.__setattr__(settings, "razorpay_webhook_secret", original_webhook)
