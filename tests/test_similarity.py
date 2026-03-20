"""Tests for the similarity service."""

from __future__ import annotations

import numpy as np

from app.services.similarity import (
    compute_overall_score,
    cosine_similarity_matrix,
    find_high_similarity_pairs,
)


def _normalized(vectors: list[list[float]]) -> np.ndarray:
    """Helper: L2-normalize a list of vectors."""
    arr = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / norms


def test_cosine_similarity_identical_vectors() -> None:
    vecs = _normalized([[1, 0, 0], [0, 1, 0]])
    sim = cosine_similarity_matrix(vecs, vecs)
    # Diagonal should be ~1.0
    assert abs(sim[0, 0] - 1.0) < 1e-5
    assert abs(sim[1, 1] - 1.0) < 1e-5
    # Off-diagonal should be ~0.0 (orthogonal)
    assert abs(sim[0, 1]) < 1e-5


def test_cosine_similarity_similar_vectors() -> None:
    vecs_a = _normalized([[1, 1, 0]])
    vecs_b = _normalized([[1, 1, 0.1]])
    sim = cosine_similarity_matrix(vecs_a, vecs_b)
    assert sim[0, 0] > 0.95  # very similar


def test_find_high_similarity_pairs() -> None:
    sim = np.array([[0.5, 0.9], [0.9, 0.5]], dtype=np.float32)
    pairs = find_high_similarity_pairs(sim, threshold=0.8)
    assert len(pairs) == 2  # (0,1) and (1,0)
    assert all(p["similarity"] >= 0.8 for p in pairs)


def test_find_high_similarity_pairs_none_above_threshold() -> None:
    sim = np.array([[0.1, 0.2], [0.3, 0.1]], dtype=np.float32)
    pairs = find_high_similarity_pairs(sim, threshold=0.8)
    assert len(pairs) == 0


def test_compute_overall_score_all_flagged() -> None:
    # 3 doc chunks, all have a match >= 0.85
    sim = np.array(
        [[0.0, 0.9, 0.85], [0.9, 0.0, 0.88], [0.85, 0.88, 0.0]],
        dtype=np.float32,
    )
    result = compute_overall_score(sim, threshold=0.8)
    assert result["score"] == 100.0
    assert result["flagged_ratio"] == 1.0


def test_compute_overall_score_empty() -> None:
    sim = np.empty((0, 0), dtype=np.float32)
    result = compute_overall_score(sim, threshold=0.8)
    assert result["score"] == 0.0
