"""Orchestrator — runs all detection agents in parallel and assembles the report.

This is the main entry point that ties the full pipeline together:

    ingest → chunk (via tools) → parallel agents → aggregate → report

This orchestrator will be used temporarily before migrating to Azure Foundry agents.
"""

from __future__ import annotations

import asyncio
import time

from app.agents.academic_agent import AcademicAgent
from app.agents.aggregation_agent import AggregationAgent
from app.agents.ai_detection_agent import AIDetectionAgent
from app.agents.report_agent import ReportAgent
from app.agents.semantic_agent import SemanticAgent
from app.agents.web_search_agent import WebSearchAgent
from app.models.schemas import AgentInput, AgentOutput, PlagiarismReport
from app.tools.content_extractor_tool import chunk_text
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_pipeline(document_id: str, text: str) -> PlagiarismReport:
    """Execute the full plagiarism detection pipeline.

    Args:
        document_id: Unique identifier for the document.
        text: Extracted plain-text content of the document.

    Returns:
        A ``PlagiarismReport`` with scores, flagged passages, and explanation.
    """
    logger.info("pipeline_started", document_id=document_id)

    pipeline_start = time.perf_counter()

    # --- 1. Chunk the text (via content_extractor_tool) -----------------------
    chunk_result = chunk_text(text, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
    chunks = chunk_result["chunks"]
    agent_input = AgentInput(document_id=document_id, text=text, chunks=chunks)

    logger.info("chunks_prepared", document_id=document_id, chunk_count=len(chunks))

    # --- 2. Run detection agents in parallel ----------------------------------
    detection_agents = [
        SemanticAgent(),
        WebSearchAgent(),
        AcademicAgent(),
        AIDetectionAgent(),
    ]

    agent_outputs: list[AgentOutput] = await asyncio.gather(
        *(agent.run(agent_input) for agent in detection_agents)
    )

    logger.info(
        "detection_agents_complete",
        document_id=document_id,
        agents=[o.agent_name for o in agent_outputs],
    )

    # --- 3. Aggregate ---------------------------------------------------------
    aggregation_agent = AggregationAgent()
    aggregation_output = await aggregation_agent.aggregate(document_id, agent_outputs)

    # --- 4. Generate report ---------------------------------------------------
    report_agent = ReportAgent()
    report = await report_agent.generate(
        document_id, aggregation_output, agent_outputs,
        original_text=text,
    )

    pipeline_elapsed = round(time.perf_counter() - pipeline_start, 3)

    logger.info(
        "pipeline_complete",
        document_id=document_id,
        plagiarism_score=report.plagiarism_score,
        risk_level=report.risk_level.value,
        pipeline_elapsed_s=pipeline_elapsed,
    )

    return report
