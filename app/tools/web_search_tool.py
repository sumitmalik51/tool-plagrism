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

# ISO language code → Bing market / DDG region
_LANG_TO_MARKET: dict[str, str] = {
    "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE",
    "pt": "pt-BR", "it": "it-IT", "hi": "hi-IN", "zh": "zh-CN",
    "ja": "ja-JP", "ar": "ar-SA", "ko": "ko-KR",
}

_LANG_TO_DDG_REGION: dict[str, str] = {
    "en": "us-en", "es": "es-es", "fr": "fr-fr", "de": "de-de",
    "pt": "br-pt", "it": "it-it", "hi": "in-en", "zh": "cn-zh",
    "ja": "jp-jp", "ar": "xa-ar", "ko": "kr-kr",
}


# ---------------------------------------------------------------------------
# Bing backend
# ---------------------------------------------------------------------------

async def _search_bing(query: str, count: int, language: str = "en") -> dict | None:
    """Try Bing Search API.  Returns *None* on auth failure so caller can
    fall through to the next backend."""
    api_key = settings.bing_api_key
    if not api_key:
        return None

    headers = {"Ocp-Apim-Subscription-Key": api_key}
    mkt = _LANG_TO_MARKET.get(language, "en-US")
    params = {"q": query, "count": min(count, 50), "mkt": mkt}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
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

def _search_ddg_sync(query: str, count: int, language: str = "en") -> list[dict]:
    """Run DuckDuckGo search synchronously (the library is sync-only)."""
    results: list[dict] = []
    try:
        from ddgs import DDGS  # lazy import

        region = _LANG_TO_DDG_REGION.get(language, "us-en")
        with DDGS() as ddgs:
            for r in ddgs.text(query, region=region, max_results=count):
                results.append({
                    "url": r.get("href", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                })
    except ImportError:
        logger.warning("ddgs_not_installed", hint="pip install ddgs")
    except Exception as exc:  # noqa: BLE001
        logger.error("ddg_search_failed", error=str(exc))
    return results


async def _search_ddg(query: str, count: int, language: str = "en") -> dict:
    """Async wrapper around the sync DuckDuckGo library."""
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, _search_ddg_sync, query, count, language)
    return {"results": results}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_web(query: str, count: int = 10, language: str = "en") -> dict:
    """Search the web for *query*, returning up to *count* results.

    Tries Bing first (if key configured & valid), then DuckDuckGo.
    The *language* code (e.g. ``"es"``, ``"fr"``) localises results.

    Returns:
        Dict with ``query``, ``results`` (list of dicts with url, title, snippet),
        ``result_count``, ``elapsed_s``.
    """
    start = time.perf_counter()

    # 1. Try Bing
    bing = await _search_bing(query, count, language)
    if bing is not None:
        elapsed = round(time.perf_counter() - start, 3)
        logger.info("web_search_complete", backend="bing", query=query[:80],
                     result_count=len(bing["results"]), elapsed_s=elapsed)
        return {"query": query, "results": bing["results"],
                "result_count": len(bing["results"]), "elapsed_s": elapsed}

    # 2. Fallback to DuckDuckGo
    ddg = await _search_ddg(query, count, language)
    elapsed = round(time.perf_counter() - start, 3)
    logger.info("web_search_complete", backend="duckduckgo", query=query[:80],
                 result_count=len(ddg["results"]), elapsed_s=elapsed)
    return {"query": query, "results": ddg["results"],
            "result_count": len(ddg["results"]), "elapsed_s": elapsed}


async def search_multiple(queries: list[str], count_per_query: int = 3, language: str = "en") -> dict:
    """Run multiple web searches and aggregate results.

    Returns:
        Dict with ``total_results``, ``queries_searched``, and ``results``
        (deduplicated by URL).
    """
    import asyncio

    start = time.perf_counter()

    tasks = [search_web(q, count=count_per_query, language=language) for q in queries]
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


# ---------------------------------------------------------------------------
# Page content fetcher
# ---------------------------------------------------------------------------

import re as _re

_TAG_RE = _re.compile(r"<[^>]+>")
_MULTI_WS = _re.compile(r"\s{3,}")


def _html_to_text(html: str) -> str:
    """Very lightweight HTML → plain-text conversion.

    Strips tags, collapses whitespace. Good enough for embedding comparison.
    """
    # Remove script and style blocks
    text = _re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=_re.DOTALL | _re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    text = _MULTI_WS.sub(" ", text)
    return text.strip()


async def _fetch_one(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    """Fetch a single URL and return ``(url, plain_text)``."""
    try:
        resp = await client.get(
            url,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if resp.status_code != 200:
            return url, ""
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return url, ""
        html = resp.text
        return url, _html_to_text(html)
    except Exception:  # noqa: BLE001
        return url, ""


async def fetch_page_text(
    urls: list[str],
    timeout: float = 10.0,
    max_concurrent: int = 5,
) -> dict[str, str]:
    """Fetch plain-text content from multiple URLs concurrently.

    Args:
        urls: URLs to fetch.
        timeout: Per-request timeout in seconds.
        max_concurrent: Max parallel requests.

    Returns:
        Dict mapping ``url → plain_text`` (empty string on failure).
    """
    if not urls:
        return {}

    start = time.perf_counter()
    sem = asyncio.Semaphore(max_concurrent)

    async def _guarded(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
        async with sem:
            return await _fetch_one(client, url)

    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [_guarded(client, u) for u in urls]
        results = await asyncio.gather(*tasks)

    mapping = {url: text for url, text in results}
    fetched = sum(1 for t in mapping.values() if t)
    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "pages_fetched",
        total=len(urls),
        fetched=fetched,
        elapsed_s=elapsed,
    )

    return mapping
