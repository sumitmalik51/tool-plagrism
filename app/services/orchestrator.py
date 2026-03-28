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
from app.tools.citation_stripper import prepare_text_for_scanning
from app.tools.language_detector import detect_language
from app.config import settings
from app.services import progress as scan_progress
from app.services.repository import store_document_fingerprints
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _adaptive_query_count(text_length: int) -> tuple[int, int]:
    """Scale search query counts based on document length.

    Short papers (< 5K chars) get the default 8 queries.
    Medium papers (5-20K) get 12.
    Large papers (20-50K) get 16.
    Very large papers (50K+) get 20.

    Returns (web_queries, scholar_queries).
    """
    if text_length < 5_000:
        return settings.web_search_max_queries, settings.scholar_max_queries
    elif text_length < 20_000:
        return 12, 12
    elif text_length < 50_000:
        return 16, 16
    else:
        return 20, 20


async def run_pipeline(
    document_id: str,
    text: str,
    *,
    excluded_domains: list[str] | None = None,
    use_gpt_ai_detection: bool = False,
) -> PlagiarismReport:
    """Execute the full plagiarism detection pipeline.

    Args:
        document_id: Unique identifier for the document.
        text: Extracted plain-text content of the document.
        excluded_domains: Optional list of domains to exclude from results.

    Returns:
        A ``PlagiarismReport`` with scores, flagged passages, and explanation.
    """
    logger.info("pipeline_started", document_id=document_id)
    tracker = scan_progress.get_or_create(document_id)

    pipeline_start = time.perf_counter()

    # --- 0a. Detect document language -----------------------------------------
    tracker.emit("language", "Detecting document language...", 5)
    lang_info = detect_language(text)
    logger.info(
        "language_detected",
        document_id=document_id,
        language=lang_info["language"],
        language_name=lang_info["language_name"],
        confidence=lang_info["confidence"],
    )

    # --- 0b. Citation-aware preprocessing — strip references & inline cites ---
    tracker.emit("preprocessing", "Stripping citations and references...", 10)
    scan_text, citation_meta = prepare_text_for_scanning(text)
    logger.info(
        "citation_preprocessing_done",
        document_id=document_id,
        chars_removed=citation_meta["chars_removed"],
        ref_section_removed=citation_meta["reference_section_removed"],
    )

    # --- 1. Chunk the text (via content_extractor_tool) -----------------------
    tracker.emit("chunking", "Splitting document into chunks...", 15)
    chunk_result = chunk_text(scan_text, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
    chunks = chunk_result["chunks"]

    logger.info("chunks_prepared", document_id=document_id, chunk_count=len(chunks))

    # --- 1b. Scale search coverage based on document size ---------------------
    web_q, scholar_q = _adaptive_query_count(len(scan_text))
    logger.info(
        "adaptive_queries",
        document_id=document_id,
        text_length=len(scan_text),
        web_queries=web_q,
        scholar_queries=scholar_q,
    )

    agent_input = AgentInput(
        document_id=document_id,
        text=scan_text,
        chunks=chunks,
        max_queries=web_q,
        use_gpt_ai_detection=use_gpt_ai_detection,
    )

    # --- 2. Run detection agents in parallel ----------------------------------
    tracker.emit("agents", "Running detection agents in parallel...", 20,
                 agents=["semantic", "web_search", "academic", "ai_detection"])
    detection_agents = [
        SemanticAgent(),
        WebSearchAgent(),
        AcademicAgent(),
        AIDetectionAgent(),
    ]

    async def _run_agent_with_progress(agent, inp, idx):
        result = await agent.run(inp)
        pct = 20 + ((idx + 1) * 15)  # 35, 50, 65, 80
        tracker.emit(
            "agent_done",
            f"{agent.name} completed (score: {result.score:.1f})",
            min(pct, 75),
            agent_name=agent.name,
            score=result.score,
        )
        return result

    agent_outputs: list[AgentOutput] = await asyncio.gather(
        *(_run_agent_with_progress(agent, agent_input, i)
          for i, agent in enumerate(detection_agents))
    )

    logger.info(
        "detection_agents_complete",
        document_id=document_id,
        agents=[o.agent_name for o in agent_outputs],
    )

    # --- 3. Aggregate ---------------------------------------------------------
    tracker.emit("aggregation", "Aggregating results...", 80)
    aggregation_agent = AggregationAgent()
    aggregation_output = await aggregation_agent.aggregate(document_id, agent_outputs)

    # --- 4. Generate report ---------------------------------------------------
    tracker.emit("report", "Generating final report...", 90)
    report_agent = ReportAgent()
    report = await report_agent.generate(
        document_id, aggregation_output, agent_outputs,
        original_text=text,
    )

    # Attach language and citation metadata to the report
    report.language = lang_info.get("language", "en")
    report.language_name = lang_info.get("language_name", "English")
    report.citation_metadata = citation_meta

    # --- 5. Filter excluded domains -------------------------------------------
    if excluded_domains:
        _filter_excluded_domains(report, excluded_domains)

    # --- 6. Store fingerprints for institutional repository -------------------
    try:
        store_document_fingerprints(document_id, text)
    except Exception as exc:
        logger.warning("fingerprint_storage_skipped", document_id=document_id, error=str(exc))

    pipeline_elapsed = round(time.perf_counter() - pipeline_start, 3)

    tracker.emit("complete", f"Analysis complete — score: {report.plagiarism_score:.1f}/100", 100,
                 plagiarism_score=report.plagiarism_score,
                 risk_level=report.risk_level.value)
    tracker.complete()

    logger.info(
        "pipeline_complete",
        document_id=document_id,
        plagiarism_score=report.plagiarism_score,
        risk_level=report.risk_level.value,
        pipeline_elapsed_s=pipeline_elapsed,
    )

    return report


def _filter_excluded_domains(
    report: PlagiarismReport,
    excluded_domains: list[str],
) -> None:
    """Remove flagged passages and sources from excluded domains."""
    from urllib.parse import urlparse

    normalised = {d.lower().removeprefix("www.") for d in excluded_domains if d}

    def _is_excluded(url: str | None) -> bool:
        if not url:
            return False
        try:
            host = urlparse(url).hostname or ""
            host = host.lower().removeprefix("www.")
            return host in normalised or any(host.endswith("." + d) for d in normalised)
        except Exception:
            return False

    # Filter flagged passages
    report.flagged_passages = [
        fp for fp in report.flagged_passages
        if not _is_excluded(fp.source)
    ]

    # Filter detected sources
    report.detected_sources = [
        ds for ds in report.detected_sources
        if not _is_excluded(ds.url)
    ]

    logger.info(
        "excluded_domains_applied",
        excluded=list(normalised),
        remaining_passages=len(report.flagged_passages),
        remaining_sources=len(report.detected_sources),
    )
