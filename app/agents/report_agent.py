"""Report agent — generates the final structured plagiarism report.

Receives individual agent outputs (via :meth:`generate`) and the
aggregation result, then delegates to the report_generator service
to build a ``PlagiarismReport``.
"""

from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.models.schemas import AgentInput, AgentOutput, PlagiarismReport
from app.services.report_generator import build_report, report_to_json


class ReportAgent(BaseAgent):
    """Produces a structured JSON plagiarism report with explanations."""

    @property
    def name(self) -> str:
        return "report_agent"

    async def generate(
        self,
        document_id: str,
        aggregation_output: AgentOutput,
        agent_outputs: list[AgentOutput],
        *,
        original_text: str = "",
    ) -> PlagiarismReport:
        """Build the final report from aggregation + individual agent results.

        Args:
            document_id: The analysed document's identifier.
            aggregation_output: Result from ``AggregationAgent.aggregate()``.
            agent_outputs: Raw results from every detection agent.
            original_text: The document's full text for the report viewer.

        Returns:
            A fully populated ``PlagiarismReport`` ready for JSON serialisation.
        """
        self.logger.info("report_generation_started", document_id=document_id)

        report = build_report(
            document_id, aggregation_output, agent_outputs,
            original_text=original_text,
        )

        self.logger.info(
            "report_generation_complete",
            document_id=document_id,
            plagiarism_score=report.plagiarism_score,
            risk_level=report.risk_level.value,
            flagged_count=len(report.flagged_passages),
        )

        return report

    # --- BaseAgent contract (fallback — prefer generate()) --------------------

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        """Not the intended entry point — prefer :meth:`generate`."""
        self.logger.warning(
            "report_via_analyze",
            document_id=agent_input.document_id,
        )
        return AgentOutput(
            agent_name=self.name,
            score=0.0,
            confidence=0.0,
            details={"warning": "Use generate() with aggregation_output instead"},
        )
