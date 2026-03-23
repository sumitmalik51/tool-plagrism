"""Tests for the citation generator tool."""

from __future__ import annotations

import pytest

from app.tools.citation_tool import (
    generate_citation,
    generate_citations_from_sources,
)


class TestGenerateCitation:
    """Unit tests for single citation generation."""

    def test_apa_with_all_fields(self):
        cite = generate_citation(
            "apa",
            title="Deep Learning for NLP",
            url="https://example.com/paper",
            authors=["Smith, J.", "Doe, A."],
            year=2024,
            publisher="Example Press",
        )
        assert "Smith, J." in cite
        assert "Deep Learning for NLP" in cite
        assert "(2024)" in cite
        assert "example.com/paper" in cite

    def test_mla_format(self):
        cite = generate_citation(
            "mla",
            title="Test Paper",
            url="https://example.com",
            authors=["Author One"],
            year=2025,
        )
        assert '"Test Paper"' in cite
        assert "Author One" in cite
        assert "2025" in cite

    def test_chicago_format(self):
        cite = generate_citation(
            "chicago",
            title="Some Research",
            url="https://example.com/research",
            year=2023,
        )
        assert '"Some Research"' in cite
        assert "2023" in cite

    def test_ieee_format(self):
        cite = generate_citation(
            "ieee",
            title="ML Survey",
            url="https://arxiv.org/paper",
            authors=["X. Zhang"],
            year=2024,
            ref_number=3,
        )
        assert "[3]" in cite
        assert '"ML Survey"' in cite
        assert "Available:" in cite

    def test_no_year(self):
        cite = generate_citation("apa", title="Test", url="https://example.com")
        assert "(n.d.)" in cite

    def test_no_title(self):
        cite = generate_citation("apa", url="https://example.com")
        assert "Untitled" in cite

    def test_no_url(self):
        cite = generate_citation("apa", title="Offline Paper", year=2020)
        assert "Offline Paper" in cite
        assert "example.com" not in cite


class TestGenerateCitationsFromSources:
    """Tests for bulk citation generation from sources."""

    def test_empty_sources(self):
        result = generate_citations_from_sources([], style="apa")
        assert result["citations"] == []
        assert result["count"] == 0

    def test_multiple_sources(self):
        sources = [
            {"url": "https://example.com/a", "title": "Paper A", "similarity": 0.8},
            {"url": "https://arxiv.org/b", "title": "Paper B", "similarity": 0.6},
        ]
        result = generate_citations_from_sources(sources, style="apa")
        assert result["count"] == 2
        assert result["style"] == "apa"
        assert len(result["citations"]) == 2
        assert result["citations"][0]["ref_number"] == 1
        assert result["citations"][1]["ref_number"] == 2
        assert result["elapsed_s"] >= 0

    def test_ieee_with_ref_numbers(self):
        sources = [
            {"url": "https://site.com", "title": "T1", "similarity": 0.9},
        ]
        result = generate_citations_from_sources(sources, style="ieee")
        assert "[1]" in result["citations"][0]["citation"]

    def test_year_extraction_from_url(self):
        sources = [
            {"url": "https://site.com/2024/article", "title": "Article"},
        ]
        result = generate_citations_from_sources(sources, style="apa")
        assert "(2024)" in result["citations"][0]["citation"]
