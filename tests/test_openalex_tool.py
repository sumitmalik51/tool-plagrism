"""Tests for the OpenAlex academic search tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.tools.openalex_tool import (
    _uninvert_abstract,
    _parse_work,
    search_openalex,
    search_openalex_multi,
)


# ---------------------------------------------------------------------------
# _uninvert_abstract
# ---------------------------------------------------------------------------

def test_uninvert_abstract_basic() -> None:
    inverted = {"Hello": [0], "world": [1], "of": [2], "science": [3]}
    assert _uninvert_abstract(inverted) == "Hello world of science"


def test_uninvert_abstract_empty() -> None:
    assert _uninvert_abstract(None) == ""
    assert _uninvert_abstract({}) == ""


def test_uninvert_abstract_gaps() -> None:
    """Gaps in positions should produce empty strings that are filtered."""
    inverted = {"First": [0], "Last": [5]}
    result = _uninvert_abstract(inverted)
    assert "First" in result
    assert "Last" in result


# ---------------------------------------------------------------------------
# _parse_work
# ---------------------------------------------------------------------------

def test_parse_work_full() -> None:
    work = {
        "id": "https://openalex.org/W12345",
        "title": "Deep Learning for NLP",
        "authorships": [
            {"author": {"display_name": "Alice Smith"}},
            {"author": {"display_name": "Bob Jones"}},
        ],
        "publication_year": 2024,
        "abstract_inverted_index": {"Deep": [0], "learning": [1], "works": [2]},
        "primary_location": {
            "source": {"display_name": "Nature AI"}
        },
        "cited_by_count": 42,
        "doi": "https://doi.org/10.1234/example",
    }
    result = _parse_work(work)

    assert result["title"] == "Deep Learning for NLP"
    assert result["authors"] == ["Alice Smith", "Bob Jones"]
    assert result["year"] == "2024"
    assert result["abstract"] == "Deep learning works"
    assert result["venue"] == "Nature AI"
    assert result["citation_count"] == 42
    assert result["url"] == "https://doi.org/10.1234/example"
    assert result["openalex_id"] == "https://openalex.org/W12345"


def test_parse_work_minimal() -> None:
    work = {"title": "Minimal Paper", "id": "https://openalex.org/W1"}
    result = _parse_work(work)
    assert result["title"] == "Minimal Paper"
    assert result["authors"] == []
    assert result["year"] == ""
    assert result["abstract"] == ""


# ---------------------------------------------------------------------------
# search_openalex (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.tools.openalex_tool._get_openalex_client")
async def test_search_openalex_success(mock_get_client: MagicMock) -> None:
    """Successful OpenAlex API call should return parsed results."""
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "meta": {"count": 1},
        "results": [
            {
                "id": "https://openalex.org/W999",
                "title": "Test Paper",
                "authorships": [{"author": {"display_name": "Tester"}}],
                "publication_year": 2025,
                "abstract_inverted_index": {"Abstract": [0], "text": [1]},
                "primary_location": {"source": {"display_name": "Test Journal"}},
                "cited_by_count": 10,
                "doi": "https://doi.org/10.5555/test",
            }
        ],
    }
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_get_client.return_value = mock_client

    result = await search_openalex("test query", max_results=5)

    assert result["result_count"] == 1
    assert result["results"][0]["title"] == "Test Paper"
    assert result["results"][0]["url"] == "https://doi.org/10.5555/test"


@pytest.mark.asyncio
@patch("app.tools.openalex_tool._get_openalex_client")
async def test_search_openalex_http_error(mock_get_client: MagicMock) -> None:
    """HTTP errors should log and return empty results."""
    import httpx
    from unittest.mock import MagicMock

    mock_request = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=mock_request, response=mock_resp
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_get_client.return_value = mock_client

    result = await search_openalex("test query")
    assert result["result_count"] == 0
    assert result["results"] == []


# ---------------------------------------------------------------------------
# search_openalex_multi
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.tools.openalex_tool.search_openalex", new_callable=AsyncMock)
async def test_search_openalex_multi_dedup(mock_search: AsyncMock) -> None:
    """Multi-search should deduplicate results by title."""
    mock_search.side_effect = [
        {
            "results": [
                {"title": "Paper A", "url": "https://doi.org/a"},
                {"title": "Paper B", "url": "https://doi.org/b"},
            ]
        },
        {
            "results": [
                {"title": "Paper B", "url": "https://doi.org/b"},  # duplicate
                {"title": "Paper C", "url": "https://doi.org/c"},
            ]
        },
    ]

    result = await search_openalex_multi(["query1", "query2"], max_per_query=3)

    assert result["total_results"] == 3  # A, B, C (B deduplicated)
    titles = {r["title"] for r in result["results"]}
    assert titles == {"Paper A", "Paper B", "Paper C"}


@pytest.mark.asyncio
@patch("app.tools.openalex_tool.search_openalex", new_callable=AsyncMock)
async def test_search_openalex_multi_all_empty(mock_search: AsyncMock) -> None:
    """All empty results should be reported."""
    mock_search.return_value = {"results": []}

    result = await search_openalex_multi(["q1", "q2"], max_per_query=3)

    assert result["total_results"] == 0
    assert result["results"] == []
