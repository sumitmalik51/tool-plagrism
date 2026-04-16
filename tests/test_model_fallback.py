"""Tests for multi-model fallback in the general rewriter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.tools.general_rewriter import _call_openai


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int = 200, content: str = '["v1", "v2", "v3"]') -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = content
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return resp


# ---------------------------------------------------------------------------
# Primary model succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_primary_model_succeeds() -> None:
    mock_resp = _mock_response(200, '["rewrite1"]')

    with patch("app.tools.general_rewriter.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        result = await _call_openai("system", "user")

    assert result == '["rewrite1"]'


# ---------------------------------------------------------------------------
# Primary model rate limited → fallback succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_on_rate_limit() -> None:
    """When primary returns 429, should try fallback deployment."""
    primary_resp = _mock_response(429, "rate limited")
    fallback_resp = _mock_response(200, '["fallback result"]')

    call_count = 0

    async def mock_post(url, json, headers):
        nonlocal call_count
        call_count += 1
        if "gpt-4o-mini" in url:
            return fallback_resp
        return primary_resp

    with patch("app.tools.general_rewriter.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        result = await _call_openai("system", "user")

    assert result == '["fallback result"]'


# ---------------------------------------------------------------------------
# Primary model 503 → fallback succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_on_503() -> None:
    """When primary returns 503, should try fallback deployment."""
    primary_resp = _mock_response(503, "service unavailable")
    fallback_resp = _mock_response(200, '["ok"]')

    async def mock_post(url, json, headers):
        if "gpt-4o-mini" in url:
            return fallback_resp
        return primary_resp

    with patch("app.tools.general_rewriter.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        result = await _call_openai("system", "user")

    assert result == '["ok"]'


# ---------------------------------------------------------------------------
# Both models fail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_both_models_fail() -> None:
    """When both primary and fallback fail, should raise."""
    error_resp = _mock_response(500, "server error")

    async def mock_post(url, json, headers):
        return error_resp

    with patch("app.tools.general_rewriter.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        with pytest.raises(RuntimeError):
            await _call_openai("system", "user")


# ---------------------------------------------------------------------------
# Fallback config — same as primary (no fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_fallback_when_same_deployment() -> None:
    """When fallback == primary, no fallback should be attempted."""
    with patch("app.tools.general_rewriter.settings") as mock_settings:
        mock_settings.azure_openai_endpoint = "https://test.openai.azure.com"
        mock_settings.azure_openai_api_key = "test-key"
        mock_settings.azure_openai_deployment = "gpt-4o"
        mock_settings.azure_openai_fallback_deployment = "gpt-4o"  # same
        mock_settings.azure_openai_api_version = "2025-01-01-preview"
        mock_settings.rewriter_max_tokens = 4096

        error_resp = _mock_response(500, "error")

        with patch("app.tools.general_rewriter.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=error_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            with pytest.raises(RuntimeError):
                await _call_openai("system", "user")
