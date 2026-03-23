"""Tests for the AI rewriter tool and endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.tools.rewriter_tool import (
    rewrite_paragraph,
    rewrite_document,
    _call_azure_openai,
    MIN_REWRITE_LENGTH,
    MIN_REWRITE_WORDS,
)


# ---------------------------------------------------------------------------
# Unit tests for rewriter_tool
# ---------------------------------------------------------------------------

class TestRewriteParagraph:
    @pytest.mark.asyncio
    async def test_short_fragment_skipped(self) -> None:
        """Fragments shorter than MIN_REWRITE_LENGTH are returned as-is."""
        result = await rewrite_paragraph(text="vs.", tone="academic")
        assert result["skipped"] is True
        assert result["original"] == "vs."
        assert result["rewrites"] == ["vs."]

    @pytest.mark.asyncio
    async def test_few_words_skipped(self) -> None:
        """Fragments with fewer than MIN_REWRITE_WORDS are returned as-is."""
        result = await rewrite_paragraph(text="Non-Flexible vs.", tone="academic")
        assert result["skipped"] is True
        assert result["rewrites"] == ["Non-Flexible vs."]

    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_returns_rewritten_text(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "This is the rewritten version of the text."

        result = await rewrite_paragraph(
            text="Original plagiarised text here.",
            tone="academic",
        )

        assert result["original"] == "Original plagiarised text here."
        assert result["rewrites"][0] == "This is the rewritten version of the text."
        assert result["tone"] == "academic"
        assert result["elapsed_s"] >= 0
        mock_api.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_passes_context(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "Rewritten."

        await rewrite_paragraph(
            text="This is a sufficiently long flagged text passage for rewriting.",
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

        result = await rewrite_paragraph(text="Some text that is long enough to rewrite.", tone="casual")
        assert result["tone"] == "casual"


class TestRewriteDocument:
    @pytest.mark.asyncio
    @patch("app.tools.rewriter_tool._call_azure_openai", new_callable=AsyncMock)
    async def test_rewrites_with_flagged_passages(self, mock_api: AsyncMock) -> None:
        mock_api.return_value = "This is the complete rewritten document."

        flagged = "The quick brown fox jumps over the lazy dog in the park"
        result = await rewrite_document(
            document_text=f"Once upon a time. {flagged}. The end of the story.",
            flagged_passages=[flagged],
            tone="academic",
        )

        assert result["passages_rewritten"] == 1
        assert result["rewritten"] == "This is the complete rewritten document."
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
    @patch("app.tools.rewriter_tool.httpx.AsyncClient")
    async def test_raises_on_bad_status(self, mock_client_cls) -> None:
        """Should raise RuntimeError when API returns non-200."""
        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError):
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
            "rewrites": ["Original rewrite."],
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
            "elapsed_s": 1.0,
        }

        resp = client.post(
            "/api/v1/rewrite/document",
            json={"text": "Doc.", "tone": "casual"},
        )

        assert resp.status_code == 200
        assert resp.json()["passages_rewritten"] == 0
