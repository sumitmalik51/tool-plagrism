"""Tests for the chatbot endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

CHATBOT_URL = "/api/v1/chatbot"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestChatbotValidation:
    """Request validation and edge cases."""

    def test_empty_messages_rejected(self) -> None:
        resp = client.post(CHATBOT_URL, json={"messages": []})
        assert resp.status_code == 422

    def test_invalid_role_rejected(self) -> None:
        resp = client.post(
            CHATBOT_URL,
            json={"messages": [{"role": "system", "content": "hi"}]},
        )
        assert resp.status_code == 422

    def test_empty_content_rejected(self) -> None:
        resp = client.post(
            CHATBOT_URL,
            json={"messages": [{"role": "user", "content": ""}]},
        )
        assert resp.status_code == 422

    def test_too_many_messages_rejected(self) -> None:
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(25)]
        resp = client.post(CHATBOT_URL, json={"messages": msgs})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Service unavailable when not configured
# ---------------------------------------------------------------------------

class TestChatbotUnconfigured:
    def test_returns_503_when_openai_not_configured(self) -> None:
        with patch("app.routes.chatbot.settings") as mock_settings:
            mock_settings.azure_openai_endpoint = ""
            mock_settings.azure_openai_api_key = ""
            resp = client.post(
                CHATBOT_URL,
                json={"messages": [{"role": "user", "content": "hello"}]},
            )
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Successful chatbot interaction (mocked OpenAI)
# ---------------------------------------------------------------------------

class TestChatbotSuccess:
    @patch("app.routes.chatbot.httpx.AsyncClient")
    def test_chat_returns_reply(self, mock_client_cls) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {"message": {"content": "PlagiarismGuard supports PDF and DOCX files.\n[INTENT: feature]"}}
            ]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch("app.routes.chatbot.settings") as s:
            s.azure_openai_endpoint = "https://fake.openai.azure.com"
            s.azure_openai_api_key = "fake-key"
            s.azure_openai_deployment = "gpt-4o"
            s.azure_openai_api_version = "2024-06-01"

            resp = client.post(
                CHATBOT_URL,
                json={"messages": [{"role": "user", "content": "what file types do you support?"}]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "reply" in data
            # Intent tag should be stripped from user-visible reply
            assert "[INTENT:" not in data["reply"]

    @patch("app.routes.chatbot.httpx.AsyncClient")
    def test_chat_retries_on_failure(self, mock_client_cls) -> None:
        """Should retry up to MAX_RETRIES times on transient errors."""
        mock_resp_fail = MagicMock()
        mock_resp_fail.status_code = 500
        mock_resp_fail.text = "Internal Server Error"

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {
            "choices": [{"message": {"content": "Hello! [INTENT: feature]"}}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_resp_fail, mock_resp_ok])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch("app.routes.chatbot.settings") as s:
            s.azure_openai_endpoint = "https://fake.openai.azure.com"
            s.azure_openai_api_key = "fake-key"
            s.azure_openai_deployment = "gpt-4o"
            s.azure_openai_api_version = "2024-06-01"

            resp = client.post(
                CHATBOT_URL,
                json={"messages": [{"role": "user", "content": "pricing?"}]},
            )
            # After retry succeeds, we get 200
            assert resp.status_code == 200

    @patch("app.routes.chatbot.httpx.AsyncClient")
    def test_chat_returns_502_after_all_retries_exhausted(self, mock_client_cls) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch("app.routes.chatbot.settings") as s:
            s.azure_openai_endpoint = "https://fake.openai.azure.com"
            s.azure_openai_api_key = "fake-key"
            s.azure_openai_deployment = "gpt-4o"
            s.azure_openai_api_version = "2024-06-01"

            resp = client.post(
                CHATBOT_URL,
                json={"messages": [{"role": "user", "content": "hello"}]},
            )
            assert resp.status_code == 502
