"""Tests for the arXiv academic search tool."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.arxiv_tool import (
    _parse_entry,
    search_arxiv,
    search_arxiv_multi,
    _NS,
)


# ---------------------------------------------------------------------------
# Sample arXiv XML response
# ---------------------------------------------------------------------------

_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.12345v1</id>
    <title>
      Deep Learning for
      Natural Language Processing
    </title>
    <summary>
      We present a novel approach to NLP using deep neural networks.
    </summary>
    <published>2023-01-15T00:00:00Z</published>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2301.12345v1" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.CL"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2302.99999v2</id>
    <title>Transformers in Vision</title>
    <summary>Vision transformers are great.</summary>
    <published>2023-02-20T00:00:00Z</published>
    <author><name>Charlie Brown</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2302.99999v2" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.CV"/>
  </entry>
</feed>"""


# ---------------------------------------------------------------------------
# _parse_entry
# ---------------------------------------------------------------------------

def test_parse_entry_full() -> None:
    root = ET.fromstring(_SAMPLE_XML)
    entries = root.findall("atom:entry", _NS)
    result = _parse_entry(entries[0])

    assert result["title"] == "Deep Learning for Natural Language Processing"
    assert result["authors"] == ["Alice Smith", "Bob Jones"]
    assert result["year"] == "2023"
    assert "novel approach" in result["abstract"]
    assert result["arxiv_id"] == "2301.12345v1"
    assert result["pdf_url"] == "http://arxiv.org/pdf/2301.12345v1"
    assert result["category"] == "cs.CL"
    assert result["venue"] == "arXiv (cs.CL)"
    assert result["url"] == "http://arxiv.org/abs/2301.12345v1"


def test_parse_entry_second() -> None:
    root = ET.fromstring(_SAMPLE_XML)
    entries = root.findall("atom:entry", _NS)
    result = _parse_entry(entries[1])

    assert result["title"] == "Transformers in Vision"
    assert result["authors"] == ["Charlie Brown"]
    assert result["year"] == "2023"
    assert result["category"] == "cs.CV"


def test_parse_entry_citation_count_is_zero() -> None:
    """arXiv API doesn't provide citation counts."""
    root = ET.fromstring(_SAMPLE_XML)
    entry = root.findall("atom:entry", _NS)[0]
    result = _parse_entry(entry)
    assert result["citation_count"] == 0


# ---------------------------------------------------------------------------
# search_arxiv
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_arxiv_ok() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = _SAMPLE_XML
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.arxiv_tool._get_arxiv_client", return_value=mock_client):
        result = await search_arxiv("deep learning NLP", max_results=5)

    assert result["query"] == "deep learning NLP"
    assert result["result_count"] == 2
    assert len(result["results"]) == 2
    assert result["results"][0]["title"] == "Deep Learning for Natural Language Processing"
    assert result["elapsed_s"] >= 0


@pytest.mark.asyncio
async def test_search_arxiv_empty_response() -> None:
    empty_xml = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = empty_xml
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.arxiv_tool._get_arxiv_client", return_value=mock_client):
        result = await search_arxiv("nonexistent topic", max_results=5)

    assert result["result_count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_arxiv_timeout() -> None:
    import httpx

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    mock_client.is_closed = False

    with patch("app.tools.arxiv_tool._get_arxiv_client", return_value=mock_client):
        result = await search_arxiv("test query", max_results=5)

    assert result["result_count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_arxiv_xml_parse_error() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "not xml at all"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.arxiv_tool._get_arxiv_client", return_value=mock_client):
        result = await search_arxiv("test", max_results=5)

    assert result["result_count"] == 0


# ---------------------------------------------------------------------------
# search_arxiv_multi
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_arxiv_multi_deduplication() -> None:
    """Multiple queries returning the same paper should be deduplicated."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = _SAMPLE_XML
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch("app.tools.arxiv_tool._get_arxiv_client", return_value=mock_client):
        result = await search_arxiv_multi(
            ["deep learning", "NLP transformers"], max_per_query=5
        )

    # Both queries return the same 2 papers — should be dedeuplicated
    assert result["queries_searched"] == 2
    assert result["total_results"] == 2  # Not 4


@pytest.mark.asyncio
async def test_search_arxiv_multi_empty_queries() -> None:
    result = await search_arxiv_multi([], max_per_query=3)
    assert result["queries_searched"] == 0
    assert result["total_results"] == 0


@pytest.mark.asyncio
async def test_search_arxiv_multi_partial_failure() -> None:
    """One query succeeds, another fails — should still return partial results."""
    call_count = 0

    async def mock_search(query, max_results=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "query": query,
                "results": [{"title": "Paper A", "authors": [], "year": "2024"}],
                "result_count": 1,
                "elapsed_s": 0.1,
            }
        raise RuntimeError("API error")

    with patch("app.tools.arxiv_tool.search_arxiv", side_effect=mock_search):
        result = await search_arxiv_multi(["q1", "q2"], max_per_query=3)

    assert result["total_results"] >= 1
