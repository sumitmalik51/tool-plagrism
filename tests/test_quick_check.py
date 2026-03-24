"""Tests for the quick-check endpoint and citation-for-source endpoint."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.routes.writing import QuickCheckRequest, SourceCitationRequest


# ---------------------------------------------------------------------------
# QuickCheckRequest validation
# ---------------------------------------------------------------------------

class TestQuickCheckRequest:
    """Validate QuickCheckRequest schema."""

    def test_valid_text(self):
        req = QuickCheckRequest(text="This is a sufficiently long piece of text for checking.")
        assert len(req.text) >= 20

    def test_short_text_rejected(self):
        with pytest.raises(Exception):
            QuickCheckRequest(text="too short")

    def test_max_length_enforcement(self):
        """Text over 5000 chars should be rejected."""
        with pytest.raises(Exception):
            QuickCheckRequest(text="a" * 5001)


# ---------------------------------------------------------------------------
# SourceCitationRequest validation
# ---------------------------------------------------------------------------

class TestSourceCitationRequest:
    """Validate SourceCitationRequest schema."""

    def test_with_url_only(self):
        req = SourceCitationRequest(url="https://example.com/paper")
        assert req.url == "https://example.com/paper"
        assert req.title is None

    def test_with_full_metadata(self):
        req = SourceCitationRequest(
            url="https://example.com/paper",
            title="A Great Paper",
            authors=["John Doe"],
            year=2024,
            publisher="Academic Press",
        )
        assert req.title == "A Great Paper"
        assert req.authors == ["John Doe"]
        assert req.year == 2024

    def test_empty_is_valid(self):
        """All fields are optional."""
        req = SourceCitationRequest()
        assert req.url is None
        assert req.title is None


# ---------------------------------------------------------------------------
# Citation for source integration
# ---------------------------------------------------------------------------

class TestCitationForSource:
    """Test citation generation for a single source."""

    def test_generates_all_styles(self):
        from app.tools.citation_tool import generate_citations_from_sources, ALL_STYLES

        source = {
            "url": "https://example.com/research",
            "title": "Machine Learning in Education",
            "similarity": 0.0,
            "source_type": "Internet",
        }

        for style in ALL_STYLES:
            result = generate_citations_from_sources([source], style=style)
            assert result["count"] == 1
            assert len(result["citations"]) == 1
            assert result["style"] == style
            # Citation text should contain the URL
            assert "example.com" in result["citations"][0]["citation"]

    def test_citation_without_url(self):
        from app.tools.citation_tool import generate_citations_from_sources

        source = {
            "title": "Offline Document",
            "similarity": 0.0,
            "source_type": "Internet",
        }
        result = generate_citations_from_sources([source], style="apa")
        assert result["count"] == 1
        assert "Offline Document" in result["citations"][0]["citation"]


# ---------------------------------------------------------------------------
# Quick check overlap logic
# ---------------------------------------------------------------------------

class TestOverlapDetection:
    """Test the word-overlap logic used in quick-check."""

    def test_high_overlap(self):
        """Two sentences with >50% word overlap should be detected."""
        sentence = "the quick brown fox jumps over the lazy dog"
        snippet = "the quick brown fox leaps over the lazy hound"

        sent_words = set(sentence.lower().split())
        snippet_words = set(snippet.lower().split())
        overlap = sent_words & snippet_words
        overlap_ratio = len(overlap) / len(sent_words)

        assert overlap_ratio >= 0.5

    def test_low_overlap(self):
        """Unrelated sentences should have low overlap."""
        sentence = "machine learning algorithms transform data analysis"
        snippet = "the weather today is sunny and warm outside"

        sent_words = set(sentence.lower().split())
        snippet_words = set(snippet.lower().split())
        overlap = sent_words & snippet_words
        overlap_ratio = len(overlap) / len(sent_words)

        assert overlap_ratio < 0.5

    def test_identical_text(self):
        """Identical text should have 100% overlap."""
        text = "this is exactly the same sentence used in both places"
        sent_words = set(text.lower().split())
        overlap_ratio = len(sent_words & sent_words) / len(sent_words)
        assert overlap_ratio == 1.0
