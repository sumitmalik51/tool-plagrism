"""Similarity tool — computes cosine similarity between embedding vectors.

Standalone, framework-agnostic tool. Accepts clear inputs, returns structured JSON.
"""

from __future__ import annotations

import time

import numpy as np
from numpy.typing import NDArray

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def cosine_similarity_matrix(
    embeddings_a: NDArray[np.float32],
    embeddings_b: NDArray[np.float32],
) -> NDArray[np.float32]:
    """Compute pairwise cosine similarity between two sets of L2-normalized embeddings.

    Args:
        embeddings_a: Shape ``(m, d)``.
        embeddings_b: Shape ``(n, d)``.

    Returns:
        Similarity matrix of shape ``(m, n)`` with values in ``[-1, 1]``.
    """
    sim: NDArray[np.float32] = np.dot(embeddings_a, embeddings_b.T)
    return sim


def find_high_similarity_pairs(
    sim_matrix: NDArray[np.float32],
    threshold: float = 0.80,
) -> list[dict]:
    """Extract chunk-index pairs whose similarity exceeds ``threshold``.

    Returns:
        List of dicts with ``chunk_a_idx``, ``chunk_b_idx``, ``similarity``.
    """
    indices = np.argwhere(sim_matrix >= threshold)
    pairs: list[dict] = []
    for i, j in indices:
        pairs.append({
            "chunk_a_idx": int(i),
            "chunk_b_idx": int(j),
            "similarity": float(sim_matrix[i, j]),
        })
    pairs.sort(key=lambda p: p["similarity"], reverse=True)
    logger.info("similarity_pairs_found", count=len(pairs), threshold=threshold)
    return pairs


def compute_overall_score(
    sim_matrix: NDArray[np.float32],
    threshold: float = 0.80,
) -> dict:
    """Derive an overall plagiarism score from the similarity matrix.

    The score is the percentage of document chunks that have at least one
    reference chunk above ``threshold``.

    Returns:
        Dict with ``score`` (0-100), ``flagged_ratio``, ``max_similarity``,
        ``mean_similarity``.
    """
    if sim_matrix.size == 0:
        return {
            "score": 0.0,
            "flagged_ratio": 0.0,
            "max_similarity": 0.0,
            "mean_similarity": 0.0,
        }

    max_per_doc_chunk = sim_matrix.max(axis=1)
    flagged = (max_per_doc_chunk >= threshold).sum()
    total = len(max_per_doc_chunk)

    score = float(flagged / total * 100) if total else 0.0
    return {
        "score": round(score, 2),
        "flagged_ratio": round(float(flagged / total), 4) if total else 0.0,
        "max_similarity": round(float(max_per_doc_chunk.max()), 4),
        "mean_similarity": round(float(max_per_doc_chunk.mean()), 4),
    }


def run_similarity_analysis(
    texts_a: list[str],
    texts_b: list[str],
    embeddings_a: list[list[float]],
    embeddings_b: list[list[float]],
    threshold: float | None = None,
) -> dict:
    """Full similarity analysis — structured JSON output.

    Accepts pre-computed embeddings as plain lists (JSON-friendly).

    Returns:
        Dict with ``score``, ``flagged_ratio``, ``max_similarity``,
        ``mean_similarity``, ``high_similarity_pairs``.
    """
    if threshold is None:
        threshold = settings.semantic_similarity_threshold

    start = time.perf_counter()

    arr_a = np.array(embeddings_a, dtype=np.float32)
    arr_b = np.array(embeddings_b, dtype=np.float32)

    sim_matrix = cosine_similarity_matrix(arr_a, arr_b)
    pairs = find_high_similarity_pairs(sim_matrix, threshold=threshold)
    score_info = compute_overall_score(sim_matrix, threshold=threshold)

    elapsed = round(time.perf_counter() - start, 3)

    result = {
        **score_info,
        "threshold": threshold,
        "high_similarity_pairs": pairs[:50],  # cap at 50
        "elapsed_s": elapsed,
    }

    logger.info(
        "similarity_analysis_complete",
        score=result["score"],
        pairs_found=len(pairs),
        elapsed_s=elapsed,
    )
    return result
