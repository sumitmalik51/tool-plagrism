"""Tests for GPT-powered AI detection in ai_detection_tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.tools.ai_detection_tool import detect_ai_text, _gpt_classify_chunks


# ---------------------------------------------------------------------------
# Heuristic mode (no GPT)
# ---------------------------------------------------------------------------

class TestHeuristicAIDetection:
    @pytest.mark.asyncio
    async def test_empty_text(self):
        result = await detect_ai_text("")
        assert result["score"] == 0.0
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_normal_text_returns_valid_score(self):
        text = "Machine learning is a powerful approach. " * 20
        result = await detect_ai_text(text)
        assert 0 <= result["score"] <= 100
        assert 0 <= result["confidence"] <= 1
        assert "indicators" in result
        assert result["indicators"]["gpt_enabled"] is False
        assert result["indicators"]["gpt_score"] is None

    @pytest.mark.asyncio
    async def test_indicators_present(self):
        text = "The quick brown fox jumps over the lazy dog. " * 15
        result = await detect_ai_text(text)
        ind = result["indicators"]
        assert "type_token_ratio" in ind
        assert "burstiness_signal" in ind
        assert "repetition_signal" in ind
        assert "uniformity_signal" in ind


# ---------------------------------------------------------------------------
# GPT mode (mocked)
# ---------------------------------------------------------------------------

def _mock_gpt_response(chunks, labels=None):
    """Create a mock GPT response for the given chunks."""
    if labels is None:
        labels = ["ai"] * len(chunks)
    return [
        {"label": labels[i] if i < len(labels) else "human", "confidence": 0.85, "reason": "Test reason"}
        for i in range(len(chunks))
    ]


class TestGPTAIDetection:
    @pytest.mark.asyncio
    async def test_gpt_mode_blends_scores(self):
        """When use_gpt=True, result should blend GPT and heuristic scores."""
        chunks = ["This is chunk one with enough words. " * 5] * 5
        text = " ".join(chunks)

        gpt_results = _mock_gpt_response(chunks, labels=["ai", "ai", "human", "human", "ai"])

        with patch("app.tools.ai_detection_tool._gpt_classify_chunks", new_callable=AsyncMock) as mock_gpt:
            mock_gpt.return_value = gpt_results
            result = await detect_ai_text(text, chunks=chunks, use_gpt=True)

        assert result["indicators"]["gpt_enabled"] is True
        assert result["indicators"]["gpt_score"] is not None
        # GPT score: 3/5 AI = 60%
        assert result["indicators"]["gpt_score"] == 60.0
        # Final score is blended: 60*0.7 + heuristic*0.3
        assert result["score"] > 0

    @pytest.mark.asyncio
    async def test_gpt_mode_adds_flagged_chunks(self):
        """GPT-flagged chunks should appear in flagged_chunks."""
        chunks = ["Passage one with enough content. " * 5]
        text = chunks[0]

        gpt_results = [{"label": "ai", "confidence": 0.9, "reason": "Formulaic structure"}]

        with patch("app.tools.ai_detection_tool._gpt_classify_chunks", new_callable=AsyncMock) as mock_gpt:
            mock_gpt.return_value = gpt_results
            result = await detect_ai_text(text, chunks=chunks, use_gpt=True)

        gpt_flagged = [f for f in result["flagged_chunks"] if "GPT classifier" in f.get("reason", "")]
        assert len(gpt_flagged) >= 1

    @pytest.mark.asyncio
    async def test_gpt_mode_without_chunks_skips_gpt(self):
        """If chunks is None, GPT mode should not be invoked."""
        text = "This text does not have chunks. " * 10

        with patch("app.tools.ai_detection_tool._gpt_classify_chunks", new_callable=AsyncMock) as mock_gpt:
            result = await detect_ai_text(text, chunks=None, use_gpt=True)

        mock_gpt.assert_not_called()
        assert result["indicators"]["gpt_score"] is None

    @pytest.mark.asyncio
    async def test_gpt_classify_returns_empty_without_credentials(self):
        """With no Azure credentials, _gpt_classify_chunks returns empty."""
        with patch("app.tools.ai_detection_tool.settings") as mock_settings:
            mock_settings.azure_openai_endpoint = ""
            mock_settings.azure_openai_api_key = ""
            result = await _gpt_classify_chunks(["some text"])
        assert result == []

    @pytest.mark.asyncio
    async def test_gpt_all_human_low_gpt_score(self):
        """If GPT classifies all chunks as human, gpt_score should be 0."""
        chunks = ["A clearly human passage. " * 5] * 3
        text = " ".join(chunks)

        gpt_results = _mock_gpt_response(chunks, labels=["human", "human", "human"])

        with patch("app.tools.ai_detection_tool._gpt_classify_chunks", new_callable=AsyncMock) as mock_gpt:
            mock_gpt.return_value = gpt_results
            result = await detect_ai_text(text, chunks=chunks, use_gpt=True)

        assert result["indicators"]["gpt_score"] == 0.0
