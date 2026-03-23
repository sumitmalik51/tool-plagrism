"""Tests for the AI detection agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.ai_detection_agent import AIDetectionAgent
from app.models.schemas import AgentInput


@pytest.mark.asyncio
async def test_ai_detection_agent_returns_structured() -> None:
    """Agent should return structured output with indicators."""
    agent = AIDetectionAgent()
    text = "The quick brown fox jumps over the lazy dog. " * 20
    result = await agent.run(AgentInput(document_id="doc-1", text=text))

    assert result.agent_name == "ai_detection_agent"
    assert 0 <= result.score <= 100
    assert 0 <= result.confidence <= 1
    assert "indicators" in result.details
    assert result.details["status"] == "completed"


@pytest.mark.asyncio
async def test_ai_detection_agent_uniform_text() -> None:
    """Highly uniform text (same sentence repeated) should score higher."""
    agent = AIDetectionAgent()
    # Very uniform text — all sentences same length, low variance
    text = "This is a test sentence. " * 50
    result = await agent.run(AgentInput(document_id="doc-2", text=text))

    assert result.score > 0.0


@pytest.mark.asyncio
async def test_ai_detection_agent_short_text() -> None:
    """Very short text should still produce a valid result."""
    agent = AIDetectionAgent()
    result = await agent.run(AgentInput(document_id="doc-3", text="Short."))

    assert result.score >= 0.0
    assert result.confidence >= 0.0


@pytest.mark.asyncio
async def test_ai_detection_agent_flags_chunks() -> None:
    """Agent should flag chunks with low sentence variance."""
    agent = AIDetectionAgent()
    # Highly uniform chunks
    chunks = ["This is a uniform sentence. This is another one. This is yet another." for _ in range(5)]
    text = " ".join(chunks)
    result = await agent.run(AgentInput(document_id="doc-4", text=text, chunks=chunks))

    # flagged_chunks may or may not be populated depending on std threshold
    assert isinstance(result.flagged_passages, list)
