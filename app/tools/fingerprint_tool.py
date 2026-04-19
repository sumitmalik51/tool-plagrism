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

# Citation markers:  [1], [12,13], (Author, 2020), (Author et al., 2020)
_CITATION_MARKER_RE = re.compile(
    r"\[\d{1,3}(?:[,;\s]*\d{1,3})*\]"           # [1], [1,2,3]
    r"|"
    r"\([A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s*\d{4}\)",  # (Author, 2020)
    re.UNICODE,
)
# Equations / math fragments:  anything with ≥2 math-heavy symbols
_EQUATION_RE = re.compile(r"(?:[=+\-*/^∫∑∏∂∇≈≤≥∝λμσ]{2,}|\\[a-z]{3,})", re.UNICODE)

# Common academic filler phrases that inflate phrase-overlap counts
_COMMON_ACADEMIC_PHRASES: set[tuple[str, ...]] = {
    tuple(p.split()) for p in [
        "in this paper we",
        "in this study we",
        "the results show that",
        "the results indicate that",
        "it has been shown that",
        "it is well known that",
        "on the other hand",
        "in order to",
        "as well as",
        "with respect to",
        "in the case of",
        "it should be noted that",
        "as shown in figure",
        "as shown in table",
        "et al",
        "for example",
        "such as",
        "due to the",
        "according to the",
        "based on the",
        "in terms of",
        "as a result",
        "in addition to",
        "it can be seen that",
        "we propose a",
        "we present a",
        "in the literature",
        "has been widely used",
        "state of the art",
        "to the best of our knowledge",
    ]
}


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation/citations/equations, collapse whitespace."""
    text = text.lower()
    text = _CITATION_MARKER_RE.sub(" ", text)
    text = _EQUATION_RE.sub(" ", text)
    text = _PUNCT_RE.sub("", text)
    text = _MULTI_WS.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Hashing & winnowing
# ---------------------------------------------------------------------------

def _rolling_hashes(text: str, k: int) -> list[int]:
    """Generate k-gram hashes using a fast polynomial rolling hash.

    Uses Rabin-style rolling hash instead of per-gram MD5 — orders of
    magnitude faster for long texts.
    """
    n = len(text)
    if n < k:
        return []

    _BASE = 31
    _MOD = (1 << 61) - 1  # Mersenne prime for fast modular arithmetic

    # Precompute base^k mod _MOD for sliding the window
    base_k = pow(_BASE, k, _MOD)

    # Compute initial hash for text[0:k]
    h = 0
    for ch in text[:k]:
        h = (h * _BASE + ord(ch)) % _MOD

    hashes = [h]
    for i in range(1, n - k + 1):
        # Slide: remove text[i-1], add text[i+k-1]
        h = (h * _BASE - ord(text[i - 1]) * base_k + ord(text[i + k - 1])) % _MOD
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
    threshold: float = 0.10,
) -> dict[str, Any]:
    """Compare a document against multiple reference texts using fingerprinting.

    A Jaccard of 0.10+ between a document and a single web page is significant
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

    # Score: linear up to Jaccard 0.30, then saturated at 100.
    # A Jaccard of 0.30 represents heavy verbatim copying; below 0.10
    # we suppress the score entirely (likely shared boilerplate noise).
    if max_jaccard < 0.10:
        score = 0.0
    else:
        score = min(max_jaccard * (100.0 / 0.30), 100.0)
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


# ---------------------------------------------------------------------------
# Phrase overlap — counts exact word-sequence matches (5–8 words)
# ---------------------------------------------------------------------------

_WORD_SPLIT = re.compile(r"\s+")


