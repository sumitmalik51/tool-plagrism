"""Web search tool — searches the web for matching content.

Standalone, framework-agnostic tool. Returns structured JSON.

Search backends (tried in order):
1. Bing Search API v7 — if ``PG_BING_API_KEY`` is set and valid.
2. DuckDuckGo — free fallback, no API key required.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

BING_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/search"


# ---------------------------------------------------------------------------
# Bing backend
# ---------------------------------------------------------------------------

async def _search_bing(query: str, count: int) -> dict | None:
    """Try Bing Search API.  Returns *None* on auth failure so caller can
    fall through to the next backend."""
    api_key = settings.bing_api_key
    if not api_key:
        return None

    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": min(count, 50), "mkt": "en-US"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(BING_SEARCH_URL, headers=headers, params=params)
            if response.status_code == 401:
                logger.warning("bing_api_key_unauthorized", hint="falling back to DuckDuckGo")
                return None
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.error("bing_search_http_error", error=str(exc))
        return None

    results = []
    for item in data.get("webPages", {}).get("value", []):
        results.append({
            "url": item.get("url", ""),
            "title": item.get("name", ""),
            "snippet": item.get("snippet", ""),
        })
    return {"results": results}


# ---------------------------------------------------------------------------
# DuckDuckGo backend (free, no key)
# ---------------------------------------------------------------------------

def _search_ddg_sync(query: str, count: int) -> list[dict]:
    """Run DuckDuckGo search synchronously (the library is sync-only)."""
    from ddgs import DDGS  # lazy import

    results: list[dict] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=count):
                results.append({
                    "url": r.get("href", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                })
    except Exception as exc:  # noqa: BLE001
        logger.error("ddg_search_failed", error=str(exc))
    return results


async def _search_ddg(query: str, count: int) -> dict:
    """Async wrapper around the sync DuckDuckGo library."""
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, _search_ddg_sync, query, count)
    return {"results": results}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_web(query: str, count: int = 5) -> dict:
    """Search the web for *query*, returning up to *count* results.

    Tries Bing first (if key configured & valid), then DuckDuckGo.

    Returns:
        Dict with ``query``, ``results`` (list of dicts with url, title, snippet),
        ``result_count``, ``elapsed_s``.
    """
    start = time.perf_counter()

    # 1. Try Bing
    bing = await _search_bing(query, count)
    if bing is not None:
        elapsed = round(time.perf_counter() - start, 3)
        logger.info("web_search_complete", backend="bing", query=query[:80],
                     result_count=len(bing["results"]), elapsed_s=elapsed)
        return {"query": query, "results": bing["results"],
                "result_count": len(bing["results"]), "elapsed_s": elapsed}

    # 2. Fallback to DuckDuckGo
    ddg = await _search_ddg(query, count)
    elapsed = round(time.perf_counter() - start, 3)
    logger.info("web_search_complete", backend="duckduckgo", query=query[:80],
                 result_count=len(ddg["results"]), elapsed_s=elapsed)
    return {"query": query, "results": ddg["results"],
            "result_count": len(ddg["results"]), "elapsed_s": elapsed}


async def search_multiple(queries: list[str], count_per_query: int = 3) -> dict:
    """Run multiple web searches and aggregate results.

    Returns:
        Dict with ``total_results``, ``queries_searched``, and ``results``
        (deduplicated by URL).
    """
    import asyncio

    start = time.perf_counter()

    tasks = [search_web(q, count=count_per_query) for q in queries]
    raw_results = await asyncio.gather(*tasks)

    seen_urls: set[str] = set()
    all_results: list[dict] = []
    for r in raw_results:
        for item in r.get("results", []):
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_results.append(item)

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "multi_search_complete",
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
