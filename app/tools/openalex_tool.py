"""OpenAlex academic search tool — free, reliable alternative to Google Scholar.

Uses the OpenAlex REST API (https://api.openalex.org) to find academic papers.
No API key required. 250M+ works indexed. Returns structured results with
title, authors, year, abstract, venue, citation count, and DOI/URL.

Provides the same output format as ``scholar_tool`` so the academic agent
can use either source interchangeably.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

_OPENALEX_WORKS_URL = "https://api.openalex.org/works"

# Polite-pool email — gets higher rate limits from OpenAlex
_CONTACT_EMAIL = "plagiarismguard@example.com"

_openalex_client: httpx.AsyncClient | None = None


def _get_openalex_client() -> httpx.AsyncClient:
    global _openalex_client
    if _openalex_client is None or _openalex_client.is_closed:
        _openalex_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    return _openalex_client


def _uninvert_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """Convert OpenAlex inverted abstract index to plain text.

    OpenAlex stores abstracts as ``{"word": [pos1, pos2], ...}``.
    """
    if not inverted_index:
        return ""

    max_pos = -1
    for positions in inverted_index.values():
        for p in positions:
            if p > max_pos:
                max_pos = p

    if max_pos < 0:
        return ""

    words: list[str] = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for p in positions:
            if p <= max_pos:
                words[p] = word

    return " ".join(w for w in words if w)


def _parse_work(work: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAlex work object to our standard paper format."""
    # Title
    title = work.get("title") or ""

    # Authors
    authorships = work.get("authorships") or []
    authors: list[str] = []
    for a in authorships[:10]:
        author_obj = a.get("author") or {}
        name = author_obj.get("display_name")
        if name:
            authors.append(name)

    # Year
    year = str(work.get("publication_year") or "")

    # Abstract
    abstract = _uninvert_abstract(work.get("abstract_inverted_index"))
    if not abstract:
        # Some works have a plain abstract_text field (rare)
        abstract = work.get("abstract") or ""

    # Venue
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue = source.get("display_name") or ""

    # Citation count
    citation_count = work.get("cited_by_count") or 0

    # URL — prefer DOI, fallback to OpenAlex landing page
    doi = work.get("doi") or ""
    openalex_id = work.get("id") or ""
    url = doi if doi else openalex_id

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "abstract": abstract[:800],
        "venue": venue,
        "citation_count": citation_count,
        "url": url,
        "openalex_id": openalex_id,
    }


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

async def _fetch_openalex(
    query: str, max_results: int
) -> list[dict[str, Any]]:
    """Fetch works from OpenAlex API matching *query*."""
    params: dict[str, Any] = {
        "search": query,
        "per_page": min(max_results, 25),
        "select": (
            "id,title,authorships,publication_year,"
            "abstract_inverted_index,primary_location,"
            "cited_by_count,doi"
        ),
        "mailto": _CONTACT_EMAIL,
    }

    try:
        client = _get_openalex_client()
        resp = await client.get(_OPENALEX_WORKS_URL, params=params)
        resp.raise_for_status()

        data = resp.json()
        works = data.get("results") or []

        parsed = [_parse_work(w) for w in works if w.get("title")]

        logger.info(
            "openalex_fetch_ok",
            query=query[:80],
            status_code=resp.status_code,
            results_parsed=len(parsed),
            total_available=data.get("meta", {}).get("count", 0),
        )
        return parsed[:max_results]

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "openalex_http_error",
            status=exc.response.status_code,
            query=query[:80],
            response_body=exc.response.text[:500] if exc.response else "N/A",
        )
    except httpx.TimeoutException as exc:
        logger.error(
            "openalex_timeout",
            query=query[:80],
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "openalex_fetch_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            query=query[:80],
        )

    return []


# ---------------------------------------------------------------------------
# Public async API (mirrors scholar_tool interface)
# ---------------------------------------------------------------------------

async def search_openalex(
    query: str, max_results: int = 10
) -> dict[str, Any]:
    """Search OpenAlex for academic works matching *query*.

    Returns:
        Dict with ``query``, ``results`` list, ``result_count``, ``elapsed_s``.
    """
    start = time.perf_counter()
    results = await _fetch_openalex(query, max_results)
    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "openalex_search_complete",
        query=query[:80],
        result_count=len(results),
        elapsed_s=elapsed,
    )

    return {
        "query": query,
        "results": results,
        "result_count": len(results),
        "elapsed_s": elapsed,
    }


async def search_openalex_multi(
    queries: list[str], max_per_query: int = 3
) -> dict[str, Any]:
    """Search OpenAlex for multiple queries and deduplicate results.

    Unlike Google Scholar scraping, OpenAlex allows concurrent requests,
    so we use ``asyncio.gather`` for speed — then deduplicate by title.

    Returns:
        Dict with ``queries_searched``, ``total_results``, ``results``,
        ``elapsed_s``.
    """
    start = time.perf_counter()

    # Run all queries concurrently (OpenAlex allows it)
    tasks = [search_openalex(q, max_results=max_per_query) for q in queries]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    empty_queries = 0

    for i, r in enumerate(raw_results):
        if isinstance(r, Exception):
            logger.error(
                "openalex_query_exception",
                query_index=i,
                error=str(r),
                error_type=type(r).__name__,
            )
            empty_queries += 1
            continue

        query_results = r.get("results", [])
        if not query_results:
            empty_queries += 1

        for item in query_results:
            title_key = item["title"].lower().strip()
            if title_key and title_key not in seen_titles:
                seen_titles.add(title_key)
                all_results.append(item)

    elapsed = round(time.perf_counter() - start, 3)

    if empty_queries == len(queries):
        logger.warning(
            "openalex_all_queries_empty",
            total_queries=len(queries),
            message="All OpenAlex queries returned 0 results.",
        )
    elif empty_queries > 0:
        logger.info(
            "openalex_partial_empty",
            total_queries=len(queries),
            empty_queries=empty_queries,
            successful_queries=len(queries) - empty_queries,
        )

    logger.info(
        "openalex_multi_search_complete",
        queries=len(queries),
        total_results=len(all_results),
        empty_queries=empty_queries,
        elapsed_s=elapsed,
    )

    return {
        "queries_searched": len(queries),
        "total_results": len(all_results),
        "results": all_results,
        "elapsed_s": elapsed,
    }
