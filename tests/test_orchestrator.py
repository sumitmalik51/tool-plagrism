"""Tests for the orchestrator (end-to-end pipeline)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.schemas import PlagiarismReport
from app.services.orchestrator import run_pipeline


@pytest.mark.asyncio
@patch("app.agents.web_search_agent.fetch_page_text", new_callable=AsyncMock, return_value={})
@patch("app.agents.web_search_agent.search_multiple", new_callable=AsyncMock, return_value=[])
@patch("app.agents.academic_agent.search_scholar_multi", new_callable=AsyncMock, return_value={"results": []})
@patch("app.agents.academic_agent.search_arxiv_multi", new_callable=AsyncMock, return_value={"results": []})
@patch("app.agents.academic_agent.search_openalex_multi", new_callable=AsyncMock, return_value={"results": []})
@patch("app.tools.embedding_tool.generate_embeddings", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.generate_embeddings", new_callable=AsyncMock)
@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_pipeline_returns_report(mock_sem, mock_web, mock_acad, mock_tool, *_mocks) -> None:
    """The full pipeline should return a PlagiarismReport even with stub agents."""
    import numpy as np

    # Provide fake embeddings so no agent tries to load the real model
    _emb = np.random.default_rng(0).random((6, 384)).astype(np.float32)
    for m in (mock_sem, mock_web, mock_acad, mock_tool):
        m.return_value = _emb

    text = "This is a test document with enough content to chunk. " * 20
    report = await run_pipeline("doc-pipeline-1", text)

    assert isinstance(report, PlagiarismReport)
    assert report.document_id == "doc-pipeline-1"
    assert 0 <= report.plagiarism_score <= 100
    assert 0 <= report.confidence_score <= 1
    assert report.risk_level in ("LOW", "MEDIUM", "HIGH")
    assert "Report generated at" in report.explanation
    assert len(report.agent_results) == 3  # 3 detection agents (semantic skipped when weight_semantic == 0)


@pytest.mark.asyncio
@patch("app.agents.web_search_agent.fetch_page_text", new_callable=AsyncMock, return_value={})
@patch("app.agents.web_search_agent.search_multiple", new_callable=AsyncMock, return_value=[])
@patch("app.agents.academic_agent.search_scholar_multi", new_callable=AsyncMock, return_value={"results": []})
@patch("app.agents.academic_agent.search_arxiv_multi", new_callable=AsyncMock, return_value={"results": []})
@patch("app.agents.academic_agent.search_openalex_multi", new_callable=AsyncMock, return_value={"results": []})
@patch("app.tools.embedding_tool.generate_embeddings", new_callable=AsyncMock)
@patch("app.agents.academic_agent.generate_embeddings", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.generate_embeddings", new_callable=AsyncMock)
@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_pipeline_short_text(mock_sem, mock_web, mock_acad, mock_tool, *_mocks) -> None:
    """Very short text should still produce a valid report (not crash)."""
    import numpy as np

    _emb = np.empty((0, 384), dtype=np.float32)
    for m in (mock_sem, mock_web, mock_acad, mock_tool):
        m.return_value = _emb

    report = await run_pipeline("doc-short", "Short.")

    assert isinstance(report, PlagiarismReport)
    # With active AI detection agent, short text may get a small non-zero score
    assert report.plagiarism_score < 30.0
