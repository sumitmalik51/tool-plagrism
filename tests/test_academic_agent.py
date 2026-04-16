"""Tests for the academic agent — uses mocked OpenAlex/Scholar & embeddings."""

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


def _make_dynamic_embeddings(dim: int = 384):
    """Return a side_effect function that generates embeddings matching input size."""
    def _side_effect(texts):
        n = len(texts)
        return _make_embeddings(n, dim)
    return _side_effect


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
@patch("app.agents.academic_agent.search_arxiv_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.search_openalex_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_academic_agent_no_scholar_results(
    mock_embed: AsyncMock, mock_openalex: AsyncMock, mock_arxiv: AsyncMock, mock_scholar: AsyncMock
) -> None:
    """When both OpenAlex and Scholar return nothing, fall back to intra-doc."""
    mock_openalex.return_value = {"results": []}
    mock_arxiv.return_value = {"results": []}
    mock_scholar.return_value = {"results": []}
    mock_embed.side_effect = _make_dynamic_embeddings()

    agent = AcademicAgent()
    text = "This is a test sentence for academic analysis. " * 30
    chunks = [f"Chunk {i} with unique text content." for i in range(6)]
    result = await agent.run(AgentInput(document_id="doc-2", text=text, chunks=chunks))

    assert result.details.get("status") == "completed_intra_only"


@pytest.mark.asyncio
@patch("app.agents.academic_agent.search_scholar_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.search_arxiv_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.search_openalex_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_academic_agent_with_papers(
    mock_embed: AsyncMock, mock_openalex: AsyncMock, mock_arxiv: AsyncMock, mock_scholar: AsyncMock
) -> None:
    """When OpenAlex returns papers, should cross-compare and produce a score."""
    mock_openalex.return_value = {
        "results": [
            {
                "title": "A Study on Machine Learning",
                "authors": ["Smith", "Jones"],
                "year": "2023",
                "abstract": "This paper explores deep learning techniques.",
                "url": "https://doi.org/10.1234/example",
                "openalex_id": "https://openalex.org/W12345",
            }
        ]
    }
    mock_arxiv.return_value = {"results": []}
    # Scholar should NOT be called since OpenAlex returned results
    mock_scholar.return_value = {"results": []}
    # Use dynamic embeddings to handle both relevance scoring and main embedding calls
    mock_embed.side_effect = _make_dynamic_embeddings()

    agent = AcademicAgent()
    text = "This is a test sentence for academic analysis. " * 30
    chunks = [f"This is chunk number {i} with enough text content to be meaningful for searching." for i in range(6)]
    result = await agent.run(AgentInput(document_id="doc-3", text=text, chunks=chunks))

    assert result.details.get("status") == "completed"
    assert result.score >= 0.0
    assert result.details["papers_found"] == 1
    assert result.details["source_used"] == "openalex"


@pytest.mark.asyncio
@patch("app.agents.academic_agent.search_scholar_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.search_arxiv_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.search_openalex_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_academic_agent_high_similarity(
    mock_embed: AsyncMock, mock_openalex: AsyncMock, mock_arxiv: AsyncMock, mock_scholar: AsyncMock
) -> None:
    """When a chunk matches a paper abstract closely, it should be flagged."""
    mock_openalex.return_value = {
        "results": [
            {
                "title": "Plagiarized Paper",
                "authors": ["Author"],
                "year": "2024",
                "abstract": "Exact matching abstract text.",
                "url": "https://doi.org/10.1234/plagiarized",
                "openalex_id": "https://openalex.org/W99999",
            }
        ]
    }
    mock_arxiv.return_value = {"results": []}
    mock_scholar.return_value = {"results": []}
    # Create embeddings where all vectors are nearly identical (high similarity)
    def _high_sim_embeddings(texts):
        n = len(texts)
        base_vec = np.ones((1, 384), dtype=np.float32)
        base_vec /= np.linalg.norm(base_vec)
        return np.tile(base_vec, (n, 1))
    mock_embed.side_effect = _high_sim_embeddings

    agent = AcademicAgent()
    text = "This is matching text. " * 30
    chunks = [f"This matching chunk number {i} has enough content to be meaningful for searching." for i in range(6)]
    result = await agent.run(AgentInput(document_id="doc-4", text=text, chunks=chunks))

    assert result.score > 0.0
    assert len(result.flagged_passages) > 0
    # Flagged passages should reference the paper
    for fp in result.flagged_passages:
        assert "Plagiarized Paper" in fp.reason


@pytest.mark.asyncio
@patch("app.agents.academic_agent.search_scholar_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.search_arxiv_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.search_openalex_multi", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_academic_agent_scholar_fallback(
    mock_embed: AsyncMock, mock_openalex: AsyncMock, mock_arxiv: AsyncMock, mock_scholar: AsyncMock
) -> None:
    """When OpenAlex returns nothing, should fall back to Scholar."""
    mock_openalex.return_value = {"results": []}
    mock_arxiv.return_value = {"results": []}
    mock_scholar.return_value = {
        "results": [
            {
                "title": "Fallback Scholar Paper",
                "authors": ["Scholar Author"],
                "year": "2025",
                "abstract": "Found via Scholar fallback.",
                "url": "https://example.com/scholar-fallback",
                "scholar_url": "https://scholar.google.com/...",
            }
        ]
    }
    # Use dynamic embeddings to handle relevance scoring + main embedding calls
    mock_embed.side_effect = _make_dynamic_embeddings()

    agent = AcademicAgent()
    text = "Text for Scholar fallback test. " * 30
    chunks = [f"Scholar fallback chunk {i} with enough words to pass validation." for i in range(6)]
    result = await agent.run(AgentInput(document_id="doc-5", text=text, chunks=chunks))

    assert result.details.get("status") == "completed"
    assert result.details["source_used"] == "scholar"
    assert result.details["papers_found"] == 1
