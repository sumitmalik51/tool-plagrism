"""Tests for the Semantic Scholar author lookup tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.semantic_scholar_tool import (
    _parse_author,
    _parse_paper,
    search_authors,
    get_author_papers,
)


# ---------------------------------------------------------------------------
# _parse_author
# ---------------------------------------------------------------------------

def test_parse_author_full() -> None:
    raw = {
        "authorId": "12345",
        "name": "Alice Smith",
        "url": "https://www.semanticscholar.org/author/12345",
        "paperCount": 42,
        "citationCount": 1500,
        "hIndex": 18,
        "affiliations": ["MIT"],
    }
    result = _parse_author(raw)

    assert result["author_id"] == "12345"
    assert result["name"] == "Alice Smith"
    assert result["paper_count"] == 42
    assert result["citation_count"] == 1500
    assert result["h_index"] == 18
    assert result["affiliations"] == ["MIT"]


def test_parse_author_minimal() -> None:
    result = _parse_author({})
    assert result["author_id"] == ""
    assert result["name"] == ""
    assert result["paper_count"] == 0
    assert result["citation_count"] == 0
    assert result["h_index"] == 0


# ---------------------------------------------------------------------------
# _parse_paper
# ---------------------------------------------------------------------------

def test_parse_paper_full() -> None:
    raw = {
        "paperId": "abc123",
        "title": "Deep Learning Study",
        "year": 2024,
        "citationCount": 100,
        "url": "https://semanticscholar.org/paper/abc123",
        "venue": "NeurIPS",
    }
    result = _parse_paper(raw)

    assert result["paper_id"] == "abc123"
    assert result["title"] == "Deep Learning Study"
    assert result["year"] == 2024
    assert result["citation_count"] == 100
    assert result["venue"] == "NeurIPS"


def test_parse_paper_minimal() -> None:
    result = _parse_paper({})
    assert result["paper_id"] == ""
    assert result["title"] == ""
    assert result["citation_count"] == 0


# ---------------------------------------------------------------------------
# search_authors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_authors_ok() -> None:
    mock_data = {
        "data": [
            {
                "authorId": "123",
                "name": "Alice Smith",
                "url": "https://example.com",
                "paperCount": 10,
                "citationCount": 100,
                "hIndex": 5,
                "affiliations": ["MIT"],
            },
            {
                "authorId": "456",
                "name": "Bob Jones",
                "url": "https://example.com/2",
                "paperCount": 20,
                "citationCount": 200,
                "hIndex": 10,
                "affiliations": [],
            },
        ]
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.semantic_scholar_tool._get_s2_client", return_value=mock_client):
        result = await search_authors("Alice Smith", max_results=5)

    assert result["query"] == "Alice Smith"
    assert result["result_count"] == 2
    assert result["results"][0]["name"] == "Alice Smith"
    assert result["results"][1]["name"] == "Bob Jones"
    assert result["elapsed_s"] >= 0


@pytest.mark.asyncio
async def test_search_authors_empty() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.semantic_scholar_tool._get_s2_client", return_value=mock_client):
        result = await search_authors("nonexistent author", max_results=5)

    assert result["result_count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_authors_timeout() -> None:
    import httpx

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    mock_client.is_closed = False

    with patch("app.tools.semantic_scholar_tool._get_s2_client", return_value=mock_client):
        result = await search_authors("test", max_results=5)

    assert result["result_count"] == 0


# ---------------------------------------------------------------------------
# get_author_papers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_author_papers_ok() -> None:
    mock_data = {
        "data": [
            {
                "paperId": "p1",
                "title": "Paper One",
                "year": 2023,
                "citationCount": 50,
                "url": "https://example.com/p1",
                "venue": "ICML",
            },
            {
                "paperId": "p2",
                "title": "Paper Two",
                "year": 2024,
                "citationCount": 10,
                "url": "https://example.com/p2",
                "venue": "NeurIPS",
            },
        ]
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.semantic_scholar_tool._get_s2_client", return_value=mock_client):
        result = await get_author_papers("12345", max_results=10)

    assert result["author_id"] == "12345"
    assert result["paper_count"] == 2
    assert result["papers"][0]["title"] == "Paper One"
    assert result["papers"][1]["venue"] == "NeurIPS"


@pytest.mark.asyncio
async def test_get_author_papers_empty() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.semantic_scholar_tool._get_s2_client", return_value=mock_client):
        result = await get_author_papers("99999", max_results=10)

    assert result["paper_count"] == 0
    assert result["papers"] == []


@pytest.mark.asyncio
async def test_get_author_papers_http_error() -> None:
    import httpx

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.semantic_scholar_tool._get_s2_client", return_value=mock_client):
        result = await get_author_papers("bad_id", max_results=10)

    assert result["paper_count"] == 0
