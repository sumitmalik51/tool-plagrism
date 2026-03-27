"""Reference validation tool — verifies that cited works actually exist.

Uses OpenAlex API to validate DOIs, titles, and author names from a
document's reference section. Identifies potentially fabricated citations.
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
_CONTACT_EMAIL = "plagiarismguard@example.com"

# --- DOI extraction ---

_DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/)?10\.\d{4,9}/[^\s,;}\]\"')]+",
    re.IGNORECASE,
)

# --- Reference line patterns ---

# Numbered: [1] Author, Title...
_NUMBERED_REF_LINE = re.compile(r"^\s*\[(\d+)\]\s*(.+)", re.MULTILINE)

# APA: Author, A. A. (2020). Title...
_APA_REF_LINE = re.compile(
    r"(?m)^\s*([A-Z][a-zA-Z\-',\.\s]+?)\((\d{4}[a-z]?)\)\.\s*(.+?)(?:\.\s|$)"
)


def extract_references(text: str) -> list[dict[str, Any]]:
    """Extract references from the reference section of a document.

    Returns a list of dicts with: number, raw_text, doi (if found),
    title_fragment, year.
    """
    refs: list[dict[str, Any]] = []

    # Try numbered references first
    for m in _NUMBERED_REF_LINE.finditer(text):
        ref_num = int(m.group(1))
        raw = m.group(2).strip()
        doi_match = _DOI_RE.search(raw)
        doi = doi_match.group(0) if doi_match else None
        # Normalize DOI
        if doi and not doi.startswith("10."):
            doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)

        # Try to extract year
        year_match = re.search(r"\b(19|20)\d{2}\b", raw)
        year = year_match.group(0) if year_match else None

        # Title fragment: text between quotes or after year
        title = ""
        quote_match = re.search(r'"([^"]{10,})"', raw)
        if quote_match:
            title = quote_match.group(1)
        elif year_match:
            after_year = raw[year_match.end():]
            # Take next sentence-like fragment
            title_m = re.match(r"[\.\),\s]*(.+?)[\.]", after_year)
            if title_m:
                title = title_m.group(1).strip()

        refs.append({
            "number": ref_num,
            "raw_text": raw[:300],
            "doi": doi,
            "title_fragment": title[:200] if title else "",
            "year": year,
        })

    # Try APA-style if no numbered refs found
    if not refs:
        for m in _APA_REF_LINE.finditer(text):
            authors = m.group(1).strip()
            year = m.group(2)
            rest = m.group(3).strip()

            doi_match = _DOI_RE.search(rest)
            doi = doi_match.group(0) if doi_match else None
            if doi and not doi.startswith("10."):
                doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)

            # Title is typically the first sentence after year
            title_m = re.match(r"(.+?)[\.]", rest)
            title = title_m.group(1).strip() if title_m else rest[:100]

            refs.append({
                "number": len(refs) + 1,
                "raw_text": f"{authors} ({year}). {rest}"[:300],
                "doi": doi,
                "title_fragment": title[:200],
                "year": year,
                "authors": authors,
            })

    return refs


async def _validate_by_doi(doi: str) -> dict[str, Any]:
    """Validate a reference by DOI lookup via OpenAlex."""
    url = f"{_OPENALEX_WORKS_URL}/https://doi.org/{doi}"
    params = {"mailto": _CONTACT_EMAIL}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                work = resp.json()
                return {
                    "found": True,
                    "method": "doi",
                    "title": work.get("title", ""),
                    "year": work.get("publication_year"),
                    "doi": doi,
                    "openalex_id": work.get("id", ""),
                    "cited_by_count": work.get("cited_by_count", 0),
                }
            elif resp.status_code == 404:
                return {"found": False, "method": "doi", "doi": doi,
                        "reason": "DOI not found in OpenAlex"}
    except Exception as exc:
        logger.warning("doi_validation_error", doi=doi, error=str(exc))

    return {"found": False, "method": "doi", "doi": doi, "reason": "lookup_failed"}


async def _validate_by_title(title: str, year: str | None = None) -> dict[str, Any]:
    """Validate a reference by title search via OpenAlex."""
    if not title or len(title) < 10:
        return {"found": False, "method": "title", "reason": "title_too_short"}

    params: dict[str, Any] = {
        "search": title,
        "per_page": 3,
        "select": "id,title,publication_year,doi,cited_by_count",
        "mailto": _CONTACT_EMAIL,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_OPENALEX_WORKS_URL, params=params)
            if resp.status_code != 200:
                return {"found": False, "method": "title", "reason": "api_error"}

            results = resp.json().get("results", [])
            if not results:
                return {"found": False, "method": "title", "reason": "no_matching_works"}

            # Check if any result title closely matches
            for work in results:
                work_title = (work.get("title") or "").lower().strip()
                query_title = title.lower().strip()

                # Simple overlap check
                if len(query_title) > 15:
                    common = set(query_title.split()) & set(work_title.split())
                    overlap = len(common) / max(len(query_title.split()), 1)
                    if overlap >= 0.6:
                        # Year check if available
                        if year and work.get("publication_year"):
                            if str(work["publication_year"]) != str(year):
                                continue  # Year mismatch, skip
                        return {
                            "found": True,
                            "method": "title",
                            "title": work.get("title", ""),
                            "year": work.get("publication_year"),
                            "doi": work.get("doi", ""),
                            "openalex_id": work.get("id", ""),
                            "cited_by_count": work.get("cited_by_count", 0),
                        }

            return {"found": False, "method": "title", "reason": "no_close_title_match"}

    except Exception as exc:
        logger.warning("title_validation_error", title=title[:50], error=str(exc))

    return {"found": False, "method": "title", "reason": "lookup_failed"}


async def validate_references(text: str) -> dict[str, Any]:
    """Extract references from text and validate each against OpenAlex.

    Returns a structured report with validated/unverified/suspicious refs.
    """
    start = time.perf_counter()

    refs = extract_references(text)
    if not refs:
        return {
            "total_references": 0,
            "validated": 0,
            "unverified": 0,
            "suspicious": 0,
            "results": [],
            "elapsed_s": 0.0,
        }

    logger.info("validating_references", count=len(refs))

    # Validate each reference (prefer DOI, fall back to title search)
    async def _validate_one(ref: dict) -> dict:
        if ref.get("doi"):
            result = await _validate_by_doi(ref["doi"])
        elif ref.get("title_fragment"):
            result = await _validate_by_title(ref["title_fragment"], ref.get("year"))
        else:
            result = {"found": False, "method": "none", "reason": "no_doi_or_title"}

        return {**ref, "validation": result}

    # Run validations concurrently (batched to avoid rate limits)
    batch_size = 10
    validated_refs: list[dict] = []
    for i in range(0, len(refs), batch_size):
        batch = refs[i:i + batch_size]
        results = await asyncio.gather(
            *[_validate_one(r) for r in batch],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                validated_refs.append({"validation": {"found": False, "reason": str(r)}})
            else:
                validated_refs.append(r)

    # Categorize results
    found_count = sum(1 for r in validated_refs if r.get("validation", {}).get("found"))
    not_found = [r for r in validated_refs if not r.get("validation", {}).get("found")]

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "reference_validation_complete",
        total=len(refs),
        validated=found_count,
        unverified=len(not_found),
        elapsed_s=elapsed,
    )

    return {
        "total_references": len(refs),
        "validated": found_count,
        "unverified": len(not_found),
        "suspicious": len([r for r in not_found
                          if r.get("validation", {}).get("reason") not in ("lookup_failed", "title_too_short")]),
        "results": validated_refs,
        "elapsed_s": elapsed,
    }
