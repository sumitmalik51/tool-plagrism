"""Web search tool — searches the web for matching content via Bing Search API.

Standalone, framework-agnostic tool. Returns structured JSON.
Requires BING_API_KEY environment variable.
"""

from __future__ import annotations

import time

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

BING_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/search"


async def search_web(query: str, count: int = 5) -> dict:
    """Search the web using Bing Search API.

    Args:
        query: Search query string.
        count: Number of results to return (max 50).

    Returns:
        Dict with ``query``, ``results`` (list of dicts with url, title, snippet),
        ``result_count``, ``elapsed_s``.
    """
    api_key = settings.bing_api_key

    if not api_key:
        logger.warning("bing_api_key_not_set")
        return {
            "query": query,
            "results": [],
            "result_count": 0,
            "elapsed_s": 0.0,
            "error": "BING_API_KEY not configured",
        }

    start = time.perf_counter()

    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": min(count, 50), "mkt": "en-US"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(BING_SEARCH_URL, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        elapsed = round(time.perf_counter() - start, 3)
        logger.error("web_search_failed", error=str(exc), elapsed_s=elapsed)
        return {
            "query": query,
            "results": [],
            "result_count": 0,
            "elapsed_s": elapsed,
            "error": str(exc),
        }

    elapsed = round(time.perf_counter() - start, 3)

    results = []
    for item in data.get("webPages", {}).get("value", []):
        results.append({
            "url": item.get("url", ""),
            "title": item.get("name", ""),
            "snippet": item.get("snippet", ""),
        })

    logger.info(
        "web_search_complete",
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
