"""Tests for Stripe payment routes."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

STRIPE_PREFIX = "/api/v1/stripe"


# ---------------------------------------------------------------------------
# List plans (public, no auth)
# ---------------------------------------------------------------------------

class TestStripePlans:
    def test_list_plans_returns_all_plans(self) -> None:
        resp = client.get(f"{STRIPE_PREFIX}/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert "plans" in data
        plans = data["plans"]
        assert len(plans) == 4  # pro_monthly, pro_yearly, premium_monthly, premium_yearly

        plan_ids = {p["id"] for p in plans}
        assert "pro_monthly" in plan_ids
        assert "pro_yearly" in plan_ids
        assert "premium_monthly" in plan_ids
        assert "premium_yearly" in plan_ids

    def test_plans_have_required_fields(self) -> None:
        resp = client.get(f"{STRIPE_PREFIX}/plans")
        data = resp.json()
        for plan in data["plans"]:
            assert "id" in plan
            assert "name" in plan
            assert "price_usd" in plan
            assert "price_display" in plan
            assert "interval" in plan
            assert "tier" in plan
            assert "features" in plan
            assert isinstance(plan["features"], list)
            assert plan["price_usd"] > 0

    def test_plans_prices_are_reasonable(self) -> None:
        resp = client.get(f"{STRIPE_PREFIX}/plans")
        for plan in resp.json()["plans"]:
            # All prices should be in cents and positive
            assert plan["price_usd"] > 0
            assert "$" in plan["price_display"]


# ---------------------------------------------------------------------------
# Create checkout session (requires auth)
# ---------------------------------------------------------------------------

class TestStripeCheckout:
    def test_checkout_requires_auth(self) -> None:
        with patch("app.routes.stripe_payments._get_stripe"):
            resp = client.post(
                f"{STRIPE_PREFIX}/create-checkout",
                json={"plan_id": "pro_monthly"},
            )
            # 401 (no user) or 503 (Stripe not configured) both acceptable
            assert resp.status_code in (401, 503)

    def test_checkout_invalid_plan(self) -> None:
        """Even if auth is somehow present, invalid plan should be rejected."""
        with patch("app.routes.stripe_payments._get_stripe"):
            resp = client.post(
                f"{STRIPE_PREFIX}/create-checkout",
                json={"plan_id": "nonexistent_plan"},
            )
            # Should fail with 400 or 401 (auth checked first)
            assert resp.status_code in (400, 401)


# ---------------------------------------------------------------------------
# Customer portal (requires auth)
# ---------------------------------------------------------------------------

class TestStripePortal:
    def test_portal_requires_auth(self) -> None:
        with patch("app.routes.stripe_payments._get_stripe"):
            resp = client.post(f"{STRIPE_PREFIX}/portal")
            # 401 (no user) or 503 (Stripe not configured) both acceptable
            assert resp.status_code in (401, 503)


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

class TestStripeWebhook:
    @patch("app.routes.stripe_payments._get_stripe")
    def test_webhook_rejects_invalid_signature(self, mock_stripe) -> None:
        mock_stripe_mod = MagicMock()
        mock_stripe_mod.Webhook.construct_event.side_effect = Exception("Invalid signature")
        mock_stripe.return_value = mock_stripe_mod

        with patch("app.routes.stripe_payments.settings") as s:
            s.stripe_secret_key = "sk_test_fake"
            s.stripe_webhook_secret = "whsec_test"

            resp = client.post(
                f"{STRIPE_PREFIX}/webhook",
                content=b'{"type": "checkout.session.completed"}',
                headers={"stripe-signature": "invalid_sig"},
            )
            assert resp.status_code == 400

    @patch("app.routes.stripe_payments.get_db")
    @patch("app.routes.stripe_payments._get_stripe")
    def test_webhook_checkout_completed_upgrades_user(self, mock_stripe, mock_db) -> None:
        mock_stripe_mod = MagicMock()
        mock_stripe_mod.Webhook.construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "customer": "cus_test_456",
                    "metadata": {
                        "pg_user_id": "42",
                        "pg_tier": "pro",
                    },
                }
            },
        }
        mock_stripe.return_value = mock_stripe_mod

        mock_instance = MagicMock()
        tx_conn = mock_instance.transaction.return_value.__enter__.return_value
        cursor = tx_conn.cursor.return_value
        cursor.fetchone.return_value = None
        mock_db.return_value = mock_instance

        with patch("app.routes.stripe_payments.settings") as s:
            s.stripe_secret_key = "sk_test_fake"
            s.stripe_webhook_secret = "whsec_test"

            resp = client.post(
                f"{STRIPE_PREFIX}/webhook",
                content=b'{"test": true}',
                headers={"stripe-signature": "valid"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            # Verify DB was called inside one transaction (UPDATE users + SELECT + INSERT payments)
            assert mock_instance.transaction.called
            assert cursor.execute.call_count == 3
            update_call = cursor.execute.call_args_list[0]
            assert "UPDATE users SET plan" in update_call[0][0]
            insert_call = cursor.execute.call_args_list[2]
            assert "INSERT INTO payments" in insert_call[0][0]

    @patch("app.routes.stripe_payments.get_db")
    @patch("app.routes.stripe_payments._get_stripe")
    def test_webhook_subscription_deleted_downgrades(self, mock_stripe, mock_db) -> None:
        mock_stripe_mod = MagicMock()
        mock_stripe_mod.Webhook.construct_event.return_value = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_test_123",
                    "customer": "cus_test_456",
                }
            },
        }
        mock_stripe.return_value = mock_stripe_mod

        mock_instance = MagicMock()
        mock_db.return_value = mock_instance

        with patch("app.routes.stripe_payments.settings") as s:
            s.stripe_secret_key = "sk_test_fake"
            s.stripe_webhook_secret = "whsec_test"

            resp = client.post(
                f"{STRIPE_PREFIX}/webhook",
                content=b'{"test": true}',
                headers={"stripe-signature": "valid"},
            )
            assert resp.status_code == 200
            # Should downgrade to free
            mock_instance.execute.assert_called_once()
            call_args = mock_instance.execute.call_args
            assert "free" in str(call_args)

    def test_webhook_no_secret_configured_returns_500(self) -> None:
        with patch("app.routes.stripe_payments._get_stripe") as mock_stripe:
            mock_stripe.return_value = MagicMock()
            with patch("app.routes.stripe_payments.settings") as s:
                s.stripe_secret_key = "sk_test_fake"
                s.stripe_webhook_secret = ""

                resp = client.post(
                    f"{STRIPE_PREFIX}/webhook",
                    content=b'{}',
                    headers={"stripe-signature": "test"},
                )
                assert resp.status_code == 500
