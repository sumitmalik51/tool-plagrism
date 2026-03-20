"""Tests for the semantic agent — uses mocked embeddings to stay fast."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.agents.semantic_agent import SemanticAgent
from app.models.schemas import AgentInput


def _make_embeddings(n: int, dim: int = 384) -> np.ndarray:
    """Create n random L2-normalised embedding vectors.

    Uses dim=384 (matching all-MiniLM-L6-v2 output) so random vectors
    are sufficiently orthogonal to stay below the 0.80 threshold.
    """
    rng = np.random.default_rng(42)
    vecs = rng.random((n, dim), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / norms


def _make_duplicate_embeddings(n: int, dup_pairs: int = 2, dim: int = 384) -> np.ndarray:
    """Create embeddings where the first ``dup_pairs`` chunks share near-identical vectors."""
    embs = _make_embeddings(n, dim)
    for i in range(dup_pairs):
        # Clone chunk i into chunk n-1-i with tiny noise so sim ≈ 0.99
        embs[n - 1 - i] = embs[i] + np.random.default_rng(i).normal(0, 0.01, dim).astype(np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    return embs / norms


@pytest.mark.asyncio
@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_semantic_agent_no_plagiarism(mock_embed: AsyncMock) -> None:
    """Distinct chunks should produce a low score."""
    chunks = [f"Unique chunk number {i}." for i in range(6)]
    mock_embed.return_value = _make_embeddings(len(chunks))

    agent = SemanticAgent()
    result = await agent.run(
        AgentInput(document_id="doc-1", text=" ".join(chunks), chunks=chunks)
    )

    assert result.agent_name == "semantic_agent"
    assert result.score < 30.0
    assert result.confidence > 0.0


@pytest.mark.asyncio
@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_semantic_agent_with_duplicates(mock_embed: AsyncMock) -> None:
    """Near-duplicate chunks should trigger flags."""
    chunks = [f"Chunk {i} text here." for i in range(8)]
    mock_embed.return_value = _make_duplicate_embeddings(len(chunks), dup_pairs=3)

    agent = SemanticAgent()
    result = await agent.run(
        AgentInput(document_id="doc-2", text=" ".join(chunks), chunks=chunks)
    )

    assert result.score > 0.0
    assert len(result.flagged_passages) > 0
    assert all(fp.similarity_score >= 0.8 for fp in result.flagged_passages)


@pytest.mark.asyncio
async def test_semantic_agent_short_text() -> None:
    """A very short document (< 2 chunks) should return quickly with score 0."""
    agent = SemanticAgent()
    result = await agent.run(
        AgentInput(document_id="doc-3", text="Short text.")
    )
    assert result.score == 0.0
    assert result.details.get("reason") == "document_too_short"
