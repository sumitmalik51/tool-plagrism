"""Google Scholar search tool — finds matching academic papers.

Uses the ``scholarly`` library to search Google Scholar for papers related
to a given query.  Returns structured results with title, authors, year,
abstract snippet, citation count, and URLs.

Because ``scholarly`` is synchronous and network-bound, all public search
functions run in a thread-pool executor to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Synchronous helpers (run in executor)
# ---------------------------------------------------------------------------

def _search_scholar_sync(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search Google Scholar synchronously."""
    results: list[dict[str, Any]] = []
    try:
        from scholarly import scholarly  # lazy import — heavy first-call
        search_iter = scholarly.search_pubs(query)
        for _ in range(max_results):
            try:
                pub = next(search_iter)
            except StopIteration:
                break

            bib = pub.get("bib", {})
            results.append({
                "title": bib.get("title", ""),
                "authors": bib.get("author", []),
                "year": bib.get("pub_year", ""),
                "abstract": bib.get("abstract", "")[:500],
                "venue": bib.get("venue", ""),
                "citation_count": pub.get("num_citations", 0),
                "url": pub.get("pub_url", "") or pub.get("eprint_url", ""),
                "scholar_url": f"https://scholar.google.com/scholar?q={query.replace(' ', '+')}",
            })
    except Exception as exc:  # noqa: BLE001
        logger.error("scholar_search_failed", error=str(exc), query=query[:80])

    return results


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def search_scholar(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search Google Scholar for academic papers matching *query*.

    Returns:
        Dict with ``query``, ``results`` list, ``result_count``, ``elapsed_s``.
    """
    start = time.perf_counter()
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, _search_scholar_sync, query, max_results)
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


async def search_scholar_multi(queries: list[str], max_per_query: int = 3) -> dict[str, Any]:
    """Search Google Scholar for multiple queries and deduplicate results.

    Returns:
        Dict with ``queries_searched``, ``total_results``, ``results``, ``elapsed_s``.
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
