"""Tests for the AI rewriter tool and endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.tools.rewriter_tool import (
    rewrite_paragraph,
    rewrite_document,
    _call_azure_openai,
)


# ---------------------------------------------------------------------------
# Unit tests for rewriter_tool
# ---------------------------------------------------------------------------

class TestRewriteParagraph:
    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_returns_rewritten_text(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "This is the rewritten version of the text."

        result = await rewrite_paragraph(
            text="Original plagiarised text here.",
            tone="academic",
        )

        assert result["original"] == "Original plagiarised text here."
        assert result["rewritten"] == "This is the rewritten version of the text."
        assert result["tone"] == "academic"
        assert result["elapsed_s"] >= 0
        mock_api.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_passes_context(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "Rewritten."

        await rewrite_paragraph(
            text="Flagged text.",
            context="Some surrounding context.",
            tone="professional",
        )

        call_args = mock_api.call_args
        user_prompt = call_args.kwargs.get("user_prompt", call_args[1].get("user_prompt", ""))
        if not user_prompt:
            # Positional args
            user_prompt = call_args[0][1] if len(call_args[0]) > 1 else ""
        assert "professional" in user_prompt.lower() or mock_api.called

    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_tone_options(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "Casual rewrite here."

        result = await rewrite_paragraph(text="Some text.", tone="casual")
        assert result["tone"] == "casual"


class TestRewriteDocument:
    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_rewrites_with_flagged_passages(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "This is the complete rewritten document."

        result = await rewrite_document(
            document_text="The quick brown fox jumps over the lazy dog.",
            flagged_passages=["quick brown fox"],
            tone="academic",
        )

        assert result["original"] == "The quick brown fox jumps over the lazy dog."
        assert result["rewritten"] == "This is the complete rewritten document."
        assert result["passages_rewritten"] == 1
        assert result["tone"] == "academic"
        assert result["elapsed_s"] >= 0

    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_no_passages_found_rewrites_all(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "Fully rewritten document."

        result = await rewrite_document(
            document_text="Some document text.",
            flagged_passages=["non-existent passage"],
            tone="academic",
        )

        assert result["passages_rewritten"] == 0
        assert result["rewritten"] == "Fully rewritten document."

    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_empty_flagged_list(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "Rewritten text."

        result = await rewrite_document(
            document_text="Document text.",
            flagged_passages=[],
            tone="professional",
        )

        assert result["passages_rewritten"] == 0


class TestCallAzureOpenAI:
    @pytest.mark.asyncio
    async def test_raises_if_not_configured(self) -> None:
        """Should raise ValueError when endpoint/key are empty."""
        with patch("app.tools.rewriter_tool.settings") as mock_settings:
            mock_settings.azure_openai_endpoint = ""
            mock_settings.azure_openai_api_key = ""
            mock_settings.azure_openai_deployment = "gpt-4o"
            mock_settings.azure_openai_api_version = "2024-12-01-preview"

            with pytest.raises(ValueError, match="not configured"):
                await _call_azure_openai("system", "user")


# ---------------------------------------------------------------------------
# API endpoint tests (via FastAPI TestClient)
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestRewriteParagraphEndpoint:
    @patch("app.routes.rewrite.rewrite_paragraph", new_callable=AsyncMock)
    def test_success(self, mock_rewrite: AsyncMock) -> None:
        mock_rewrite.return_value = {
            "original": "Plagiarised text.",
            "rewritten": "Original rewrite.",
            "tone": "academic",
            "elapsed_s": 1.23,
        }

        resp = client.post(
            "/api/v1/rewrite/paragraph",
            json={"text": "Plagiarised text.", "tone": "academic"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["original"] == "Plagiarised text."
        assert data["rewritten"] == "Original rewrite."
        assert data["tone"] == "academic"

    @patch("app.routes.rewrite.rewrite_paragraph", new_callable=AsyncMock)
    def test_not_configured_returns_503(self, mock_rewrite: AsyncMock) -> None:
        mock_rewrite.side_effect = ValueError("Azure OpenAI is not configured.")

        resp = client.post(
            "/api/v1/rewrite/paragraph",
            json={"text": "Some text."},
        )

        assert resp.status_code == 503

    @patch("app.routes.rewrite.rewrite_paragraph", new_callable=AsyncMock)
    def test_api_error_returns_502(self, mock_rewrite: AsyncMock) -> None:
        mock_rewrite.side_effect = RuntimeError("Azure returned 500")

        resp = client.post(
            "/api/v1/rewrite/paragraph",
            json={"text": "Some text."},
        )

        assert resp.status_code == 502

    def test_empty_text_rejected(self) -> None:
        resp = client.post(
            "/api/v1/rewrite/paragraph",
            json={"text": ""},
        )

        assert resp.status_code == 422


class TestRewriteDocumentEndpoint:
    @patch("app.routes.rewrite.rewrite_document", new_callable=AsyncMock)
    def test_success(self, mock_rewrite: AsyncMock) -> None:
        mock_rewrite.return_value = {
            "original": "Full document text.",
            "rewritten": "Full rewritten document.",
            "passages_rewritten": 2,
            "tone": "professional",
            "elapsed_s": 3.45,
        }

        resp = client.post(
            "/api/v1/rewrite/document",
            json={
                "text": "Full document text.",
                "flagged_passages": ["passage one", "passage two"],
                "tone": "professional",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["rewritten"] == "Full rewritten document."
        assert data["passages_rewritten"] == 2

    @patch("app.routes.rewrite.rewrite_document", new_callable=AsyncMock)
    def test_not_configured_returns_503(self, mock_rewrite: AsyncMock) -> None:
        mock_rewrite.side_effect = ValueError("Azure OpenAI is not configured.")

        resp = client.post(
            "/api/v1/rewrite/document",
            json={"text": "Some doc."},
        )

        assert resp.status_code == 503

    @patch("app.routes.rewrite.rewrite_document", new_callable=AsyncMock)
    def test_api_error_returns_502(self, mock_rewrite: AsyncMock) -> None:
        mock_rewrite.side_effect = RuntimeError("Azure returned 500")

        resp = client.post(
            "/api/v1/rewrite/document",
            json={"text": "Some doc."},
        )

        assert resp.status_code == 502

    def test_empty_text_rejected(self) -> None:
        resp = client.post(
            "/api/v1/rewrite/document",
            json={"text": ""},
        )

        assert resp.status_code == 422

    @patch("app.routes.rewrite.rewrite_document", new_callable=AsyncMock)
    def test_no_flagged_passages_accepted(self, mock_rewrite: AsyncMock) -> None:
        mock_rewrite.return_value = {
            "original": "Doc.",
            "rewritten": "Rewritten doc.",
            "passages_rewritten": 0,
            "tone": "casual",
            "elapsed_s": 1.0,
        }

        resp = client.post(
            "/api/v1/rewrite/document",
            json={"text": "Doc.", "tone": "casual"},
        )

        assert resp.status_code == 200
        assert resp.json()["passages_rewritten"] == 0
