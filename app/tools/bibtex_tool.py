"""BibTeX export tool — converts paper metadata to BibTeX format.

Accepts a list of paper metadata dicts (from OpenAlex, arXiv, or Scholar)
and produces a valid BibTeX string for reference management.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _sanitize_key(text: str) -> str:
    """Create a valid BibTeX citation key from text."""
    # Normalize unicode to ASCII-safe equivalents
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    # Keep only alphanumeric and underscores
    text = re.sub(r"[^a-zA-Z0-9]", "", text)
    return text[:40] if text else "unknown"


def _escape_bibtex(value: str) -> str:
    """Escape special BibTeX characters in a field value."""
    # Replace special LaTeX characters
    for char, replacement in [("&", r"\&"), ("%", r"\%"), ("$", r"\$"),
                               ("#", r"\#"), ("_", r"\_"), ("~", r"\textasciitilde{}"),
                               ("^", r"\textasciicircum{}")]:
        value = value.replace(char, replacement)
    return value


def paper_to_bibtex(paper: dict[str, Any], index: int = 0) -> str:
    """Convert a single paper metadata dict to a BibTeX entry.

    Args:
        paper: Dict with keys like title, authors, year, abstract, url, venue.
        index: Fallback index for generating unique citation keys.

    Returns:
        A single BibTeX entry string.
    """
    title = paper.get("title", "Untitled")
    authors = paper.get("authors", [])
    year = str(paper.get("year", ""))
    abstract = paper.get("abstract", "")
    url = paper.get("url", "") or paper.get("doi", "")
    venue = paper.get("venue", "")
    arxiv_id = paper.get("arxiv_id", "")
    doi = paper.get("doi", "")

    # Build citation key: first_author_last_name + year + first_title_word
    if authors and isinstance(authors, list) and authors[0]:
        first_author = authors[0].split()[-1] if authors[0] else "unknown"
    else:
        first_author = "unknown"
    title_word = title.split()[0] if title else "untitled"
    cite_key = _sanitize_key(f"{first_author}{year}{title_word}")
    if not cite_key:
        cite_key = f"paper{index}"

    # Format authors in BibTeX style: "Last, First and Last, First"
    author_strs: list[str] = []
    if isinstance(authors, list):
        for a in authors[:10]:
            parts = str(a).strip().split()
            if len(parts) >= 2:
                author_strs.append(f"{parts[-1]}, {' '.join(parts[:-1])}")
            elif parts:
                author_strs.append(parts[0])
    author_field = " and ".join(author_strs) if author_strs else "Unknown"

    # Determine entry type
    entry_type = "article"
    if arxiv_id:
        entry_type = "misc"  # arXiv preprints are typically @misc

    # Build fields
    fields: list[str] = [
        f"  title = {{{_escape_bibtex(title)}}}",
        f"  author = {{{_escape_bibtex(author_field)}}}",
    ]
    if year:
        fields.append(f"  year = {{{year}}}")
    if venue:
        if entry_type == "article":
            fields.append(f"  journal = {{{_escape_bibtex(venue)}}}")
        else:
            fields.append(f"  howpublished = {{{_escape_bibtex(venue)}}}")
    if url:
        fields.append(f"  url = {{{url}}}")
    if doi and doi.startswith("https://doi.org/"):
        fields.append(f"  doi = {{{doi.replace('https://doi.org/', '')}}}")
    elif doi:
        fields.append(f"  doi = {{{doi}}}")
    if arxiv_id:
        fields.append(f"  eprint = {{{arxiv_id}}}")
        fields.append("  archiveprefix = {arXiv}")
    if abstract:
        fields.append(f"  abstract = {{{_escape_bibtex(abstract[:500])}}}")

    fields_str = ",\n".join(fields)
    return f"@{entry_type}{{{cite_key},\n{fields_str}\n}}"


def papers_to_bibtex(papers: list[dict[str, Any]]) -> str:
    """Convert a list of paper metadata dicts to a BibTeX string.

    Args:
        papers: List of paper dicts from OpenAlex/arXiv/Scholar tools.

    Returns:
        Complete BibTeX string with all entries.
    """
    if not papers:
        return ""

    entries: list[str] = []
    seen_keys: set[str] = set()

    for i, paper in enumerate(papers):
        entry = paper_to_bibtex(paper, index=i)
        # Extract key and deduplicate
        match = re.match(r"@\w+\{(\w+),", entry)
        if match:
            key = match.group(1)
            if key in seen_keys:
                # Append index to make unique
                new_key = f"{key}{i}"
                entry = entry.replace(f"{{{key},", f"{{{new_key},", 1)
                key = new_key
            seen_keys.add(key)
        entries.append(entry)

    result = "\n\n".join(entries)
    logger.info("bibtex_export_complete", paper_count=len(papers), entry_count=len(entries))
    return result
