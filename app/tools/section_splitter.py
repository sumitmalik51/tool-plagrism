"""Section analysis tool — splits documents by headings for per-section plagiarism.

Detects section headers in academic papers (numbered, title-case, or Markdown-style)
and splits the document into logical sections for breakdown analysis.
"""

from __future__ import annotations

import re
from app.utils.logger import get_logger

logger = get_logger(__name__)

# --- Section header patterns for academic papers ---

# Numbered: "1. Introduction", "2.1 Background", "Chapter 3: Methods"
_NUMBERED_HEADING = re.compile(
    r"(?m)^[ \t]*(?:chapter\s+)?\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{2,80}$"
)

# Title-case line <= 80 chars, standalone (common in PDFs)
_TITLE_CASE_HEADING = re.compile(
    r"(?m)^[ \t]*[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|and|of|the|in|for|with|to|a|an)){1,10}\s*$"
)

# ALL CAPS headings like "ABSTRACT", "INTRODUCTION"
_UPPER_HEADING = re.compile(
    r"(?m)^[ \t]*[A-Z]{3,}(?:\s+[A-Z]{2,}){0,5}\s*$"
)

# LaTeX-style: \section{...}, \subsection{...}
_LATEX_HEADING = re.compile(
    r"(?m)^[ \t]*\\(?:sub)*section\*?\{([^}]+)\}"
)

# Markdown-style: # Heading, ## Heading
_MARKDOWN_HEADING = re.compile(
    r"(?m)^[ \t]*#{1,3}\s+(.+)$"
)

# Common academic section names (for validation)
_KNOWN_SECTIONS = {
    "abstract", "introduction", "background", "literature review",
    "related work", "methodology", "methods", "materials and methods",
    "experimental setup", "experiment", "experiments", "results",
    "discussion", "results and discussion", "analysis", "findings",
    "conclusion", "conclusions", "summary", "future work",
    "acknowledgements", "acknowledgments", "appendix", "appendices",
}


def _is_likely_heading(text: str) -> bool:
    """Check if a line is likely a section heading (not body text)."""
    stripped = text.strip()
    # Too long for a heading
    if len(stripped) > 100:
        return False
    # Too short
    if len(stripped) < 3:
        return False
    # Ends with period (likely a sentence, not heading)
    if stripped.endswith(".") and not stripped.endswith("etc."):
        return False
    return True


def split_into_sections(text: str) -> list[dict]:
    """Split document text into sections based on detected headings.

    Returns a list of dicts: [{title, text, start_char, end_char, word_count}]
    If no sections are detected, returns the whole document as one section.
    """
    if not text or len(text.strip()) < 100:
        return [{"title": "Full Document", "text": text, "start_char": 0,
                 "end_char": len(text), "word_count": len(text.split())}]

    # Collect all heading matches with positions
    headings: list[tuple[int, str]] = []

    # Try numbered headings first (most reliable for academic papers)
    for m in _NUMBERED_HEADING.finditer(text):
        line = m.group(0).strip()
        if _is_likely_heading(line):
            headings.append((m.start(), line))

    # LaTeX headings
    for m in _LATEX_HEADING.finditer(text):
        headings.append((m.start(), m.group(1).strip()))

    # Markdown headings
    for m in _MARKDOWN_HEADING.finditer(text):
        headings.append((m.start(), m.group(1).strip()))

    # ALL CAPS headings (only if few numbered ones found)
    if len(headings) < 3:
        for m in _UPPER_HEADING.finditer(text):
            line = m.group(0).strip()
            if len(line) > 3 and _is_likely_heading(line):
                headings.append((m.start(), line))

    # Deduplicate and sort by position
    seen_positions: set[int] = set()
    unique_headings: list[tuple[int, str]] = []
    for pos, title in sorted(headings, key=lambda h: h[0]):
        # Skip if too close to an existing heading (within 50 chars)
        if any(abs(pos - sp) < 50 for sp in seen_positions):
            continue
        seen_positions.add(pos)
        unique_headings.append((pos, title))

    if not unique_headings:
        return [{"title": "Full Document", "text": text, "start_char": 0,
                 "end_char": len(text), "word_count": len(text.split())}]

    # Build sections from heading positions
    sections: list[dict] = []

    # Text before first heading (if any)
    if unique_headings[0][0] > 200:
        preamble = text[:unique_headings[0][0]].strip()
        if preamble:
            sections.append({
                "title": "Preamble",
                "text": preamble,
                "start_char": 0,
                "end_char": unique_headings[0][0],
                "word_count": len(preamble.split()),
            })

    for i, (pos, title) in enumerate(unique_headings):
        if i + 1 < len(unique_headings):
            end = unique_headings[i + 1][0]
        else:
            end = len(text)

        section_text = text[pos:end].strip()
        sections.append({
            "title": title,
            "text": section_text,
            "start_char": pos,
            "end_char": end,
            "word_count": len(section_text.split()),
        })

    logger.info(
        "sections_detected",
        section_count=len(sections),
        headings=[s["title"] for s in sections],
    )

    return sections