def phrase_overlap_count(
    passage: str,
    source_text: str,
    *,
    min_words: int = 5,
    max_words: int = 8,
) -> int:
    """Count how many distinct word n-grams (5-8 words) from *passage* appear
    verbatim in *source_text*.

    Both texts are lowercased and stripped of punctuation before comparison.
    Returns the total number of matching phrases across all n-gram sizes.
    """
    p_norm = _PUNCT_RE.sub("", passage.lower())
    s_norm = _PUNCT_RE.sub("", source_text.lower())

    p_words = _WORD_SPLIT.split(p_norm.strip())
    s_words = _WORD_SPLIT.split(s_norm.strip())

    if len(p_words) < min_words or len(s_words) < min_words:
        return 0

    # Build set of all source n-grams for each size
    total_matches = 0
    for n in range(min_words, max_words + 1):
        if len(s_words) < n or len(p_words) < n:
            continue
        source_ngrams: set[tuple[str, ...]] = set()
        for i in range(len(s_words) - n + 1):
            source_ngrams.add(tuple(s_words[i : i + n]))
        # Count passage n-grams that appear in source
        for i in range(len(p_words) - n + 1):
            if tuple(p_words[i : i + n]) in source_ngrams:
                total_matches += 1

    return total_matches


def _is_common_phrase(ngram: tuple[str, ...]) -> bool:
    """Return True if the n-gram is a common academic phrase."""
    for common in _COMMON_ACADEMIC_PHRASES:
        clen = len(common)
        nlen = len(ngram)
        if nlen >= clen:
            # Check if common phrase is a contiguous sub-sequence
            for start in range(nlen - clen + 1):
                if ngram[start : start + clen] == common:
                    return True
        elif clen >= nlen:
            for start in range(clen - nlen + 1):
                if common[start : start + nlen] == ngram:
                    return True
    return False


def idf_filtered_phrase_overlap(
    passage: str,
    source_text: str,
    *,
    min_words: int = 5,
    max_words: int = 8,
) -> int:
    """Like phrase_overlap_count but filters out common academic phrases.

    Returns count of *non-trivial* matching n-grams — phrases that are
    content-specific rather than boilerplate.
    """
    p_norm = _PUNCT_RE.sub("", passage.lower())
    s_norm = _PUNCT_RE.sub("", source_text.lower())

    p_words = _WORD_SPLIT.split(p_norm.strip())
    s_words = _WORD_SPLIT.split(s_norm.strip())

    if len(p_words) < min_words or len(s_words) < min_words:
        return 0

    total_matches = 0
    for n in range(min_words, max_words + 1):
        if len(s_words) < n or len(p_words) < n:
            continue
        source_ngrams: set[tuple[str, ...]] = set()
        for i in range(len(s_words) - n + 1):
            ng = tuple(s_words[i : i + n])
            if not _is_common_phrase(ng):
                source_ngrams.add(ng)
        for i in range(len(p_words) - n + 1):
            ng = tuple(p_words[i : i + n])
            if ng in source_ngrams and not _is_common_phrase(ng):
                total_matches += 1

    return total_matches


# ---------------------------------------------------------------------------
# Per-request IDF — real document-frequency over candidate corpus
# ---------------------------------------------------------------------------

import math


def build_idf_table(
    corpus_texts: list[str],
    *,
    min_words: int = 5,
    max_words: int = 8,
) -> dict[tuple[str, ...], float]:
    """Build a per-request IDF table over a candidate corpus.

    For each n-gram of size *min_words*..*max_words*, computes
    ``log(N / df)`` where N is the number of documents and *df* is the
    document-frequency of that n-gram. Higher IDF = rarer = more
    discriminative for source attribution.

    The caller passes the small corpus of retrieved candidate documents
    (web pages, abstracts) — typically 10-30 docs — so this is cheap.
    """
    if not corpus_texts:
        return {}
    N = len(corpus_texts)
    df: dict[tuple[str, ...], int] = {}
    for text in corpus_texts:
        norm = _PUNCT_RE.sub("", text.lower())
        words = _WORD_SPLIT.split(norm.strip())
        seen: set[tuple[str, ...]] = set()
        for n in range(min_words, max_words + 1):
            if len(words) < n:
                continue
            for i in range(len(words) - n + 1):
                seen.add(tuple(words[i : i + n]))
        for ng in seen:
            df[ng] = df.get(ng, 0) + 1

    # log(N/df), but never below 0 (rare-positive only)
    return {ng: math.log(N / d) for ng, d in df.items()}


