"""Tests for the orchestrator (end-to-end pipeline)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.schemas import PlagiarismReport
from app.services.orchestrator import run_pipeline


@pytest.mark.asyncio
@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_pipeline_returns_report(mock_embed: AsyncMock) -> None:
    """The full pipeline should return a PlagiarismReport even with stub agents."""
    import numpy as np

    # Provide fake embeddings so the semantic agent doesn't try to load model
    mock_embed.return_value = np.random.default_rng(0).random((6, 384)).astype(np.float32)

    text = "This is a test document with enough content to chunk. " * 20
    report = await run_pipeline("doc-pipeline-1", text)

    assert isinstance(report, PlagiarismReport)
    assert report.document_id == "doc-pipeline-1"
    assert 0 <= report.plagiarism_score <= 100
    assert 0 <= report.confidence_score <= 1
    assert report.risk_level in ("LOW", "MEDIUM", "HIGH")
    assert "Report generated at" in report.explanation
    assert len(report.agent_results) == 4  # 4 detection agents


@pytest.mark.asyncio
@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
async def test_pipeline_short_text(mock_embed: AsyncMock) -> None:
    """Very short text should still produce a valid report (not crash)."""
    import numpy as np

    mock_embed.return_value = np.empty((0, 384), dtype=np.float32)

    report = await run_pipeline("doc-short", "Short.")

    assert isinstance(report, PlagiarismReport)
    # With active AI detection agent, short text may get a small non-zero score
    assert report.plagiarism_score < 30.0
