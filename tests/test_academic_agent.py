"""Tests for the academic agent — uses mocked Scholar & embeddings."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.agents.academic_agent import AcademicAgent, _extract_queries
from app.models.schemas import AgentInput


def _make_embeddings(n: int, dim: int = 384) -> np.ndarray:
    rng = np.random.default_rng(42)
    vecs = rng.random((n, dim), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / norms


# ---------------------------------------------------------------------------
# _extract_queries
# ---------------------------------------------------------------------------

def test_extract_queries_empty() -> None:
    assert _extract_queries([]) == []


def test_extract_queries_extracts_sentences() -> None:
    chunks = [
        "This is a full sentence about machine learning. And another about AI.",
        "Short.",
        "Another sufficiently long sentence about natural language processing here. More text.",
    ]
    queries = _extract_queries(chunks, max_queries=3)
    # Should produce meaningful queries (not arbitrary 120-char truncations)
    assert len(queries) >= 1
    for q in queries:
        assert len(q) > 25


def test_extract_queries_max_limit() -> None:
    chunks = [f"This is sentence number {i} with enough words to be meaningful. More text follows." for i in range(20)]
    queries = _extract_queries(chunks, max_queries=3)
    assert len(queries) <= 3


# ---------------------------------------------------------------------------
# AcademicAgent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_academic_agent_short_text() -> None:
    """Short text (< 2 chunks) should return quickly."""
    agent = AcademicAgent()
    result = await agent.run(AgentInput(document_id="doc-1", text="Short."))

    assert result.score == 0.0
    assert result.details.get("status") == "document_too_short"


@pytest.mark.asyncio
@patch("app.agents.academic_agent.search_scholar_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_academic_agent_no_scholar_results(
    mock_embed: AsyncMock, mock_scholar: AsyncMock
) -> None:
    """When Scholar returns nothing, should fall back to intra-doc analysis."""
    mock_scholar.return_value = {"results": []}
    mock_embed.return_value = _make_embeddings(6)

    agent = AcademicAgent()
    text = "This is a test sentence for academic analysis. " * 30
    chunks = [f"Chunk {i} with unique text content." for i in range(6)]
    result = await agent.run(AgentInput(document_id="doc-2", text=text, chunks=chunks))

    assert result.details.get("status") == "completed_intra_only"


@pytest.mark.asyncio
@patch("app.agents.academic_agent.search_scholar_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_academic_agent_with_papers(
    mock_embed: AsyncMock, mock_scholar: AsyncMock
) -> None:
    """When Scholar returns papers, should cross-compare and produce a score."""
    mock_scholar.return_value = {
        "results": [
            {
                "title": "A Study on Machine Learning",
                "authors": ["Smith", "Jones"],
                "year": "2023",
                "abstract": "This paper explores deep learning techniques.",
                "url": "https://example.com/paper1",
                "scholar_url": "https://scholar.google.com/...",
            }
        ]
    }
    # 6 chunks + 1 paper abstract = 7 embeddings
    mock_embed.return_value = _make_embeddings(7)

    agent = AcademicAgent()
    text = "This is a test sentence for academic analysis. " * 30
    chunks = [f"This is chunk number {i} with enough text content to be meaningful for searching." for i in range(6)]
    result = await agent.run(AgentInput(document_id="doc-3", text=text, chunks=chunks))

    assert result.details.get("status") == "completed"
    assert result.score >= 0.0
    assert result.details["scholar_papers_found"] == 1


@pytest.mark.asyncio
@patch("app.agents.academic_agent.search_scholar_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_academic_agent_high_similarity(
    mock_embed: AsyncMock, mock_scholar: AsyncMock
) -> None:
    """When a chunk matches a paper abstract closely, it should be flagged."""
    mock_scholar.return_value = {
        "results": [
            {
                "title": "Plagiarized Paper",
                "authors": ["Author"],
                "year": "2024",
                "abstract": "Exact matching abstract text.",
                "url": "https://example.com/plagiarized",
            }
        ]
    }
    # Create embeddings where chunks are very similar to the paper abstract
    base_vec = np.ones((1, 384), dtype=np.float32)
    base_vec /= np.linalg.norm(base_vec)
    # 6 chunks similar to paper + 1 paper = all nearly identical
    all_embs = np.tile(base_vec, (7, 1))
    mock_embed.return_value = all_embs

    agent = AcademicAgent()
    text = "This is matching text. " * 30
    chunks = [f"This matching chunk number {i} has enough content to be meaningful for searching." for i in range(6)]
    result = await agent.run(AgentInput(document_id="doc-4", text=text, chunks=chunks))

    assert result.score > 0.0
    assert len(result.flagged_passages) > 0
    # Flagged passages should reference the paper
    for fp in result.flagged_passages:
        assert "Plagiarized Paper" in fp.reason