def idf_weighted_phrase_hits(
    passage: str,
    source_text: str,
    idf_table: dict[tuple[str, ...], float],
    *,
    min_words: int = 5,
    max_words: int = 8,
    min_idf: float = 0.7,  # ~drop n-grams in >=50% of candidate docs
    max_doc_freq_ratio: float = 0.30,  # also drop n-grams in >=30% of docs
) -> int:
    """Count n-gram matches between passage and source, weighted by real IDF.

    An n-gram counts as a hit only if:
      1. It appears verbatim in both passage and source.
      2. Its IDF is above *min_idf* (i.e. it is not boilerplate in the
         current request's candidate corpus).
      3. It is not in the static common-academic-phrases blocklist.

    *idf_table* is built once per request via :func:`build_idf_table`.
    If empty, falls back to the static-blocklist behaviour of
    :func:`idf_filtered_phrase_overlap`.
    """
    if not idf_table:
        return idf_filtered_phrase_overlap(
            passage, source_text,
            min_words=min_words, max_words=max_words,
        )

    # Compute corpus-frequency cutoff implied by max_doc_freq_ratio.
    # df_threshold corresponds to N * max_doc_freq_ratio; convert to IDF.
    # If we know N (from any value: log(N/df)=idf), the cap becomes:
    #   idf >= log(1/max_doc_freq_ratio)
    cap_idf = math.log(1.0 / max_doc_freq_ratio)
    effective_min_idf = max(min_idf, cap_idf)

    p_norm = _PUNCT_RE.sub("", passage.lower())
    s_norm = _PUNCT_RE.sub("", source_text.lower())
    p_words = _WORD_SPLIT.split(p_norm.strip())
    s_words = _WORD_SPLIT.split(s_norm.strip())

    if len(p_words) < min_words or len(s_words) < min_words:
        return 0

    total_hits = 0
    for n in range(min_words, max_words + 1):
        if len(s_words) < n or len(p_words) < n:
            continue
        # Build source ngram set
        src_ngrams: set[tuple[str, ...]] = set()
        for i in range(len(s_words) - n + 1):
            src_ngrams.add(tuple(s_words[i : i + n]))
        # Walk passage
        for i in range(len(p_words) - n + 1):
            ng = tuple(p_words[i : i + n])
            if ng not in src_ngrams:
                continue
            if _is_common_phrase(ng):
                continue
            idf = idf_table.get(ng, 0.0)
            if idf < effective_min_idf:
                # Too common in candidate corpus → topic noise
                continue
            total_hits += 1
    return total_hits


def longest_common_token_substring(text_a: str, text_b: str) -> int:
    """Return the length (in tokens) of the longest contiguous word-sequence
    shared between *text_a* and *text_b*.

    Uses a simple DP approach bounded by passage length (not full documents).
    Both texts are normalised before comparison.
    """
    a_words = _WORD_SPLIT.split(_normalize(text_a))
    b_words = _WORD_SPLIT.split(_normalize(text_b))

    if not a_words or not b_words:
        return 0

    # Limit to first 300 tokens to keep O(n*m) manageable
    a_words = a_words[:300]
    b_words = b_words[:300]

    max_len = 0
    # Use rolling array for space efficiency
    prev = [0] * (len(b_words) + 1)
    for i in range(1, len(a_words) + 1):
        curr = [0] * (len(b_words) + 1)
        for j in range(1, len(b_words) + 1):
            if a_words[i - 1] == b_words[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > max_len:
                    max_len = curr[j]
        prev = curr

    return max_len


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
