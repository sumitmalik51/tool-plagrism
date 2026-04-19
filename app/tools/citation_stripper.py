"""Citation stripper — removes citations and reference sections before plagiarism scanning.

Citations and bibliography sections are expected to match external sources and should
not count as plagiarism. This module strips them out before analysis so the scanner
focuses only on the author's original writing.
"""

from __future__ import annotations

import re
from app.utils.logger import get_logger

logger = get_logger(__name__)

# --- Patterns for reference / bibliography sections ---------------------------

# Section headers that start a references block.
# The prefix pattern handles common PDF markers like ■, ●, •, roman numerals,
# section numbers (e.g. "10. References"), brackets, etc.
# NOTE: We do NOT anchor to end-of-line ($) because two-column PDFs often
# merge the header with text from the adjacent column on the same line,
# e.g. "REFERENCES Ulanski, J.; Li, Y...."
_REF_HEADERS = re.compile(
    r"(?im)^\s*(?:[IVXLC]+[.\s]+|[\W\d_.]*)\s*"
    r"(?:references|bibliography|works?\s+cited|literature\s+cited"
    r"|further\s+reading|cited\s+works?|cited\s+references)\b"
)

# Numbered reference entries like (1) Author, (2) ..., [1] Author, etc.
_NUMBERED_REF = re.compile(r"(?m)^\s*(?:\[\d+\]|\(\d+\))\s+[A-Z]")

# APA-style entries: Author, A. A. (2020). Title...
_APA_REF = re.compile(
    r"(?m)^\s*[A-Z][a-zA-Z\-',\.\s]+\(\d{4}[a-z]?\)\.\s+.+"
)


def strip_reference_section(text: str) -> tuple[str, str]:
    """Remove the references/bibliography section from the end of a document.

    Returns:
        (cleaned_text, removed_section) — the text without references,
        and the removed references section (for transparency).
    """
    match = _REF_HEADERS.search(text)
    if not match:
        return text, ""

    ref_start = match.start()
    ref_pct = ref_start / len(text) * 100

    # Primary gate: must be in the last 55% of the document.
    # Review papers can have very large reference sections (40%+ of text).
    if ref_start < len(text) * 0.45:
        return text, ""

    # For matches between 45-60%, require secondary confirmation via numbered
    # reference entries to avoid false positives on mid-document section titles.
    if ref_start < len(text) * 0.60:
        candidate = text[ref_start:ref_start + 3000]
        numbered_refs = len(_NUMBERED_REF.findall(candidate))
        if numbered_refs < 3:
            logger.debug(
                "ref_header_rejected_insufficient_entries",
                position_pct=round(ref_pct, 1),
                numbered_refs=numbered_refs,
            )
            return text, ""

    removed = text[ref_start:]
    cleaned = text[:ref_start].rstrip()

    logger.info(
        "reference_section_stripped",
        ref_start_pct=round(ref_pct, 1),
        removed_chars=len(removed),
    )

    return cleaned, removed


# --- Inline citation patterns -----------------------------------------------

# [1], [1, 2], [1-3], [Author2020], [Author, 2020]
_BRACKET_CITE = re.compile(
    r"\[(?:\d+(?:\s*[-–,]\s*\d+)*|[A-Za-z]+(?:\s*(?:et\s+al\.?))?(?:,?\s*\d{4}[a-z]?)?)"
    r"(?:\s*[;,]\s*(?:\d+(?:\s*[-–,]\s*\d+)*|[A-Za-z]+(?:\s*(?:et\s+al\.?))?(?:,?\s*\d{4}[a-z]?)?)"
    r")*\]"
)

# (Author, 2020), (Author et al., 2020), (Author & Co, 2020; Author2, 2021)
_PAREN_CITE = re.compile(
    r"\("
    r"[A-Z][a-zA-Z\-']+"                                   # First author
    r"(?:\s+(?:et\s+al\.?|and|&)(?:\s+[A-Z][a-zA-Z\-']+)?)?"  # Optional: et al. OR co-author
    r",?\s*\d{4}[a-z]?"                                    # Year
    r"(?:\s*[;,]\s*"                                        # Separator for multi-cites
    r"[A-Z][a-zA-Z\-']+"
    r"(?:\s+(?:et\s+al\.?|and|&)(?:\s+[A-Z][a-zA-Z\-']+)?)?"
    r",?\s*\d{4}[a-z]?)*"
    r"\)"
)

# Superscript notation: plain digits after text like "text1,2" or "text1-3"
# Not reliable enough to strip — skip for now


def strip_inline_citations(text: str) -> str:
    """Remove inline citation markers from text.

    Keeps the surrounding sentence intact so the text reads naturally
    for similarity comparison.
    """
    result = _BRACKET_CITE.sub("", text)
    result = _PAREN_CITE.sub("", result)
    # Collapse double spaces left by removal
    result = re.sub(r"  +", " ", result)
    return result


def prepare_text_for_scanning(text: str) -> tuple[str, dict]:
    """Full citation-aware preprocessing pipeline.

    Returns:
        (cleaned_text, metadata) where metadata contains stats about
        what was removed.
    """
    original_len = len(text)

    # 1. Strip reference section
    text, removed_refs = strip_reference_section(text)

    # 2. Strip inline citations
    text = strip_inline_citations(text)

    metadata = {
        "original_length": original_len,
        "cleaned_length": len(text),
        "reference_section_removed": bool(removed_refs),
        "reference_section_length": len(removed_refs),
        "chars_removed": original_len - len(text),
    }

    logger.info("citation_aware_preprocessing", **metadata)

    return text, metadata
