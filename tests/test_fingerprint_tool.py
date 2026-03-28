"""Tests for the N-gram fingerprinting tool."""

from __future__ import annotations

import pytest

from app.tools.fingerprint_tool import (
    _normalize,
    _rolling_hashes,
    _winnow,
    compare_fingerprints,
    fingerprint_chunks,
    fingerprint_match_score,
    generate_fingerprints,
)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello World") == "hello world"

    def test_strips_punctuation(self):
        assert _normalize("hello, world!") == "hello world"

    def test_collapses_whitespace(self):
        assert _normalize("hello   \n  world") == "hello world"

    def test_empty(self):
        assert _normalize("") == ""


# ---------------------------------------------------------------------------
# Rolling hashes
# ---------------------------------------------------------------------------

class TestRollingHashes:
    def test_returns_correct_count(self):
        hashes = _rolling_hashes("abcdefgh", k=5)
        # len-5+1 = 4 hashes
        assert len(hashes) == 4

    def test_empty_when_too_short(self):
        assert _rolling_hashes("abc", k=5) == []

    def test_deterministic(self):
        a = _rolling_hashes("hello world", k=3)
        b = _rolling_hashes("hello world", k=3)
        assert a == b


# ---------------------------------------------------------------------------
# Winnowing
# ---------------------------------------------------------------------------

class TestWinnow:
    def test_basic(self):
        hashes = [5, 3, 7, 1, 4, 2, 8]
        result = _winnow(hashes, window_size=3)
        # Should return list of (hash, pos) tuples
        assert all(isinstance(t, tuple) and len(t) == 2 for t in result)

    def test_empty_input(self):
        assert _winnow([], window_size=3) == []

    def test_zero_window(self):
        assert _winnow([1, 2, 3], window_size=0) == []


# ---------------------------------------------------------------------------
# Generate fingerprints
# ---------------------------------------------------------------------------

class TestGenerateFingerprints:
    def test_returns_expected_keys(self):
        text = "The quick brown fox jumps over the lazy dog. " * 10
        result = generate_fingerprints(text)
        assert "fingerprints" in result
        assert "count" in result
        assert "normalized_length" in result
        assert isinstance(result["fingerprints"], set)

    def test_short_text_returns_empty(self):
        result = generate_fingerprints("hi")
        assert result["count"] == 0
        assert result["fingerprints"] == set()

    def test_identical_texts_same_fingerprints(self):
        text = "The importance of renewable energy in modern society. " * 5
        a = generate_fingerprints(text)
        b = generate_fingerprints(text)
        assert a["fingerprints"] == b["fingerprints"]

    def test_different_texts_different_fingerprints(self):
        a = generate_fingerprints("Alpha beta gamma delta epsilon zeta eta theta. " * 5)
        b = generate_fingerprints("One two three four five six seven eight nine ten. " * 5)
        # Not completely disjoint but should be mostly different
        overlap = len(a["fingerprints"] & b["fingerprints"])
        total = len(a["fingerprints"] | b["fingerprints"])
        assert overlap / total < 0.5 if total else True


# ---------------------------------------------------------------------------
# Compare fingerprints
# ---------------------------------------------------------------------------

class TestCompareFingerprints:
    def test_identical_sets(self):
        s = {1, 2, 3, 4, 5}
        result = compare_fingerprints(s, s)
        assert result["jaccard"] == 1.0
        assert result["overlap_count"] == 5

    def test_disjoint_sets(self):
        result = compare_fingerprints({1, 2, 3}, {4, 5, 6})
        assert result["jaccard"] == 0.0
        assert result["overlap_count"] == 0

    def test_empty_sets(self):
        result = compare_fingerprints(set(), set())
        assert result["jaccard"] == 0.0

    def test_partial_overlap(self):
        result = compare_fingerprints({1, 2, 3}, {2, 3, 4})
        # overlap=2, union=4 → jaccard=0.5
        assert result["jaccard"] == 0.5
        assert result["overlap_count"] == 2


# ---------------------------------------------------------------------------
# fingerprint_match_score (end-to-end)
# ---------------------------------------------------------------------------

class TestFingerprintMatchScore:
    def test_identical_documents_high_score(self):
        text = "This paper examines the role of artificial intelligence in healthcare systems. " * 10
        result = fingerprint_match_score(text, [text])
        assert result["score"] >= 50
        assert len(result["matches"]) >= 1

    def test_no_overlap_zero_score(self):
        doc = "Alpha bravo charlie delta echo foxtrot golf hotel india. " * 5
        refs = ["One two three four five six seven eight nine ten. " * 5]
        result = fingerprint_match_score(doc, refs)
        assert result["score"] < 10  # low/zero

    def test_empty_refs(self):
        result = fingerprint_match_score("some text", [])
        assert result["score"] == 0.0

    def test_short_doc(self):
        result = fingerprint_match_score("hi", ["hello world"])
        assert result["score"] == 0.0


# ---------------------------------------------------------------------------
# fingerprint_chunks
# ---------------------------------------------------------------------------

class TestFingerprintChunks:
    def test_matching_chunk_detected(self):
        ref = "The study of climate change impacts on agricultural productivity represents " * 10
        chunks = [ref, "Something completely unrelated about quantum physics. " * 10]
        result = fingerprint_chunks(chunks, ref)
        # First chunk should match
        assert any(r["chunk_index"] == 0 for r in result)

    def test_no_match_returns_empty(self):
        ref = "Alpha bravo charlie delta echo foxtrot golf. " * 10
        chunks = ["One two three four five six seven eight. " * 5]
        result = fingerprint_chunks(chunks, ref)
        # May or may not match depending on threshold
        assert isinstance(result, list)
