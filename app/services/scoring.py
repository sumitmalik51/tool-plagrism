"""Scoring service — weighted aggregation of agent outputs.

Keeps all scoring math in a standalone, testable service.
The aggregation_agent delegates to this module so that
business logic stays out of the agent class itself (per AGENT_RULES).
"""

from __future__ import annotations

from app.config import settings
from app.models.schemas import AgentOutput, FlaggedPassage
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Map agent names → config weight attribute names
_WEIGHT_MAP: dict[str, str] = {
    "semantic_agent": "weight_semantic",
    "web_search_agent": "weight_web_search",
    "academic_agent": "weight_academic",
    "ai_detection_agent": "weight_ai_detection",
}


def get_agent_weight(agent_name: str) -> float:
    """Return the configured weight for an agent (0.0 if unknown)."""
    attr = _WEIGHT_MAP.get(agent_name)
    if attr is None:
        return 0.0
    return getattr(settings, attr, 0.0)


def compute_weighted_score(agent_outputs: list[AgentOutput]) -> float:
    """Compute a single plagiarism score from multiple agent outputs.

    Each agent's score (0-100) is multiplied by its configured weight.
    If an agent produced an error (score == 0 and confidence == 0),
    its weight is redistributed proportionally among the remaining agents.

    Returns:
        A score in [0, 100].
    """
    if not agent_outputs:
        return 0.0

    # Separate healthy results from errored ones
    healthy: list[tuple[AgentOutput, float]] = []
    for output in agent_outputs:
        w = get_agent_weight(output.agent_name)
        if w <= 0:
            continue
        is_error = output.confidence == 0.0 and "error" in output.details
        if not is_error:
            healthy.append((output, w))

    if not healthy:
        return 0.0

    # Normalise weights so they sum to 1.0
    total_weight = sum(w for _, w in healthy)
    if total_weight <= 0:
        return 0.0

    score = sum(output.score * (w / total_weight) for output, w in healthy)
    score = round(min(max(score, 0.0), 100.0), 2)

    logger.info(
        "weighted_score_computed",
        score=score,
        agents_used=[o.agent_name for o, _ in healthy],
        total_weight=round(total_weight, 4),
    )
    return score


def merge_flagged_passages(
    agent_outputs: list[AgentOutput],
    max_passages: int = 50,
) -> list[FlaggedPassage]:
    """Collect and deduplicate flagged passages from all agents.

    Keeps up to ``max_passages`` entries, sorted by descending similarity.
    """
    all_passages: list[FlaggedPassage] = []
    seen_texts: set[str] = set()

    for output in agent_outputs:
        for fp in output.flagged_passages:
            key = fp.text[:100]  # deduplicate on first 100 chars
            if key not in seen_texts:
                seen_texts.add(key)
                all_passages.append(fp)

    all_passages.sort(key=lambda p: p.similarity_score, reverse=True)
    return all_passages[:max_passages]
