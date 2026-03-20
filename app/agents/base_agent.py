"""Abstract base class for all detection agents."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from app.models.schemas import AgentInput, AgentOutput
from app.utils.logger import get_logger


class BaseAgent(ABC):
    """Base class that every detection agent must extend.

    Guarantees a consistent interface:
      • Accepts ``AgentInput``
      • Returns ``AgentOutput``
      • Provides built-in structured logging with execution time tracking
    """

    def __init__(self) -> None:
        self.logger = get_logger(self.name)

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the agent (e.g. 'semantic_agent')."""

    async def run(self, agent_input: AgentInput) -> AgentOutput:
        """Execute the agent and return structured output.

        Wraps ``_analyze`` with logging, execution time tracking,
        and error handling so that individual agents only need to
        implement ``_analyze``.
        """
        self.logger.info("agent_started", document_id=agent_input.document_id)
        start = time.perf_counter()
        try:
            result = await self._analyze(agent_input)
            elapsed = round(time.perf_counter() - start, 3)
            self.logger.info(
                "agent_completed",
                document_id=agent_input.document_id,
                score=result.score,
                confidence=result.confidence,
                elapsed_s=elapsed,
            )
            return result
        except Exception as exc:
            elapsed = round(time.perf_counter() - start, 3)
            self.logger.error(
                "agent_failed",
                document_id=agent_input.document_id,
                error=str(exc),
                elapsed_s=elapsed,
            )
            # Return a safe zero-score result so the pipeline can continue
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.0,
                flagged_passages=[],
                details={"error": str(exc)},
            )

    @abstractmethod
    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        """Core analysis logic — implemented by each concrete agent."""
