"""Tests for the tools layer — embedding, similarity, content extractor, AI detect."""

from __future__ import annotations

import numpy as np
import pytest

from app.tools.ai_detection_tool import detect_ai_text
from app.tools.content_extractor_tool import chunk_text, extract_text
from app.tools.similarity_tool import (
    compute_overall_score,
    cosine_similarity_matrix,
    find_high_similarity_pairs,
    run_similarity_analysis,
)


# ---------------------------------------------------------------------------
# content_extractor_tool — chunk_text
# ---------------------------------------------------------------------------

def test_chunk_text_empty() -> None:
    result = chunk_text("")
    assert result["chunks"] == []
    assert result["chunk_count"] == 0


def test_chunk_text_short() -> None:
    result = chunk_text("Hello world.", chunk_size=500)
    assert result["chunk_count"] == 1
    assert result["chunks"][0] == "Hello world."


def test_chunk_text_long() -> None:
    text = "Hello world. " * 200
    result = chunk_text(text, chunk_size=500, overlap=100)
    assert result["chunk_count"] > 1
    assert all(len(c) > 0 for c in result["chunks"])


def test_chunk_text_returns_dict() -> None:
    result = chunk_text("Some text here.", chunk_size=500)
    assert "chunks" in result
    assert "chunk_count" in result
    assert "chunk_size" in result
    assert "overlap" in result


def test_chunk_text_no_mid_word_start() -> None:
    """Chunks should never start in the middle of a word."""
    # Build text where a naive overlap split would land mid-word
    text = "Article Stability of Non-Flexible Devices. " * 50
    result = chunk_text(text, chunk_size=100, overlap=30)
    for i, chunk in enumerate(result["chunks"]):
        # Find where this chunk starts in the original text
        idx = text.find(chunk[:20])
        if idx > 0:
            # The character before the chunk start must be whitespace
            # or punctuation — never a letter (mid-word).
            prev = text[idx - 1]
            assert prev.isspace() or prev in '.;:!?,', (
                f"Chunk {i} starts mid-word at position {idx}: "
                f"...{text[max(0, idx-5):idx+15]!r}..."
            )


# ---------------------------------------------------------------------------
# content_extractor_tool — extract_text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_text_txt() -> None:
    result = await extract_text(b"Test content here.", "test.txt")
    assert result["text"] == "Test content here."
    assert result["file_type"] == "txt"
    assert result["char_count"] == 18


@pytest.mark.asyncio
async def test_extract_text_unsupported() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        await extract_text(b"data", "file.xyz")


@pytest.mark.asyncio
async def test_extract_text_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        await extract_text(b"   ", "empty.txt")


# ---------------------------------------------------------------------------
# similarity_tool
# ---------------------------------------------------------------------------

def _normalized(vectors: list[list[float]]) -> np.ndarray:
    arr = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / norms


def test_similarity_matrix_identity() -> None:
    vecs = _normalized([[1, 0, 0], [0, 1, 0]])
    sim = cosine_similarity_matrix(vecs, vecs)
    assert abs(sim[0, 0] - 1.0) < 1e-5
    assert abs(sim[0, 1]) < 1e-5


def test_find_pairs_above_threshold() -> None:
    sim = np.array([[0.5, 0.9], [0.9, 0.5]], dtype=np.float32)
    pairs = find_high_similarity_pairs(sim, threshold=0.8)
    assert len(pairs) == 2


def test_find_pairs_none_above() -> None:
    sim = np.array([[0.1, 0.2], [0.3, 0.1]], dtype=np.float32)
    pairs = find_high_similarity_pairs(sim, threshold=0.8)
    assert len(pairs) == 0


def test_overall_score_all_flagged() -> None:
    sim = np.array([[0.9, 0.85], [0.85, 0.9]], dtype=np.float32)
    result = compute_overall_score(sim, threshold=0.8)
    assert result["score"] == 100.0


def test_overall_score_empty() -> None:
    result = compute_overall_score(np.empty((0, 0), dtype=np.float32))
    assert result["score"] == 0.0


def test_run_similarity_analysis() -> None:
    vecs = _normalized([[1, 0, 0], [0.9, 0.1, 0]])
    result = run_similarity_analysis(
        texts_a=["a", "b"],
        texts_b=["c", "d"],
        embeddings_a=vecs.tolist(),
        embeddings_b=vecs.tolist(),
        threshold=0.8,
    )
    assert "score" in result
    assert "high_similarity_pairs" in result
    assert "elapsed_s" in result


# ---------------------------------------------------------------------------
# ai_detection_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_detect_empty() -> None:
    result = await detect_ai_text("")
    assert result["score"] == 0.0
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_ai_detect_returns_structured() -> None:
    text = "The quick brown fox jumps over the lazy dog. " * 10
    result = await detect_ai_text(text)
    assert "score" in result
    assert "confidence" in result
    assert "indicators" in result
    assert 0 <= result["score"] <= 100


@pytest.mark.asyncio
async def test_ai_detect_with_chunks() -> None:
    text = "This is a uniform sentence. " * 50
    chunks = [text[i:i+200] for i in range(0, len(text), 200)]
    result = await detect_ai_text(text, chunks=chunks)
    assert isinstance(result["flagged_chunks"], list)
