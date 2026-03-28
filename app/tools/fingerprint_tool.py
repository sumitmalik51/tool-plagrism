"""N-gram fingerprinting tool — detects exact and near-exact text matches.

Uses winnowing (a rolling hash fingerprint algorithm) to identify copied passages.
This catches direct copy-paste and light word substitution that embedding-based
similarity may miss.

The algorithm:
1. Normalize text (lowercase, strip punctuation, collapse whitespace).
2. Generate character-level n-grams (shingles) of length k.
3. Hash each shingle using a rolling hash.
4. Select fingerprints using the winnowing algorithm (min hash in each window).
5. Compare fingerprint sets between document and reference using Jaccard similarity.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = _PUNCT_RE.sub("", text)
    text = _MULTI_WS.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Hashing & winnowing
# ---------------------------------------------------------------------------

def _rolling_hashes(text: str, k: int) -> list[int]:
    """Generate k-gram hashes using a simple polynomial rolling hash."""
    if len(text) < k:
        return []
    hashes = []
    for i in range(len(text) - k + 1):
        gram = text[i : i + k]
        h = int(hashlib.md5(gram.encode("utf-8")).hexdigest()[:8], 16)
        hashes.append(h)
    return hashes


def _winnow(hashes: list[int], window_size: int) -> list[tuple[int, int]]:
    """Winnowing algorithm — selects representative fingerprints.

    For each window of `window_size` consecutive hashes, picks the minimum.
    Adjacent duplicate picks are merged.

    Returns list of (hash_value, position) tuples.
    """
    if not hashes or window_size < 1:
        return []

    fingerprints: list[tuple[int, int]] = []
    prev_pos = -1

    for i in range(len(hashes) - window_size + 1):
        window = hashes[i : i + window_size]
        min_val = min(window)
        min_pos = i + window.index(min_val)

        if min_pos != prev_pos:
            fingerprints.append((min_val, min_pos))
            prev_pos = min_pos

    return fingerprints


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_fingerprints(
    text: str,
    *,
    k: int = 25,
    window_size: int = 4,
) -> dict[str, Any]:
    """Generate fingerprints for a text document.

    Args:
        text: Raw text content.
        k: Character n-gram size (shingle length). Larger = fewer false positives.
        window_size: Winnowing window size. Smaller = more fingerprints.

    Returns:
        Dict with ``fingerprints`` (set of hash ints), ``count``,
        ``normalized_length``.
    """
    normalized = _normalize(text)
    if len(normalized) < k:
        return {"fingerprints": set(), "count": 0, "normalized_length": len(normalized)}

    hashes = _rolling_hashes(normalized, k)
    fp_pairs = _winnow(hashes, window_size)
    fp_set = {h for h, _ in fp_pairs}

    return {
        "fingerprints": fp_set,
        "count": len(fp_set),
        "normalized_length": len(normalized),
    }


def compare_fingerprints(
    doc_fps: set[int],
    ref_fps: set[int],
) -> dict[str, Any]:
    """Compare two fingerprint sets using Jaccard similarity.

    Returns:
        Dict with ``jaccard`` (0-1), ``overlap_count``, ``doc_count``,
        ``ref_count``.
    """
    if not doc_fps or not ref_fps:
        return {"jaccard": 0.0, "overlap_count": 0, "doc_count": len(doc_fps), "ref_count": len(ref_fps)}

    overlap = doc_fps & ref_fps
    union = doc_fps | ref_fps
    jaccard = len(overlap) / len(union) if union else 0.0

    return {
        "jaccard": round(jaccard, 4),
        "overlap_count": len(overlap),
        "doc_count": len(doc_fps),
        "ref_count": len(ref_fps),
    }


def fingerprint_match_score(
    doc_text: str,
    ref_texts: list[str],
    *,
    k: int = 25,
    window_size: int = 4,
    threshold: float = 0.05,
) -> dict[str, Any]:
    """Compare a document against multiple reference texts using fingerprinting.

    A Jaccard of 0.05+ between a document and a single web page is significant
    — it means ~5% of the unique text patterns are shared verbatim.

    Args:
        doc_text: The document text.
        ref_texts: List of reference texts to compare against.
        k: Shingle size.
        window_size: Winnowing window.
        threshold: Minimum Jaccard to flag a match.

    Returns:
        Dict with ``score`` (0-100), ``matches`` list, ``elapsed_s``.
    """
    start = time.perf_counter()

    doc_fp = generate_fingerprints(doc_text, k=k, window_size=window_size)
    doc_set = doc_fp["fingerprints"]

    if not doc_set:
        return {"score": 0.0, "matches": [], "elapsed_s": 0.0}

    matches: list[dict] = []
    max_jaccard = 0.0

    for i, ref in enumerate(ref_texts):
        if not ref or len(ref.strip()) < k:
            continue
        ref_fp = generate_fingerprints(ref, k=k, window_size=window_size)
        comparison = compare_fingerprints(doc_set, ref_fp["fingerprints"])

        if comparison["jaccard"] >= threshold:
            matches.append({
                "ref_index": i,
                "jaccard": comparison["jaccard"],
                "overlap_count": comparison["overlap_count"],
            })
            max_jaccard = max(max_jaccard, comparison["jaccard"])

    # Score: scale Jaccard to 0-100.
    # Jaccard 0.05 = borderline, 0.15 = moderate, 0.30+ = heavy copying
    score = min(max_jaccard * 300, 100.0)
    score = round(score, 2)

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "fingerprint_match_complete",
        score=score,
        match_count=len(matches),
        max_jaccard=round(max_jaccard, 4),
        elapsed_s=elapsed,
    )

    return {
        "score": score,
        "matches": sorted(matches, key=lambda m: m["jaccard"], reverse=True),
        "max_jaccard": round(max_jaccard, 4),
        "elapsed_s": elapsed,
    }


def fingerprint_chunks(
    doc_chunks: list[str],
    ref_text: str,
    *,
    k: int = 20,
    window_size: int = 3,
    threshold: float = 0.08,
) -> list[dict]:
    """Check which document chunks have exact-match overlap with a reference.

    Uses smaller k (20) for chunk-level matching since chunks are shorter.

    Returns:
        List of dicts with ``chunk_index``, ``jaccard``, ``overlap_count``
        for chunks exceeding the threshold.
    """
    ref_fp = generate_fingerprints(ref_text, k=k, window_size=window_size)
    ref_set = ref_fp["fingerprints"]

    if not ref_set:
        return []

    flagged: list[dict] = []
    for i, chunk in enumerate(doc_chunks):
        chunk_fp = generate_fingerprints(chunk, k=k, window_size=window_size)
        chunk_set = chunk_fp["fingerprints"]
        if not chunk_set:
            continue

        overlap = chunk_set & ref_set
        if not overlap:
            continue

        jaccard = len(overlap) / len(chunk_set | ref_set)
        if jaccard >= threshold:
            flagged.append({
                "chunk_index": i,
                "jaccard": round(jaccard, 4),
                "overlap_count": len(overlap),
            })

    return flagged
