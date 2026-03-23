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
    MatchGroup,
    PlagiarismReport,
    RiskLevel,
    SourceTextBlock,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_report(
    document_id: str,
    aggregation_output: AgentOutput,
    agent_outputs: list[AgentOutput],
    *,
    original_text: str = "",
) -> PlagiarismReport:
    """Assemble the final plagiarism report.

    Args:
        document_id: Identifier of the analysed document.
        aggregation_output: Result from ``AggregationAgent.aggregate()``.
        agent_outputs: Individual detection agent results for transparency.
        original_text: The original document text (for the document viewer).

    Returns:
        A fully populated ``PlagiarismReport``.
    """
    risk_level = RiskLevel(
        aggregation_output.details.get("risk_level", "LOW")
    )
    explanation = aggregation_output.details.get("explanation", "")

    # --- Collect detected sources from agent details --------------------------
    detected_sources = _extract_sources(
        agent_outputs, aggregation_output.flagged_passages
    )

    # --- Build match groups (categorised by detection type) --------------------
    match_groups = _build_match_groups(
        aggregation_output.flagged_passages, original_text
    )

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
        original_text=original_text,
        match_groups=match_groups,
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

def _extract_sources(
    agent_outputs: list[AgentOutput],
    flagged_passages: list[FlaggedPassage],
) -> list[DetectedSource]:
    """Pull detected source URLs from the merged flagged passages.

    Only sources that actually appear in the merged (deduplicated) flagged
    passages are included.  Sources are enriched with type, text_blocks,
    matched_words, and matched_passages for the similarity report.
    """
    # --- 1. Build a lookup of agent-level metadata for titles & types ---------
    agent_meta: dict[str, dict] = {}  # url → {title, source_type}
    for output in agent_outputs:
        agent = output.agent_name.lower()
        source_type = "Publication" if "academic" in agent else "Internet"

        for fp in output.flagged_passages:
            if fp.source and fp.source.startswith("http") and fp.source not in agent_meta:
                agent_meta[fp.source] = {"title": None, "source_type": source_type}

        for src in output.details.get("sources", []):
            url = src.get("url", "")
            if url and url not in agent_meta:
                agent_meta[url] = {
                    "title": src.get("title"),
                    "source_type": source_type,
                }
            elif url and url in agent_meta and not agent_meta[url]["title"]:
                agent_meta[url]["title"] = src.get("title")

    # --- 2. Group merged flagged passages by source URL -----------------------
    source_passages: dict[str, list[FlaggedPassage]] = {}
    for fp in flagged_passages:
        if fp.source and fp.source.startswith("http"):
            source_passages.setdefault(fp.source, []).append(fp)

    # --- 3. Build DetectedSource objects from actual matches -------------------
    sources: list[DetectedSource] = []
    for url, fps in source_passages.items():
        meta = agent_meta.get(url, {"title": None, "source_type": "Internet"})
        max_sim = max(fp.similarity_score for fp in fps)
        blocks = [
            SourceTextBlock(
                text=fp.text,
                word_count=len(fp.text.split()),
                similarity_score=fp.similarity_score,
            )
            for fp in fps
        ]
        total_words = sum(b.word_count for b in blocks)

        sources.append(
            DetectedSource(
                url=url,
                title=meta["title"],
                similarity=max_sim,
                source_type=meta["source_type"],
                text_blocks=len(blocks),
                matched_words=total_words,
                matched_passages=blocks,
            )
        )

    sources.sort(key=lambda s: s.similarity, reverse=True)

    # Assign source numbers
    for idx, src in enumerate(sources, start=1):
        src.source_number = idx

    return sources


def _classify_passage(fp: FlaggedPassage) -> str:
    """Classify a flagged passage into a match group category."""
    if fp.source and fp.source.startswith("internal_chunk_"):
        return "Internal Duplication"
    if fp.source and fp.source.startswith("http"):
        reason_lower = (fp.reason or "").lower()
        if any(kw in reason_lower for kw in ("scholar", "academic", "paper", "openalex")):
            return "Academic Match"
        return "Web Match"
    if fp.source == "ai_detection_heuristic":
        return "AI Generated"
    # Fallback based on reason text
    reason_lower = (fp.reason or "").lower()
    if any(kw in reason_lower for kw in ("scholar", "academic", "paper", "openalex")):
        return "Academic Match"
    if "internal" in reason_lower or "duplication" in reason_lower:
        return "Internal Duplication"
    if "ai" in reason_lower:
        return "AI Generated"
    return "Web Match"


_GROUP_ICONS = {
    "Web Match": "🌐",
    "Academic Match": "📚",
    "AI Generated": "🤖",
}

# Internal Duplication is excluded — self-similarity is not plagiarism.
_GROUP_ORDER = ["Web Match", "Academic Match", "AI Generated"]


def _build_match_groups(
    flagged_passages: list[FlaggedPassage],
    original_text: str,
) -> list[MatchGroup]:
    """Build categorised match groups from flagged passages.

    Percentage is estimated as matched-words / total-words.
    """
    total_words = max(len(original_text.split()), 1) if original_text else 1
    group_data: dict[str, list[FlaggedPassage]] = {g: [] for g in _GROUP_ORDER}

    for fp in flagged_passages:
        cat = _classify_passage(fp)
        if cat == "Internal Duplication":
            continue  # self-similarity is not plagiarism
        group_data.setdefault(cat, []).append(fp)

    groups: list[MatchGroup] = []
    for cat in _GROUP_ORDER:
        passages = group_data.get(cat, [])
        matched_words = sum(len(fp.text.split()) for fp in passages)
        pct = round((matched_words / total_words) * 100, 1)
        groups.append(
            MatchGroup(
                category=cat,
                icon=_GROUP_ICONS.get(cat, ""),
                count=len(passages),
                percentage=pct,
            )
        )

    return groups
