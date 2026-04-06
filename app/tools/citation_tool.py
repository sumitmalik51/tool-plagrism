"""Citation generator tool — auto-generate formatted citations.

Supports APA 7, MLA 9, Chicago 17, and IEEE citation styles.
Works with source metadata from the plagiarism report.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from app.utils.logger import get_logger

logger = get_logger(__name__)

Style = Literal["apa", "mla", "chicago", "ieee"]

ALL_STYLES: list[Style] = ["apa", "mla", "chicago", "ieee"]


def _domain(url: str) -> str:
    """Extract clean domain from URL."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host.removeprefix("www.")
    except Exception:
        return url


def _today_str(style: Style) -> str:
    """Return today's date formatted for the given style."""
    now = datetime.now(timezone.utc)
    if style == "apa":
        return now.strftime("%B %d, %Y")  # January 15, 2026
    if style == "mla":
        return now.strftime("%d %b. %Y")  # 15 Jan. 2026
    if style == "chicago":
        return now.strftime("%B %d, %Y")
    # ieee
    return now.strftime("%b. %d, %Y")


def _format_apa(
    title: str | None,
    url: str | None,
    authors: list[str] | None,
    year: int | str | None,
    publisher: str | None,
) -> str:
    """APA 7th edition."""
    parts: list[str] = []

    if authors:
        parts.append(", ".join(authors))
    else:
        parts.append(_domain(url) if url else "Unknown Author")

    y = f"({year})" if year else "(n.d.)"
    parts.append(y)

    t = title or "Untitled"
    parts.append(f"*{t}*.")

    if publisher:
        parts.append(f"{publisher}.")

    if url:
        parts.append(f"Retrieved {_today_str('apa')}, from {url}")

    return " ".join(parts)


def _format_mla(
    title: str | None,
    url: str | None,
    authors: list[str] | None,
    year: int | str | None,
    publisher: str | None,
) -> str:
    """MLA 9th edition."""
    parts: list[str] = []

    if authors:
        # MLA: Last, First. for first author
        parts.append(f"{authors[0]}.")
    else:
        pass  # start with title

    t = f'"{title}"' if title else '"Untitled"'
    parts.append(f"{t}.")

    if publisher:
        parts.append(f"*{publisher}*,")
    elif url:
        parts.append(f"*{_domain(url)}*,")

    if year:
        parts.append(f"{year}.")

    if url:
        parts.append(f"{url}.")

    parts.append(f"Accessed {_today_str('mla')}.")

    return " ".join(parts)


def _format_chicago(
    title: str | None,
    url: str | None,
    authors: list[str] | None,
    year: int | str | None,
    publisher: str | None,
) -> str:
    """Chicago 17th edition (notes-bibliography)."""
    parts: list[str] = []

    if authors:
        parts.append(f"{authors[0]}.")
    else:
        parts.append(f"{_domain(url)}." if url else "Unknown Author.")

    t = f'"{title}"' if title else '"Untitled"'
    parts.append(f"{t}.")

    if publisher:
        parts.append(f"{publisher}.")

    if year:
        parts.append(f"Last modified {year}.")

    if url:
        parts.append(f"Accessed {_today_str('chicago')}. {url}.")

    return " ".join(parts)


def _format_ieee(
    title: str | None,
    url: str | None,
    authors: list[str] | None,
    year: int | str | None,
    publisher: str | None,
    ref_number: int = 1,
) -> str:
    """IEEE citation style."""
    parts: list[str] = []

    parts.append(f"[{ref_number}]")

    if authors:
        parts.append(f"{', '.join(authors)},")
    else:
        parts.append(f"{_domain(url)}," if url else "Unknown,")

    t = f'"{title}"' if title else '"Untitled"'
    parts.append(f"{t},")

    if publisher:
        parts.append(f"*{publisher}*,")

    if year:
        parts.append(f"{year}.")
    else:
        parts.append("n.d.")

    if url:
        parts.append(f"[Online]. Available: {url}.")
        parts.append(f"[Accessed: {_today_str('ieee')}].")

    return " ".join(parts)


def generate_citation(
    style: Style,
    *,
    title: str | None = None,
    url: str | None = None,
    authors: list[str] | None = None,
    year: int | str | None = None,
    publisher: str | None = None,
    ref_number: int = 1,
) -> str:
    """Generate a single citation in the given style."""
    if style == "apa":
        return _format_apa(title, url, authors, year, publisher)
    if style == "mla":
        return _format_mla(title, url, authors, year, publisher)
    if style == "chicago":
        return _format_chicago(title, url, authors, year, publisher)
    if style == "ieee":
        return _format_ieee(title, url, authors, year, publisher, ref_number)
    return _format_apa(title, url, authors, year, publisher)


def generate_citations_from_sources(
    sources: list[dict],
    style: Style = "apa",
) -> dict:
    """Generate citations for all detected sources from a plagiarism report.

    Args:
        sources: List of source dicts with url, title, similarity, source_type.
        style: Citation style to use.

    Returns:
        Dict with citations list, style, count, elapsed_s.
    """
    start = time.perf_counter()

    citations: list[dict] = []

    for idx, src in enumerate(sources, start=1):
        url = src.get("url")
        title = src.get("title")
        source_type = src.get("source_type", "Internet")
        similarity = src.get("similarity", 0)

        # Try to extract year from URL or title
        year = None
        for text_to_check in [url or "", title or ""]:
            year_match = re.search(r"20[12]\d", text_to_check)
            if year_match:
                year = int(year_match.group())
                break

        # Try to extract authors from source
        authors = src.get("authors") or None

        publisher = None
        if url:
            domain = _domain(url)
            if domain and domain not in (title or "").lower():
                publisher = domain

        citation_text = generate_citation(
            style,
            title=title,
            url=url,
            authors=authors,
            year=year,
            publisher=publisher,
            ref_number=idx,
        )

        citations.append({
            "ref_number": idx,
            "citation": citation_text,
            "style": style,
            "source_url": url,
            "source_title": title,
            "source_type": source_type,
            "similarity": similarity,
        })

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "citations_generated",
        style=style,
        count=len(citations),
        elapsed_s=elapsed,
    )

    return {
        "citations": citations,
        "style": style,
        "count": len(citations),
        "elapsed_s": elapsed,
    }
