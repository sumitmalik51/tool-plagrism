"""Tests for webhook subscription routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

WEBHOOKS_PREFIX = "/api/v1/webhooks"

_FAKE_USER_PAYLOAD = {"sub": "42", "email": "test@example.com"}


def _auth_header(token: str = "fake-jwt") -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth checks
# ---------------------------------------------------------------------------

class TestWebhooksAuth:
    def test_create_webhook_requires_auth(self) -> None:
        resp = client.post(WEBHOOKS_PREFIX, json={"url": "https://example.com/hook"})
        assert resp.status_code == 401

    def test_list_webhooks_requires_auth(self) -> None:
        resp = client.get(WEBHOOKS_PREFIX)
        assert resp.status_code == 401

    def test_delete_webhook_requires_auth(self) -> None:
        resp = client.delete(f"{WEBHOOKS_PREFIX}/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Create webhook
# ---------------------------------------------------------------------------

class TestCreateWebhook:
    @patch("app.routes.webhooks.get_db")
    @patch("app.routes.webhooks.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_create_webhook_success(self, mock_verify, mock_db) -> None:
        mock_instance = MagicMock()
        mock_instance.fetch_all.return_value = []  # no existing webhooks
        mock_instance.execute.return_value = 1  # new webhook id
        mock_db.return_value = mock_instance

        resp = client.post(
            WEBHOOKS_PREFIX,
            json={"url": "https://example.com/hook", "events": ["scan.complete"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://example.com/hook"
        assert "secret" in data
        assert len(data["secret"]) == 64  # hex of 32 bytes

    @patch("app.routes.webhooks.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_create_webhook_requires_https(self, mock_verify) -> None:
        resp = client.post(
            WEBHOOKS_PREFIX,
            json={"url": "http://insecure.com/hook"},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    @patch("app.routes.webhooks.get_db")
    @patch("app.routes.webhooks.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_create_webhook_max_5_limit(self, mock_verify, mock_db) -> None:
        mock_instance = MagicMock()
        mock_instance.fetch_all.return_value = [{"id": i} for i in range(5)]
        mock_db.return_value = mock_instance

        resp = client.post(
            WEBHOOKS_PREFIX,
            json={"url": "https://example.com/hook6"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "Maximum 5" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# List webhooks
# ---------------------------------------------------------------------------

class TestListWebhooks:
    @patch("app.routes.webhooks.get_db")
    @patch("app.routes.webhooks.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_list_webhooks_returns_array(self, mock_verify, mock_db) -> None:
        mock_instance = MagicMock()
        mock_instance.fetch_all.return_value = [
            {"id": 1, "url": "https://a.com/hook", "events": "scan.complete", "is_active": 1, "created_at": "2024-01-01"},
        ]
        mock_db.return_value = mock_instance

        resp = client.get(WEBHOOKS_PREFIX, headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["webhooks"]) == 1
        assert data["webhooks"][0]["events"] == ["scan.complete"]


# ---------------------------------------------------------------------------
# Delete webhook
# ---------------------------------------------------------------------------

class TestDeleteWebhook:
    @patch("app.routes.webhooks.get_db")
    @patch("app.routes.webhooks.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_delete_own_webhook(self, mock_verify, mock_db) -> None:
        mock_instance = MagicMock()
        mock_instance.fetch_one.return_value = {"user_id": 42}
        mock_db.return_value = mock_instance

        resp = client.delete(f"{WEBHOOKS_PREFIX}/1", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    @patch("app.routes.webhooks.get_db")
    @patch("app.routes.webhooks.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_delete_other_user_webhook_returns_404(self, mock_verify, mock_db) -> None:
        mock_instance = MagicMock()
        mock_instance.fetch_one.return_value = {"user_id": 99}  # different user
        mock_db.return_value = mock_instance

        resp = client.delete(f"{WEBHOOKS_PREFIX}/1", headers=_auth_header())
        assert resp.status_code == 404

    @patch("app.routes.webhooks.get_db")
    @patch("app.routes.webhooks.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_delete_nonexistent_webhook_returns_404(self, mock_verify, mock_db) -> None:
        mock_instance = MagicMock()
        mock_instance.fetch_one.return_value = None
        mock_db.return_value = mock_instance

        resp = client.delete(f"{WEBHOOKS_PREFIX}/999", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# fire_webhooks helper (unit test)
# ---------------------------------------------------------------------------

class TestFireWebhooks:
    @pytest.mark.asyncio
    @patch("app.routes.webhooks.httpx.AsyncClient")
    @patch("app.routes.webhooks.get_db")
    async def test_fire_webhooks_sends_signed_payload(self, mock_db, mock_client_cls) -> None:
        from app.routes.webhooks import fire_webhooks

        mock_instance = MagicMock()
        mock_instance.fetch_all.return_value = [
            {"url": "https://example.com/hook", "secret": "abc123", "events": "scan.complete"},
        ]
        mock_db.return_value = mock_instance

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await fire_webhooks(42, "scan.complete", {"score": 25.0})

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        # Verify signature header is present
        headers = call_kwargs.kwargs.get("headers", {}) if call_kwargs.kwargs else call_kwargs[1].get("headers", {})
        assert "X-PlagiarismGuard-Signature" in headers
        assert headers["X-PlagiarismGuard-Signature"].startswith("sha256=")
