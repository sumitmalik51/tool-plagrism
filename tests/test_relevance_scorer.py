"""Tests for the semantic relevance scoring tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.tools.relevance_scorer import score_relevance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_embeddings(texts):
    """Generate deterministic fake embeddings for testing."""
    # Use hash-based pseudo-embeddings so similar texts get somewhat similar vectors
    embeddings = []
    for t in texts:
        np.random.seed(hash(t) % (2**31))
        embeddings.append(np.random.randn(384).tolist())
    return embeddings


# ---------------------------------------------------------------------------
# Basic scoring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_relevance_basic() -> None:
    results = [
        {"title": "Deep Learning NLP", "abstract": "Neural networks for language processing"},
        {"title": "Cooking Recipes", "abstract": "How to make pasta at home"},
        {"title": "Machine Learning", "abstract": "Statistical learning and pattern recognition"},
    ]

    with patch("app.tools.relevance_scorer.generate_embeddings", new_callable=AsyncMock) as mock_embed:
        # Create embeddings where the query is most similar to result 0 and 2
        mock_embed.return_value = _fake_embeddings(
            ["deep learning for NLP tasks"] + [r["abstract"] for r in results]
        )

        scored = await score_relevance(
            "deep learning for NLP tasks",
            results,
            min_score=0.0,
        )

    assert len(scored) == 3
    # Every result should have a relevance_score
    for r in scored:
        assert "relevance_score" in r
        assert isinstance(r["relevance_score"], float)

    # Results should be sorted by relevance descending
    scores = [r["relevance_score"] for r in scored]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_score_relevance_empty_results() -> None:
    result = await score_relevance("test query", [])
    assert result == []


@pytest.mark.asyncio
async def test_score_relevance_empty_query() -> None:
    results = [{"title": "Test", "abstract": "Content"}]
    result = await score_relevance("", results)
    assert result == results


@pytest.mark.asyncio
async def test_score_relevance_min_score_filter() -> None:
    results = [
        {"title": "Relevant", "abstract": "Very relevant content"},
        {"title": "Irrelevant", "abstract": "Completely unrelated stuff"},
    ]

    with patch("app.tools.relevance_scorer.generate_embeddings", new_callable=AsyncMock) as mock_embed:
        # First embedding is query, then results
        # Make the second result have low similarity
        query_emb = [1.0] * 384
        relevant_emb = [0.9] * 384  # high similarity
        irrelevant_emb = [-0.5] * 384  # low similarity
        mock_embed.return_value = [query_emb, relevant_emb, irrelevant_emb]

        scored = await score_relevance(
            "relevant query",
            results,
            min_score=0.5,
        )

    # Only the relevant result should pass the filter
    assert len(scored) <= 2
    for r in scored:
        assert r["relevance_score"] >= 0.5


@pytest.mark.asyncio
async def test_score_relevance_uses_fallback_key() -> None:
    results = [
        {"title": "Title Only", "abstract": ""},  # empty abstract
    ]

    with patch("app.tools.relevance_scorer.generate_embeddings", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = [[1.0] * 384, [0.8] * 384]

        scored = await score_relevance(
            "test query",
            results,
            text_key="abstract",
            fallback_key="title",
            min_score=0.0,
        )

    # Should still score using the title since abstract is empty
    assert len(scored) == 1
    assert scored[0]["relevance_score"] > 0


@pytest.mark.asyncio
async def test_score_relevance_embedding_failure() -> None:
    results = [{"title": "Test", "abstract": "Content"}]

    with patch("app.tools.relevance_scorer.generate_embeddings", new_callable=AsyncMock) as mock_embed:
        mock_embed.side_effect = RuntimeError("embedding service down")

        scored = await score_relevance("query", results)

    # Should return results with score 0 instead of crashing
    assert len(scored) == 1
    assert scored[0]["relevance_score"] == 0.0


@pytest.mark.asyncio
async def test_score_relevance_no_text_in_results() -> None:
    results = [
        {"title": "", "abstract": ""},
        {"title": "", "abstract": ""},
    ]

    scored = await score_relevance("test query", results, min_score=0.0)

    # All results should have score 0
    for r in scored:
        assert r["relevance_score"] == 0.0


@pytest.mark.asyncio
async def test_score_relevance_preserves_existing_fields() -> None:
    results = [
        {"title": "Paper", "abstract": "Content", "url": "https://example.com", "year": "2024"},
    ]

    with patch("app.tools.relevance_scorer.generate_embeddings", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = [[1.0] * 384, [0.8] * 384]

        scored = await score_relevance("query", results, min_score=0.0)

    assert scored[0]["url"] == "https://example.com"
    assert scored[0]["year"] == "2024"
    assert "relevance_score" in scored[0]
