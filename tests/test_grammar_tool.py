"""Tests for the grammar & style checker tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.tools.grammar_tool import check_grammar, _parse_result, _quality_label


class TestParseResult:
    """Test JSON parsing of LLM responses."""

    def test_valid_json(self):
        raw = '{"issues": [{"type": "grammar", "severity": "error", "text": "bad", "message": "fix it", "suggestion": "good"}], "corrected_text": "good", "summary": {"total_issues": 1, "errors": 1, "warnings": 0, "suggestions": 0, "overall_quality": "good"}}'
        result = _parse_result(raw)
        assert len(result["issues"]) == 1
        assert result["corrected_text"] == "good"

    def test_json_in_markdown(self):
        raw = '```json\n{"issues": [], "corrected_text": "fine", "summary": {}}\n```'
        result = _parse_result(raw)
        assert result["issues"] == []

    def test_invalid_json(self):
        raw = "This is not JSON at all."
        result = _parse_result(raw)
        assert result["issues"] == []

    def test_empty_string(self):
        result = _parse_result("")
        assert result["issues"] == []


class TestQualityLabel:
    """Test quality label computation."""

    def test_excellent(self):
        assert _quality_label(0, 0, 1000) == "excellent"

    def test_needs_improvement(self):
        assert _quality_label(5, 5, 1000) in ("needs_improvement", "poor")

    def test_poor(self):
        assert _quality_label(20, 10, 1000) == "poor"


class TestCheckGrammar:
    """Test the grammar checking function."""

    @pytest.mark.asyncio
    async def test_short_text_skipped(self):
        result = await check_grammar("hi")
        assert result["skipped"] is True
        assert result["summary"]["overall_quality"] == "text_too_short"

    @pytest.mark.asyncio
    async def test_happy_path(self):
        mock_response = '{"issues": [{"type": "grammar", "severity": "error", "text": "he go", "message": "Subject-verb agreement", "suggestion": "he goes"}], "corrected_text": "He goes to school.", "summary": {"total_issues": 1, "errors": 1, "warnings": 0, "suggestions": 0, "overall_quality": "good"}}'

        with patch("app.tools.grammar_tool._call_openai", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            result = await check_grammar("He go to school every day. This is a test.")

        assert result["skipped"] is False
        assert len(result["issues"]) == 1
        assert result["issues"][0]["severity"] == "error"
        assert result["elapsed_s"] >= 0

    @pytest.mark.asyncio
    async def test_no_issues(self):
        mock_response = '{"issues": [], "corrected_text": "Perfect text.", "summary": {"total_issues": 0, "errors": 0, "warnings": 0, "suggestions": 0, "overall_quality": "excellent"}}'

        with patch("app.tools.grammar_tool._call_openai", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            result = await check_grammar("This is a perfectly written sentence with no errors.")

        assert result["summary"]["total_issues"] == 0
        assert result["summary"]["overall_quality"] == "excellent"
