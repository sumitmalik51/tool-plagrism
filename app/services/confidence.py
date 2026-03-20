"""Confidence scoring service — produces overall confidence and risk level.

Evaluates agreement between agents, data quality, and score magnitude
to produce a single [0, 1] confidence value and a risk classification.
"""

from __future__ import annotations

import math

from app.config import settings
from app.models.schemas import AgentOutput, RiskLevel
from app.utils.logger import get_logger

logger = get_logger(__name__)


def compute_confidence(
    agent_outputs: list[AgentOutput],
    weighted_score: float,
) -> float:
    """Derive an overall confidence in ``weighted_score``.

    The confidence combines three signals:

    1. **Agent agreement** — low variance among agent scores → high confidence.
    2. **Individual confidence** — weighted average of each agent's own confidence.
    3. **Coverage** — how many agents actually contributed (non-error).

    Returns:
        A value in [0.0, 1.0].
    """
    valid = [o for o in agent_outputs if not _is_errored(o)]

    if not valid:
        return 0.0

    # --- 1. Agreement (inverse of normalised std-dev) -------------------------
    scores = [o.score for o in valid]
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    std_dev = math.sqrt(variance)
    # Normalise: std_dev of 50 (max realistic) → agreement ≈ 0
    agreement = max(1.0 - (std_dev / 50.0), 0.0)

    # --- 2. Weighted average of per-agent confidence --------------------------
    avg_conf = sum(o.confidence for o in valid) / len(valid)

    # --- 3. Coverage --- ------------------------------------------------------
    expected_agents = 4  # semantic, web_search, academic, ai_detection
    coverage = min(len(valid) / expected_agents, 1.0)

    # --- Combine (tunable weights) --------------------------------------------
    confidence = (
        agreement * 0.35
        + avg_conf * 0.45
        + coverage * 0.20
    )
    confidence = round(min(max(confidence, 0.0), 0.99), 2)

    logger.info(
        "confidence_computed",
        confidence=confidence,
        agreement=round(agreement, 4),
        avg_agent_confidence=round(avg_conf, 4),
        coverage=round(coverage, 4),
        agent_count=len(valid),
    )
    return confidence


def classify_risk(
    plagiarism_score: float,
    confidence: float,
) -> RiskLevel:
    """Map the final score + confidence to a risk level.

    Thresholds are loaded from settings so they can be tuned via
    environment variables without code changes.
    """
    high = settings.risk_threshold_high
    medium = settings.risk_threshold_medium

    # High-confidence high-score → HIGH risk
    if plagiarism_score >= high and confidence >= 0.4:
        return RiskLevel.HIGH

    # Score above medium threshold → MEDIUM
    if plagiarism_score >= medium:
        return RiskLevel.MEDIUM

    return RiskLevel.LOW


def generate_explanation(
    plagiarism_score: float,
    confidence: float,
    risk_level: RiskLevel,
    agent_outputs: list[AgentOutput],
) -> str:
    """Build a human-readable summary of the analysis."""
    valid = [o for o in agent_outputs if not _is_errored(o)]
    agent_lines = "\n".join(
        f"  - {o.agent_name}: score={o.score}, confidence={o.confidence}"
        for o in valid
    )
    errored = [o for o in agent_outputs if _is_errored(o)]
    error_note = ""
    if errored:
        names = ", ".join(o.agent_name for o in errored)
        error_note = f"\nNote: The following agents encountered errors and were excluded: {names}."

    return (
        f"PlagiarismGuard analysis complete.\n"
        f"Overall plagiarism score: {plagiarism_score}/100 "
        f"(confidence: {confidence:.0%}).\n"
        f"Risk level: {risk_level.value}.\n\n"
        f"Agent breakdown:\n{agent_lines}"
        f"{error_note}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_errored(output: AgentOutput) -> bool:
    """Return True if the agent output represents an error/fallback."""
    return output.confidence == 0.0 and "error" in output.details
