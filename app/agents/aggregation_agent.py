"""Aggregation agent — combines outputs from all detection agents.

Receives a list of ``AgentOutput`` objects (injected via ``details``),
computes a weighted plagiarism score, overall confidence, risk level,
and a human-readable explanation.
"""

from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.models.schemas import AgentInput, AgentOutput, FlaggedPassage
from app.services.confidence import classify_risk, compute_confidence, generate_explanation
from app.services.scoring import compute_weighted_score, merge_flagged_passages


class AggregationAgent(BaseAgent):
    """Merges individual agent scores into a single weighted plagiarism score.

    Expected usage::

        agg = AggregationAgent()
        result = await agg.run(AgentInput(
            document_id="...",
            text="...",
            # Pass agent outputs via the ``chunks`` field is not appropriate,
            # so we serialise them into ``details`` on a wrapper AgentInput.
        ))

    The caller (orchestrator) should call :meth:`aggregate` directly instead
    of going through the generic ``run`` path.
    """

    @property
    def name(self) -> str:
        return "aggregation_agent"

    async def aggregate(self, document_id: str, agent_outputs: list[AgentOutput]) -> AgentOutput:
        """Public entry point used by the orchestrator.

        Args:
            document_id: The document being analysed.
            agent_outputs: Results from the detection agents.

        Returns:
            An ``AgentOutput`` carrying the aggregated score, confidence,
            merged flagged passages, and a rich ``details`` dict.
        """
        self.logger.info(
            "aggregation_started",
            document_id=document_id,
            agent_count=len(agent_outputs),
        )

        # --- Weighted score ---------------------------------------------------
        weighted_score = compute_weighted_score(agent_outputs)

        # --- Confidence -------------------------------------------------------
        confidence = compute_confidence(agent_outputs, weighted_score)

        # --- Risk level -------------------------------------------------------
        risk_level = classify_risk(weighted_score, confidence)

        # --- Flagged passages -------------------------------------------------
        flagged = merge_flagged_passages(agent_outputs)

        # --- Explanation ------------------------------------------------------
        explanation = generate_explanation(
            weighted_score, confidence, risk_level, agent_outputs,
        )

        self.logger.info(
            "aggregation_complete",
            document_id=document_id,
            score=weighted_score,
            confidence=confidence,
            risk_level=risk_level.value,
            flagged_count=len(flagged),
        )

        return AgentOutput(
            agent_name=self.name,
            score=weighted_score,
            confidence=confidence,
            flagged_passages=flagged,
            details={
                "risk_level": risk_level.value,
                "explanation": explanation,
                "agent_scores": {
                    o.agent_name: {"score": o.score, "confidence": o.confidence}
                    for o in agent_outputs
                },
            },
        )

    # --- BaseAgent contract (not used directly by orchestrator) ---------------

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        """Fallback for the base-class ``run()`` path.

        Not the intended entry point — prefer :meth:`aggregate`.
        """
        self.logger.warning(
            "aggregation_via_analyze",
            document_id=agent_input.document_id,
        )
        return AgentOutput(
            agent_name=self.name,
            score=0.0,
            confidence=0.0,
            details={"warning": "Use aggregate() with agent_outputs instead"},
        )
