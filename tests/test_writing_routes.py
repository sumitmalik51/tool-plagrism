"""Tests for the writing tools routes (citation, readability, grammar, batch)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestCitationEndpoints:
    """Test citation generation routes."""

    def test_generate_citations_apa(self):
        resp = client.post("/api/v1/citations/generate", json={
            "sources": [
                {"url": "https://example.com/paper", "title": "Test Paper", "similarity": 0.8},
            ],
            "style": "apa",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["style"] == "apa"
        assert len(data["citations"]) == 1

    def test_generate_citations_all_styles(self):
        resp = client.post("/api/v1/citations/all-styles", json={
            "sources": [
                {"url": "https://example.com", "title": "Sample", "similarity": 0.5},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "styles" in data
        assert "apa" in data["styles"]
        assert "mla" in data["styles"]
        assert "chicago" in data["styles"]
        assert "ieee" in data["styles"]

    def test_generate_citations_empty_sources(self):
        resp = client.post("/api/v1/citations/generate", json={
            "sources": [],
            "style": "apa",
        })
        # Pydantic validation requires min_length=1
        assert resp.status_code == 422


class TestReadabilityEndpoint:
    """Test readability analysis route."""

    def test_readability_basic(self):
        resp = client.post("/api/v1/readability", json={
            "text": "The quick brown fox jumps over the lazy dog. Simple sentences are easy to read. This is a test."
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "scores" in data
        assert "statistics" in data
        assert "reading_time" in data
        assert "level" in data

    def test_readability_empty_text(self):
        resp = client.post("/api/v1/readability", json={"text": ""})
        assert resp.status_code == 422  # Pydantic min_length validation


class TestGrammarEndpoint:
    """Test grammar checking route."""

    def test_grammar_short_text(self):
        resp = client.post("/api/v1/grammar/check", json={"text": "hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["skipped"] is True

    def test_grammar_happy_path(self):
        mock_response = '{"issues": [], "corrected_text": "Good text.", "summary": {"total_issues": 0, "errors": 0, "warnings": 0, "suggestions": 0, "overall_quality": "excellent"}}'

        with patch("app.tools.grammar_tool._call_openai", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            resp = client.post("/api/v1/grammar/check", json={
                "text": "This is a well-written sentence without any grammatical errors."
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["skipped"] is False
        assert data["summary"]["total_issues"] == 0


class TestAnalyzeExcludedDomains:
    """Test that excluded_domains parameter is accepted."""

    def test_excluded_domains_accepted(self):
        """The endpoint should accept the excluded_domains field."""
        with patch("app.routes.analyze.run_pipeline", new_callable=AsyncMock) as mock:
            from app.models.schemas import PlagiarismReport, RiskLevel
            mock.return_value = PlagiarismReport(
                document_id="test",
                plagiarism_score=0.0,
                confidence_score=0.0,
                risk_level=RiskLevel.LOW,
                explanation="Test",
            )
            resp = client.post("/api/v1/analyze-agent", json={
                "text": "Hello world test text.",
                "excluded_domains": ["example.com", "mysite.org"],
            })
        assert resp.status_code == 200
        # Verify excluded_domains was passed
        call_kwargs = mock.call_args[1]
        assert call_kwargs["excluded_domains"] == ["example.com", "mysite.org"]
