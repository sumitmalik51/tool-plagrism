"""arXiv academic search tool — searches arXiv.org for preprints and papers.

Uses the arXiv REST API (https://export.arxiv.org/api/query) to find academic
papers. No API key required. Returns structured results with title, authors,
year, abstract, arXiv ID, PDF URL, and category.

Provides the same output format as ``openalex_tool`` so the academic agent
can use either source interchangeably.
"""

from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

_ARXIV_API_URL = "https://export.arxiv.org/api/query"

_arxiv_client: httpx.AsyncClient | None = None

# XML namespaces used in arXiv Atom responses
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def _get_arxiv_client() -> httpx.AsyncClient:
    global _arxiv_client
    if _arxiv_client is None or _arxiv_client.is_closed:
        _arxiv_client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
    return _arxiv_client


def _parse_entry(entry: ET.Element) -> dict[str, Any]:
    """Convert an arXiv Atom entry to our standard paper format."""
    title = (entry.findtext("atom:title", "", _NS) or "").strip()
    title = re.sub(r"\s+", " ", title)  # collapse whitespace/newlines

    # Authors
    authors: list[str] = []
    for author_el in entry.findall("atom:author", _NS):
        name = (author_el.findtext("atom:name", "", _NS) or "").strip()
        if name:
            authors.append(name)

    # Abstract
    abstract = (entry.findtext("atom:summary", "", _NS) or "").strip()
    abstract = re.sub(r"\s+", " ", abstract)

    # Published date → year
    published = entry.findtext("atom:published", "", _NS) or ""
    year = published[:4] if len(published) >= 4 else ""

    # arXiv ID from <id> tag (e.g. http://arxiv.org/abs/2301.12345v1)
    raw_id = (entry.findtext("atom:id", "", _NS) or "").strip()
    arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id

    # PDF link
    pdf_url = ""
    for link_el in entry.findall("atom:link", _NS):
        if link_el.get("title") == "pdf":
            pdf_url = link_el.get("href", "")
            break

    # Primary category
    primary_cat = entry.find("arxiv:primary_category", _NS)
    category = primary_cat.get("term", "") if primary_cat is not None else ""

    # URL — prefer abstract page
    url = raw_id if raw_id else ""

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "abstract": abstract[:800],
        "venue": f"arXiv ({category})" if category else "arXiv",
        "citation_count": 0,  # arXiv API doesn't provide citation counts
        "url": url,
        "arxiv_id": arxiv_id,
        "pdf_url": pdf_url,
        "category": category,
    }


async def _fetch_arxiv(query: str, max_results: int) -> list[dict[str, Any]]:
    """Fetch papers from arXiv API matching *query*."""
    params: dict[str, Any] = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": min(max_results, 25),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    try:
        client = _get_arxiv_client()
        resp = await client.get(_ARXIV_API_URL, params=params)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", _NS)

        parsed = [_parse_entry(e) for e in entries if e.findtext("atom:title", "", _NS)]
        # Filter out empty titles
        parsed = [p for p in parsed if p["title"]]

        logger.info(
            "arxiv_fetch_ok",
            query=query[:80],
            status_code=resp.status_code,
            results_parsed=len(parsed),
        )
        return parsed[:max_results]

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "arxiv_http_error",
            status=exc.response.status_code,
            query=query[:80],
        )
    except httpx.TimeoutException:
        logger.error("arxiv_timeout", query=query[:80])
    except ET.ParseError as exc:
        logger.error("arxiv_xml_parse_error", error=str(exc), query=query[:80])
    except Exception as exc:
        logger.error(
            "arxiv_fetch_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            query=query[:80],
        )

    return []


async def search_arxiv(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search arXiv for papers matching *query*.

    Returns:
        Dict with ``query``, ``results`` list, ``result_count``, ``elapsed_s``.
    """
    start = time.perf_counter()
    results = await _fetch_arxiv(query, max_results)
    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "arxiv_search_complete",
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


async def search_arxiv_multi(
    queries: list[str], max_per_query: int = 3
) -> dict[str, Any]:
    """Search arXiv for multiple queries and deduplicate results.

    Returns:
        Dict with ``queries_searched``, ``total_results``, ``results``,
        ``elapsed_s``.
    """
    start = time.perf_counter()

    tasks = [search_arxiv(q, max_results=max_per_query) for q in queries]
    try:
        raw_results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=30.0
        )
    except asyncio.TimeoutError:
        logger.warning("arxiv_multi_timed_out", query_count=len(queries))
        raw_results = []

    all_results: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    empty_queries = 0

    for i, r in enumerate(raw_results):
        if isinstance(r, Exception):
            logger.error(
                "arxiv_query_exception",
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

    logger.info(
        "arxiv_multi_search_complete",
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
