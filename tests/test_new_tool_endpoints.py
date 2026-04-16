"""Tests for the new tool API endpoints (arXiv, BibTeX, Author, Relevance)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /tools/arxiv-search
# ---------------------------------------------------------------------------

def test_arxiv_search_endpoint() -> None:
    mock_result = {
        "query": "deep learning",
        "results": [
            {"title": "DL Paper", "authors": ["Smith"], "year": "2024", "arxiv_id": "2401.00001"}
        ],
        "result_count": 1,
        "elapsed_s": 0.5,
    }

    with patch("app.routes.tools.search_arxiv", new_callable=AsyncMock, return_value=mock_result):
        resp = client.post(
            "/tools/arxiv-search",
            json={"query": "deep learning", "max_results": 5},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["result_count"] == 1
    assert data["results"][0]["title"] == "DL Paper"


def test_arxiv_search_empty_query() -> None:
    resp = client.post("/tools/arxiv-search", json={"query": "", "max_results": 5})
    assert resp.status_code == 422  # Validation error


# ---------------------------------------------------------------------------
# /tools/bibtex-export
# ---------------------------------------------------------------------------

def test_bibtex_export_endpoint() -> None:
    resp = client.post(
        "/tools/bibtex-export",
        json={
            "papers": [
                {
                    "title": "Test Paper",
                    "authors": ["Alice Smith"],
                    "year": "2024",
                    "abstract": "A test abstract.",
                    "url": "https://example.com",
                    "venue": "Test Journal",
                }
            ]
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["entry_count"] == 1
    assert "@article{" in data["bibtex"]
    assert "Test Paper" in data["bibtex"]


def test_bibtex_export_multiple_papers() -> None:
    resp = client.post(
        "/tools/bibtex-export",
        json={
            "papers": [
                {"title": "Paper A", "authors": ["Author A"], "year": "2023"},
                {"title": "Paper B", "authors": ["Author B"], "year": "2024"},
            ]
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["entry_count"] == 2
    assert data["bibtex"].count("@") == 2


def test_bibtex_export_empty_papers() -> None:
    resp = client.post("/tools/bibtex-export", json={"papers": []})
    assert resp.status_code == 422  # min_length=1


# ---------------------------------------------------------------------------
# /tools/author-lookup
# ---------------------------------------------------------------------------

def test_author_lookup_endpoint() -> None:
    mock_result = {
        "query": "Smith",
        "results": [
            {"author_id": "123", "name": "Alice Smith", "paper_count": 10, "citation_count": 100}
        ],
        "result_count": 1,
        "elapsed_s": 0.3,
    }

    with patch("app.tools.semantic_scholar_tool.search_authors", new_callable=AsyncMock, return_value=mock_result):
        resp = client.post(
            "/tools/author-lookup",
            json={"query": "Smith", "max_results": 5},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["result_count"] == 1
    assert data["results"][0]["name"] == "Alice Smith"


# ---------------------------------------------------------------------------
# /tools/author-papers
# ---------------------------------------------------------------------------

def test_author_papers_endpoint() -> None:
    mock_result = {
        "author_id": "123",
        "papers": [{"paper_id": "p1", "title": "Paper 1", "year": 2024}],
        "paper_count": 1,
        "elapsed_s": 0.2,
    }

    with patch("app.tools.semantic_scholar_tool.get_author_papers", new_callable=AsyncMock, return_value=mock_result):
        resp = client.post(
            "/tools/author-papers",
            json={"author_id": "123", "max_results": 10},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["paper_count"] == 1


# ---------------------------------------------------------------------------
# /tools/relevance-score
# ---------------------------------------------------------------------------

def test_relevance_score_endpoint() -> None:
    mock_scored = [
        {"title": "Relevant", "abstract": "Content", "relevance_score": 0.85},
    ]

    with patch("app.tools.relevance_scorer.score_relevance", new_callable=AsyncMock, return_value=mock_scored):
        resp = client.post(
            "/tools/relevance-score",
            json={
                "query": "test query",
                "results": [
                    {"title": "Relevant", "abstract": "Content"},
                ],
                "min_score": 0.1,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["results"][0]["relevance_score"] == 0.85


def test_relevance_score_empty_results() -> None:
    resp = client.post(
        "/tools/relevance-score",
        json={"query": "test", "results": [], "min_score": 0.1},
    )
    assert resp.status_code == 422  # min_length=1
