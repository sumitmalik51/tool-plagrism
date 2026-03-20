"""Tests for the scoring service (weighted aggregation)."""

from __future__ import annotations

from app.models.schemas import AgentOutput
from app.services.scoring import compute_weighted_score, merge_flagged_passages, get_agent_weight
from app.models.schemas import FlaggedPassage


def _agent(name: str, score: float, confidence: float, error: bool = False) -> AgentOutput:
    """Helper to build a minimal AgentOutput."""
    details: dict = {"error": "boom"} if error else {}
    return AgentOutput(
        agent_name=name,
        score=score,
        confidence=0.0 if error else confidence,
        flagged_passages=[],
        details=details,
    )


# ---------------------------------------------------------------------------
# compute_weighted_score
# ---------------------------------------------------------------------------

def test_weighted_score_single_agent() -> None:
    """With one healthy agent, the score equals that agent's score."""
    outputs = [_agent("semantic_agent", 80.0, 0.9)]
    assert compute_weighted_score(outputs) == 80.0


def test_weighted_score_all_agents_equal() -> None:
    """When all agents agree, the weighted score equals the common score."""
    outputs = [
        _agent("semantic_agent", 50.0, 0.8),
        _agent("web_search_agent", 50.0, 0.7),
        _agent("academic_agent", 50.0, 0.6),
        _agent("ai_detection_agent", 50.0, 0.9),
    ]
    assert compute_weighted_score(outputs) == 50.0


def test_weighted_score_mixed() -> None:
    """Different scores should produce a weighted average."""
    outputs = [
        _agent("semantic_agent", 90.0, 0.9),       # w=0.30
        _agent("web_search_agent", 60.0, 0.7),     # w=0.25
        _agent("academic_agent", 40.0, 0.6),        # w=0.25
        _agent("ai_detection_agent", 20.0, 0.5),    # w=0.20
    ]
    score = compute_weighted_score(outputs)
    # Manual: (90*0.30 + 60*0.25 + 40*0.25 + 20*0.20) / 1.0 = 27+15+10+4 = 56
    assert score == 56.0


def test_weighted_score_excludes_errored_agents() -> None:
    """Errored agents should be excluded; their weight redistributed."""
    outputs = [
        _agent("semantic_agent", 80.0, 0.9),
        _agent("web_search_agent", 0.0, 0.0, error=True),  # errored
        _agent("academic_agent", 60.0, 0.6),
    ]
    score = compute_weighted_score(outputs)
    # Only semantic (0.30) and academic (0.25) contribute
    # Normalised: sem = 0.30/0.55 ≈ 0.5455, acad = 0.25/0.55 ≈ 0.4545
    expected = round(80.0 * (0.30 / 0.55) + 60.0 * (0.25 / 0.55), 2)
    assert score == expected


def test_weighted_score_empty() -> None:
    assert compute_weighted_score([]) == 0.0


def test_weighted_score_unknown_agent() -> None:
    """Unknown agent names get weight 0 → excluded."""
    outputs = [_agent("unknown_agent", 99.0, 0.9)]
    assert compute_weighted_score(outputs) == 0.0


# ---------------------------------------------------------------------------
# merge_flagged_passages
# ---------------------------------------------------------------------------

def test_merge_deduplicates() -> None:
    fp = FlaggedPassage(text="same text here", similarity_score=0.9, reason="dup")
    outputs = [
        AgentOutput(agent_name="a", score=10, confidence=0.5, flagged_passages=[fp]),
        AgentOutput(agent_name="b", score=20, confidence=0.6, flagged_passages=[fp]),
    ]
    merged = merge_flagged_passages(outputs)
    assert len(merged) == 1


def test_merge_respects_max() -> None:
    passages = [
        FlaggedPassage(text=f"passage {i}", similarity_score=0.5, reason="t")
        for i in range(10)
    ]
    outputs = [AgentOutput(agent_name="a", score=10, confidence=0.5, flagged_passages=passages)]
    merged = merge_flagged_passages(outputs, max_passages=3)
    assert len(merged) == 3


def test_merge_sorted_by_similarity() -> None:
    fp_low = FlaggedPassage(text="low", similarity_score=0.3, reason="")
    fp_high = FlaggedPassage(text="high", similarity_score=0.95, reason="")
    outputs = [
        AgentOutput(agent_name="a", score=10, confidence=0.5, flagged_passages=[fp_low, fp_high]),
    ]
    merged = merge_flagged_passages(outputs)
    assert merged[0].similarity_score == 0.95


# ---------------------------------------------------------------------------
# get_agent_weight
# ---------------------------------------------------------------------------

def test_known_agent_weights() -> None:
    assert get_agent_weight("semantic_agent") == 0.30
    assert get_agent_weight("web_search_agent") == 0.25
    assert get_agent_weight("academic_agent") == 0.25
    assert get_agent_weight("ai_detection_agent") == 0.20


def test_unknown_agent_weight() -> None:
    assert get_agent_weight("nonexistent") == 0.0
