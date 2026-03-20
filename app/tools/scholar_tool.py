"""Google Scholar search tool — finds matching academic papers.

Uses lightweight HTTP scraping via ``httpx`` + regex parsing to search
Google Scholar.  No heavyweight dependencies (scholarly, selenium, sphinx)
are required.

Returns structured results with title, authors, year, snippet, and URLs.
"""

from __future__ import annotations

import asyncio
import html
import re
import time
import urllib.parse
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

_SCHOLAR_URL = "https://scholar.google.com/scholar"

# Regex patterns for parsing Google Scholar HTML
_RESULT_BLOCK = re.compile(
    r'<div class="gs_ri">(.*?)</div>\s*</div>\s*</div>',
    re.DOTALL,
)
_TITLE_LINK = re.compile(
    r'<h3[^>]*class="gs_rt"[^>]*>.*?<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_TITLE_NOLINK = re.compile(
    r'<h3[^>]*class="gs_rt"[^>]*>(.*?)</h3>',
    re.DOTALL,
)
_AUTHORS_LINE = re.compile(
    r'<div class="gs_a">(.*?)</div>',
    re.DOTALL,
)
_SNIPPET = re.compile(
    r'<div class="gs_rs">(.*?)</div>',
    re.DOTALL,
)
_CITED_BY = re.compile(r'Cited by (\d+)')


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _parse_authors_line(line: str) -> tuple[list[str], str, str]:
    """Parse the author/venue/year line from Scholar.

    Returns (authors, venue, year).
    """
    clean = _strip_tags(line)
    # Typical format: "A Smith, B Jones - Journal Name, 2023 - publisher.com"
    parts = clean.split(" - ", 2)
    authors = [a.strip() for a in parts[0].split(",") if a.strip()] if parts else []
    venue = ""
    year = ""
    if len(parts) >= 2:
        venue_year = parts[1]
        # Extract year (4 digits)
        year_match = re.search(r"\b(19|20)\d{2}\b", venue_year)
        if year_match:
            year = year_match.group(0)
            venue = venue_year[: year_match.start()].rstrip(", ")
        else:
            venue = venue_year.split(" - ")[0].strip()
    return authors, venue, year


def _parse_results(html_text: str, query: str) -> list[dict[str, Any]]:
    """Parse Google Scholar HTML into structured results."""
    results: list[dict[str, Any]] = []

    for block_match in _RESULT_BLOCK.finditer(html_text):
        block = block_match.group(1)

        # Title + URL
        title_link = _TITLE_LINK.search(block)
        if title_link:
            url = title_link.group(1)
            title = _strip_tags(title_link.group(2))
        else:
            title_nolink = _TITLE_NOLINK.search(block)
            title = _strip_tags(title_nolink.group(1)) if title_nolink else ""
            url = ""

        if not title:
            continue

        # Authors / venue / year
        authors_match = _AUTHORS_LINE.search(block)
        authors, venue, year = (
            _parse_authors_line(authors_match.group(1))
            if authors_match
            else ([], "", "")
        )

        # Snippet
        snippet_match = _SNIPPET.search(block)
        snippet = _strip_tags(snippet_match.group(1))[:500] if snippet_match else ""

        # Citation count
        cited_match = _CITED_BY.search(block)
        citation_count = int(cited_match.group(1)) if cited_match else 0

        encoded_q = urllib.parse.quote_plus(query)
        results.append({
            "title": title,
            "authors": authors,
            "year": year,
            "abstract": snippet,
            "venue": venue,
            "citation_count": citation_count,
            "url": url,
            "scholar_url": f"https://scholar.google.com/scholar?q={encoded_q}",
        })

    return results


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

async def _fetch_scholar(query: str, max_results: int) -> list[dict[str, Any]]:
    """Fetch and parse Google Scholar results via HTTP."""
    params = {
        "q": query,
        "hl": "en",
        "num": min(max_results, 20),
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0, follow_redirects=True
        ) as client:
            resp = await client.get(_SCHOLAR_URL, params=params, headers=headers)
            resp.raise_for_status()
            return _parse_results(resp.text, query)[:max_results]
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "scholar_http_error",
            status=exc.response.status_code,
            query=query[:80],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("scholar_fetch_failed", error=str(exc), query=query[:80])

    return []


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def search_scholar(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search Google Scholar for academic papers matching *query*.

    Returns:
        Dict with ``query``, ``results`` list, ``result_count``, ``elapsed_s``.
    """
    start = time.perf_counter()
    results = await _fetch_scholar(query, max_results)
    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "scholar_search_complete",
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


async def search_scholar_multi(
    queries: list[str], max_per_query: int = 3
) -> dict[str, Any]:
    """Search Google Scholar for multiple queries and deduplicate results.

    Returns:
        Dict with ``queries_searched``, ``total_results``, ``results``,
        ``elapsed_s``.
    """
    start = time.perf_counter()

    tasks = [search_scholar(q, max_results=max_per_query) for q in queries]
    raw_results = await asyncio.gather(*tasks)

    seen_titles: set[str] = set()
    all_results: list[dict[str, Any]] = []
    for r in raw_results:
        for item in r.get("results", []):
            title_key = item["title"].lower().strip()
            if title_key and title_key not in seen_titles:
                seen_titles.add(title_key)
                all_results.append(item)

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "scholar_multi_search_complete",
        queries=len(queries),
        total_results=len(all_results),
        elapsed_s=elapsed,
    )

    return {
        "queries_searched": len(queries),
        "total_results": len(all_results),
        "results": all_results,
        "elapsed_s": elapsed,
    }
