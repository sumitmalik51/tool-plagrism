"""Semantic Scholar author lookup tool — search and retrieve author profiles.

Uses the Semantic Scholar Academic Graph API to look up authors and their
publications. Free tier: 100 requests/5 min without API key.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

_S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"

_s2_client: httpx.AsyncClient | None = None


def _get_s2_client() -> httpx.AsyncClient:
    global _s2_client
    if _s2_client is None or _s2_client.is_closed:
        _s2_client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
    return _s2_client


def _parse_author(author: dict[str, Any]) -> dict[str, Any]:
    """Parse an author result from the Semantic Scholar API."""
    return {
        "author_id": author.get("authorId", ""),
        "name": author.get("name", ""),
        "url": author.get("url", ""),
        "paper_count": author.get("paperCount", 0),
        "citation_count": author.get("citationCount", 0),
        "h_index": author.get("hIndex", 0),
        "affiliations": author.get("affiliations", []),
    }


def _parse_paper(paper: dict[str, Any]) -> dict[str, Any]:
    """Parse a paper from the author's publications."""
    return {
        "paper_id": paper.get("paperId", ""),
        "title": paper.get("title", ""),
        "year": paper.get("year"),
        "citation_count": paper.get("citationCount", 0),
        "url": paper.get("url", ""),
        "venue": paper.get("venue", ""),
    }


async def search_authors(
    query: str, max_results: int = 5
) -> dict[str, Any]:
    """Search Semantic Scholar for authors matching *query*.

    Returns:
        Dict with ``query``, ``results``, ``result_count``, ``elapsed_s``.
    """
    start = time.perf_counter()

    params = {
        "query": query,
        "limit": min(max_results, 20),
        "fields": "name,url,paperCount,citationCount,hIndex,affiliations",
    }

    results: list[dict[str, Any]] = []

    try:
        client = _get_s2_client()
        resp = await client.get(f"{_S2_BASE_URL}/author/search", params=params)
        resp.raise_for_status()

        data = resp.json()
        raw_authors = data.get("data", [])
        results = [_parse_author(a) for a in raw_authors]

        logger.info(
            "s2_author_search_ok",
            query=query[:80],
            result_count=len(results),
        )

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "s2_author_search_http_error",
            status=exc.response.status_code,
            query=query[:80],
        )
    except httpx.TimeoutException:
        logger.error("s2_author_search_timeout", query=query[:80])
    except Exception as exc:
        logger.error(
            "s2_author_search_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            query=query[:80],
        )

    elapsed = round(time.perf_counter() - start, 3)

    return {
        "query": query,
        "results": results,
        "result_count": len(results),
        "elapsed_s": elapsed,
    }


async def get_author_papers(
    author_id: str, max_results: int = 10
) -> dict[str, Any]:
    """Get an author's publications from Semantic Scholar.

    Args:
        author_id: Semantic Scholar author ID.
        max_results: Max papers to return.

    Returns:
        Dict with ``author_id``, ``papers``, ``paper_count``, ``elapsed_s``.
    """
    start = time.perf_counter()

    params = {
        "fields": "title,year,citationCount,url,venue",
        "limit": min(max_results, 50),
    }

    papers: list[dict[str, Any]] = []

    try:
        client = _get_s2_client()
        resp = await client.get(
            f"{_S2_BASE_URL}/author/{author_id}/papers", params=params
        )
        resp.raise_for_status()

        data = resp.json()
        raw_papers = data.get("data", [])
        papers = [_parse_paper(p) for p in raw_papers if p.get("title")]

        logger.info(
            "s2_author_papers_ok",
            author_id=author_id,
            paper_count=len(papers),
        )

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "s2_author_papers_http_error",
            status=exc.response.status_code,
            author_id=author_id,
        )
    except httpx.TimeoutException:
        logger.error("s2_author_papers_timeout", author_id=author_id)
    except Exception as exc:
        logger.error(
            "s2_author_papers_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            author_id=author_id,
        )

    elapsed = round(time.perf_counter() - start, 3)

    return {
        "author_id": author_id,
        "papers": papers,
        "paper_count": len(papers),
        "elapsed_s": elapsed,
    }
