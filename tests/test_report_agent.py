"""Tests for the report agent."""

from __future__ import annotations

import pytest

from app.agents.report_agent import ReportAgent
from app.models.schemas import (
    AgentOutput,
    FlaggedPassage,
    PlagiarismReport,
    RiskLevel,
)


def _agg_output() -> AgentOutput:
    return AgentOutput(
        agent_name="aggregation_agent",
        score=45.0,
        confidence=0.65,
        flagged_passages=[
            FlaggedPassage(text="flagged", similarity_score=0.9, reason="test"),
        ],
        details={
            "risk_level": "MEDIUM",
            "explanation": "Test explanation.",
            "agent_scores": {},
        },
    )


def _det_outputs() -> list[AgentOutput]:
    return [
        AgentOutput(agent_name="semantic_agent", score=50, confidence=0.8),
        AgentOutput(agent_name="web_search_agent", score=40, confidence=0.6),
    ]


@pytest.mark.asyncio
async def test_report_agent_generate() -> None:
    """ReportAgent.generate should return a PlagiarismReport."""
    agent = ReportAgent()
    report = await agent.generate("doc-1", _agg_output(), _det_outputs())

    assert isinstance(report, PlagiarismReport)
    assert report.document_id == "doc-1"
    assert report.plagiarism_score == 45.0
    assert report.risk_level == RiskLevel.MEDIUM
    assert len(report.flagged_passages) > 0
    assert "Report generated at" in report.explanation


@pytest.mark.asyncio
async def test_report_agent_preserves_agent_results() -> None:
    agent = ReportAgent()
    det = _det_outputs()
    report = await agent.generate("doc-2", _agg_output(), det)

    assert len(report.agent_results) == len(det)
