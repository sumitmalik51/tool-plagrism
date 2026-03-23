"""Report generation service — builds the final PlagiarismReport.

Transforms the aggregation_agent's ``AgentOutput`` and the individual
detection agent outputs into the ``PlagiarismReport`` schema that is
returned to the API consumer.  Keeps formatting / assembly logic out
of both agents and routes (per AGENT_RULES).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import (
    AgentOutput,
    DetectedSource,
    FlaggedPassage,
    PlagiarismReport,
    RiskLevel,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_report(
    document_id: str,
    aggregation_output: AgentOutput,
    agent_outputs: list[AgentOutput],
) -> PlagiarismReport:
    """Assemble the final plagiarism report.

    Args:
        document_id: Identifier of the analysed document.
        aggregation_output: Result from ``AggregationAgent.aggregate()``.
        agent_outputs: Individual detection agent results for transparency.

    Returns:
        A fully populated ``PlagiarismReport``.
    """
    risk_level = RiskLevel(
        aggregation_output.details.get("risk_level", "LOW")
    )
    explanation = aggregation_output.details.get("explanation", "")

    # --- Collect detected sources from agent details --------------------------
    detected_sources = _extract_sources(agent_outputs)

    # --- Enrich explanation with timestamp ------------------------------------
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    full_explanation = (
        f"{explanation}\n\n"
        f"Report generated at {timestamp}."
    )

    report = PlagiarismReport(
        document_id=document_id,
        plagiarism_score=aggregation_output.score,
        confidence_score=aggregation_output.confidence,
        risk_level=risk_level,
        detected_sources=detected_sources,
        flagged_passages=aggregation_output.flagged_passages,
        agent_results=agent_outputs,
        explanation=full_explanation,
    )

    logger.info(
        "report_generated",
        document_id=document_id,
        plagiarism_score=report.plagiarism_score,
        risk_level=report.risk_level.value,
        flagged_count=len(report.flagged_passages),
        source_count=len(report.detected_sources),
    )

    return report


def report_to_json(report: PlagiarismReport) -> dict:
    """Serialise a ``PlagiarismReport`` to a plain dict (JSON-ready).

    Uses Pydantic's ``model_dump`` with ``mode="json"`` so that enums,
    datetimes, etc. are properly serialised.
    """
    return report.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_sources(agent_outputs: list[AgentOutput]) -> list[DetectedSource]:
    """Pull detected source URLs from agent flagged passages and details.

    Sources are deduplicated by URL.
    """
    seen: set[str] = set()
    sources: list[DetectedSource] = []

    for output in agent_outputs:
        # From flagged passages that have a source URL
        for fp in output.flagged_passages:
            if fp.source and fp.source.startswith("http"):
                if fp.source not in seen:
                    seen.add(fp.source)
                    sources.append(
                        DetectedSource(
                            url=fp.source,
                            title=None,
                            similarity=fp.similarity_score,
                        )
                    )

        # From agent-specific details (e.g. web_search_agent may list URLs)
        for src in output.details.get("sources", []):
            url = src.get("url", "")
            if url and url not in seen:
                seen.add(url)
                raw_sim = src.get("similarity", 0.0)
                # Clamp to [0, 1] — cosine similarity can be slightly negative
                clamped_sim = max(0.0, min(float(raw_sim), 1.0))
                sources.append(
                    DetectedSource(
                        url=url,
                        title=src.get("title"),
                        similarity=clamped_sim,
                    )
                )

    sources.sort(key=lambda s: s.similarity, reverse=True)
    return sources
