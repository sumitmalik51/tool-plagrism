"""Tests for the aggregation agent."""

from __future__ import annotations

import pytest

from app.agents.aggregation_agent import AggregationAgent
from app.models.schemas import AgentOutput, FlaggedPassage


def _agent(name: str, score: float, confidence: float, error: bool = False) -> AgentOutput:
    details: dict = {"error": "boom"} if error else {}
    fps: list[FlaggedPassage] = []
    if score > 30:
        fps = [FlaggedPassage(text=f"flagged by {name}", similarity_score=score / 100, reason="test")]
    return AgentOutput(
        agent_name=name,
        score=score,
        confidence=0.0 if error else confidence,
        flagged_passages=fps,
        details=details,
    )


@pytest.mark.asyncio
async def test_aggregation_happy_path() -> None:
    """Full aggregation with 4 healthy agents should produce a valid result."""
    outputs = [
        _agent("semantic_agent", 70, 0.9),
        _agent("web_search_agent", 60, 0.8),
        _agent("academic_agent", 50, 0.7),
        _agent("ai_detection_agent", 40, 0.6),
    ]
    agg = AggregationAgent()
    result = await agg.aggregate("doc-1", outputs)

    assert result.agent_name == "aggregation_agent"
    assert 0 <= result.score <= 100
    assert 0 <= result.confidence <= 1
    assert "risk_level" in result.details
    assert "explanation" in result.details
    assert result.details["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    assert len(result.flagged_passages) > 0


@pytest.mark.asyncio
async def test_aggregation_with_errored_agent() -> None:
    """Errored agents should be excluded; aggregation still works."""
    outputs = [
        _agent("semantic_agent", 80, 0.9),
        _agent("web_search_agent", 0, 0.0, error=True),
        _agent("academic_agent", 60, 0.7),
        _agent("ai_detection_agent", 40, 0.5),
    ]
    agg = AggregationAgent()
    result = await agg.aggregate("doc-2", outputs)

    assert result.score > 0
    # The errored agent should be noted in the explanation
    assert "web_search_agent" in result.details["explanation"]


@pytest.mark.asyncio
async def test_aggregation_empty() -> None:
    """No agent outputs → zero score, zero confidence."""
    agg = AggregationAgent()
    result = await agg.aggregate("doc-3", [])

    assert result.score == 0.0
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_aggregation_all_zero() -> None:
    """All agents scoring 0 → aggregated score 0, LOW risk."""
    outputs = [
        _agent("semantic_agent", 0, 0.8),
        _agent("web_search_agent", 0, 0.7),
        _agent("academic_agent", 0, 0.6),
        _agent("ai_detection_agent", 0, 0.5),
    ]
    agg = AggregationAgent()
    result = await agg.aggregate("doc-4", outputs)

    assert result.score == 0.0
    assert result.details["risk_level"] == "LOW"
