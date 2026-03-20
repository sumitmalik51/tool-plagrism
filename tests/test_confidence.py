"""Tests for the confidence scoring service."""

from __future__ import annotations

from app.models.schemas import AgentOutput, RiskLevel
from app.services.confidence import classify_risk, compute_confidence, generate_explanation


def _agent(name: str, score: float, confidence: float, error: bool = False) -> AgentOutput:
    details: dict = {"error": "boom"} if error else {}
    return AgentOutput(
        agent_name=name,
        score=score,
        confidence=0.0 if error else confidence,
        flagged_passages=[],
        details=details,
    )


# ---------------------------------------------------------------------------
# compute_confidence
# ---------------------------------------------------------------------------

def test_confidence_high_agreement() -> None:
    """Agents that agree closely should produce higher confidence."""
    outputs = [
        _agent("semantic_agent", 50, 0.8),
        _agent("web_search_agent", 52, 0.7),
        _agent("academic_agent", 48, 0.75),
        _agent("ai_detection_agent", 51, 0.85),
    ]
    conf = compute_confidence(outputs, 50.0)
    assert conf >= 0.6


def test_confidence_low_agreement() -> None:
    """Wildly different scores should lower confidence."""
    outputs = [
        _agent("semantic_agent", 90, 0.8),
        _agent("web_search_agent", 10, 0.7),
        _agent("academic_agent", 50, 0.5),
        _agent("ai_detection_agent", 30, 0.4),
    ]
    conf = compute_confidence(outputs, 50.0)
    # Should still be positive but lower than the agreeing case
    assert 0.0 < conf < 0.8


def test_confidence_excludes_errors() -> None:
    """Errored agents should be fully excluded from confidence calc."""
    outputs = [
        _agent("semantic_agent", 70, 0.9),
        _agent("web_search_agent", 0, 0.0, error=True),
    ]
    conf = compute_confidence(outputs, 70.0)
    assert conf > 0.0


def test_confidence_all_errors() -> None:
    outputs = [_agent("semantic_agent", 0, 0.0, error=True)]
    assert compute_confidence(outputs, 0.0) == 0.0


def test_confidence_empty() -> None:
    assert compute_confidence([], 0.0) == 0.0


# ---------------------------------------------------------------------------
# classify_risk
# ---------------------------------------------------------------------------

def test_risk_high() -> None:
    assert classify_risk(75.0, 0.8) == RiskLevel.HIGH


def test_risk_medium() -> None:
    assert classify_risk(45.0, 0.5) == RiskLevel.MEDIUM


def test_risk_low() -> None:
    assert classify_risk(15.0, 0.9) == RiskLevel.LOW


def test_risk_high_score_low_confidence() -> None:
    """High score but very low confidence → still MEDIUM (not HIGH)."""
    assert classify_risk(80.0, 0.2) == RiskLevel.MEDIUM


# ---------------------------------------------------------------------------
# generate_explanation
# ---------------------------------------------------------------------------

def test_explanation_contains_score() -> None:
    outputs = [_agent("semantic_agent", 60, 0.8)]
    text = generate_explanation(60.0, 0.8, RiskLevel.HIGH, outputs)
    assert "60" in text
    assert "HIGH" in text
    assert "semantic_agent" in text


def test_explanation_notes_errors() -> None:
    outputs = [
        _agent("semantic_agent", 60, 0.8),
        _agent("web_search_agent", 0, 0.0, error=True),
    ]
    text = generate_explanation(60.0, 0.8, RiskLevel.HIGH, outputs)
    assert "web_search_agent" in text
    assert "error" in text.lower() or "excluded" in text.lower()
