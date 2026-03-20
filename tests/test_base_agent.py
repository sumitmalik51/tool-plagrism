"""Tests for the base agent contract."""

from __future__ import annotations

import pytest

from app.agents.base_agent import BaseAgent
from app.models.schemas import AgentInput, AgentOutput


class _DummyAgent(BaseAgent):
    """Minimal concrete agent for testing the base class."""

    @property
    def name(self) -> str:
        return "dummy_agent"

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_name=self.name,
            score=42.0,
            confidence=0.9,
        )


class _FailingAgent(BaseAgent):
    """Agent that always raises an exception."""

    @property
    def name(self) -> str:
        return "failing_agent"

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        raise RuntimeError("intentional failure")


@pytest.mark.asyncio
async def test_agent_returns_structured_output() -> None:
    """A well-behaved agent should return an AgentOutput."""
    agent = _DummyAgent()
    inp = AgentInput(document_id="doc-1", text="sample text")
    result = await agent.run(inp)
    assert isinstance(result, AgentOutput)
    assert result.agent_name == "dummy_agent"
    assert result.score == 42.0


@pytest.mark.asyncio
async def test_agent_handles_failure_gracefully() -> None:
    """A failing agent should return a zero-score output instead of crashing."""
    agent = _FailingAgent()
    inp = AgentInput(document_id="doc-2", text="sample text")
    result = await agent.run(inp)
    assert result.score == 0.0
    assert result.confidence == 0.0
    assert "error" in result.details
