"""Semantic relevance scoring — ranks search results by semantic closeness to the query.

Given a query text and a set of search results (with snippets/abstracts),
computes semantic similarity scores to rank results by relevance. This
filters out low-relevance noise before expensive embedding comparison.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.tools.embedding_tool import generate_embeddings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def score_relevance(
    query_text: str,
    results: list[dict[str, Any]],
    text_key: str = "abstract",
    fallback_key: str = "title",
    min_score: float = 0.15,
) -> list[dict[str, Any]]:
    """Score and rank search results by semantic relevance to query_text.

    Each result dict gets a ``relevance_score`` field added.
    Results are sorted by relevance descending and optionally filtered
    by ``min_score``.

    Args:
        query_text: The query or document chunk to compare against.
        results: List of result dicts (papers, web results, etc.).
        text_key: Primary key in each result to use for comparison text.
        fallback_key: Fallback key if text_key is empty.
        min_score: Minimum relevance score to keep (0 = keep all).

    Returns:
        Sorted list of results with ``relevance_score`` added.
    """
    if not results or not query_text.strip():
        return results

    # Extract comparison texts
    texts: list[str] = []
    valid_indices: list[int] = []
    for i, r in enumerate(results):
        text = r.get(text_key, "") or r.get(fallback_key, "") or ""
        text = str(text).strip()
        if text:
            texts.append(text)
            valid_indices.append(i)

    if not texts:
        # No texts to compare — return everything with score 0
        for r in results:
            r["relevance_score"] = 0.0
        return results

    # Embed query + all result texts together
    all_texts = [query_text] + texts
    try:
        all_embeddings = await generate_embeddings(all_texts)
    except Exception as exc:
        logger.warning("relevance_scoring_embedding_failed", error=str(exc))
        for r in results:
            r["relevance_score"] = 0.0
        return results

    query_emb = np.array(all_embeddings[0])
    result_embs = np.array(all_embeddings[1:])

    # Compute cosine similarity between query and each result
    query_norm = np.linalg.norm(query_emb)
    if query_norm == 0:
        for r in results:
            r["relevance_score"] = 0.0
        return results

    similarities = np.dot(result_embs, query_emb) / (
        np.linalg.norm(result_embs, axis=1) * query_norm + 1e-10
    )

    # Assign scores back
    for r in results:
        r["relevance_score"] = 0.0

    for idx, sim in zip(valid_indices, similarities):
        results[idx]["relevance_score"] = round(float(sim), 4)

    # Sort by relevance descending
    results.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)

    # Filter by min_score
    if min_score > 0:
        results = [r for r in results if r.get("relevance_score", 0) >= min_score]

    logger.info(
        "relevance_scoring_complete",
        total_results=len(results),
        min_score=min_score,
        top_score=results[0]["relevance_score"] if results else 0,
    )

    return results
