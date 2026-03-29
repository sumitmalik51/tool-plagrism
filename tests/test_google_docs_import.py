"""Tests for the Google Docs import endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

VALID_GDOC_URL = "https://docs.google.com/document/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ/edit"
INVALID_URL = "https://example.com/not-a-doc"


def _mock_response(status_code: int = 200, text: str = "Sample document text."):
    """Create a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


class TestGoogleDocsImport:
    @patch("app.routes.upload.httpx.AsyncClient")
    def test_import_success(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(200, "Hello from Google Docs!"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        res = client.post(
            "/api/v1/import-google-doc",
            json={"url": VALID_GDOC_URL},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["text"] == "Hello from Google Docs!"
        assert data["char_count"] == len("Hello from Google Docs!")
        assert "source" in data

    def test_invalid_url(self):
        res = client.post(
            "/api/v1/import-google-doc",
            json={"url": INVALID_URL},
        )
        assert res.status_code == 400
        assert "Invalid Google Docs URL" in res.json()["detail"]

    @patch("app.routes.upload.httpx.AsyncClient")
    def test_not_found(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(404))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        res = client.post(
            "/api/v1/import-google-doc",
            json={"url": VALID_GDOC_URL},
        )
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    @patch("app.routes.upload.httpx.AsyncClient")
    def test_not_shared(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(403))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        res = client.post(
            "/api/v1/import-google-doc",
            json={"url": VALID_GDOC_URL},
        )
        assert res.status_code == 403
        assert "not publicly shared" in res.json()["detail"].lower()

    @patch("app.routes.upload.httpx.AsyncClient")
    def test_empty_document(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(200, "   "))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        res = client.post(
            "/api/v1/import-google-doc",
            json={"url": VALID_GDOC_URL},
        )
        assert res.status_code == 422
        assert "empty" in res.json()["detail"].lower()

    @patch("app.routes.upload.httpx.AsyncClient")
    def test_text_truncated_at_limit(self, mock_client_cls):
        big_text = "x" * 600_000
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(200, big_text))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        res = client.post(
            "/api/v1/import-google-doc",
            json={"url": VALID_GDOC_URL},
        )
        assert res.status_code == 200
        assert res.json()["char_count"] == 500_000

    def test_missing_url(self):
        res = client.post(
            "/api/v1/import-google-doc",
            json={},
        )
        assert res.status_code == 422

    @patch("app.routes.upload.httpx.AsyncClient")
    def test_server_error(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(500))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        res = client.post(
            "/api/v1/import-google-doc",
            json={"url": VALID_GDOC_URL},
        )
        assert res.status_code == 502
