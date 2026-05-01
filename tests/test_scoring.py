"""Tests for the scoring service (weighted aggregation)."""

from __future__ import annotations

from app.models.schemas import AgentOutput
from app.services.scoring import (
    compute_weighted_score,
    merge_flagged_passages,
    get_agent_weight,
    _is_citation_metadata,
    _trim_leading_fragment,
)
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
    outputs = [_agent("web_search_agent", 80.0, 0.9)]
    assert compute_weighted_score(outputs) == 80.0


def test_weighted_score_all_agents_equal() -> None:
    """When all scored agents agree, the weighted score equals the common score."""
    outputs = [
        _agent("web_search_agent", 50.0, 0.7),
        _agent("academic_agent", 50.0, 0.6),
        _agent("ai_detection_agent", 50.0, 0.9),
    ]
    assert compute_weighted_score(outputs) == 50.0


def test_weighted_score_mixed() -> None:
    """Different scores should produce a weighted average."""
    outputs = [
        _agent("web_search_agent", 60.0, 0.7),     # w=0.35
        _agent("academic_agent", 40.0, 0.6),        # w=0.35
        _agent("ai_detection_agent", 20.0, 0.5),    # w=0.30
    ]
    score = compute_weighted_score(outputs)
    # Manual: (60*0.35 + 40*0.35 + 20*0.30) / 1.0 = 21+14+6 = 41
    assert score == 41.0


def test_weighted_score_excludes_errored_agents() -> None:
    """Errored agents should be excluded; their weight redistributed."""
    outputs = [
        _agent("web_search_agent", 80.0, 0.9),
        _agent("academic_agent", 0.0, 0.0, error=True),  # errored
        _agent("ai_detection_agent", 60.0, 0.6),
    ]
    score = compute_weighted_score(outputs)
    # Only web_search (0.35) and ai_detection (0.30) contribute
    # Normalised: web = 0.35/0.65, ai = 0.30/0.65
    expected = round(80.0 * (0.35 / 0.65) + 60.0 * (0.30 / 0.65), 2)
    assert score == expected


def test_weighted_score_empty() -> None:
    assert compute_weighted_score([]) == 0.0


def test_weighted_score_semantic_excluded() -> None:
    """Semantic agent (weight 0) should be excluded from score."""
    outputs = [_agent("semantic_agent", 99.0, 0.9)]
    assert compute_weighted_score(outputs) == 0.0


def test_weighted_score_unknown_agent() -> None:
    """Unknown agent names get weight 0 → excluded."""
    outputs = [_agent("unknown_agent", 99.0, 0.9)]
    assert compute_weighted_score(outputs) == 0.0


# ---------------------------------------------------------------------------
# merge_flagged_passages
# ---------------------------------------------------------------------------

def test_merge_deduplicates() -> None:
    fp = FlaggedPassage(text="The same duplicated text passage appears here as well", similarity_score=0.9, reason="dup")
    outputs = [
        AgentOutput(agent_name="a", score=10, confidence=0.5, flagged_passages=[fp]),
        AgentOutput(agent_name="b", score=20, confidence=0.6, flagged_passages=[fp]),
    ]
    merged = merge_flagged_passages(outputs)
    assert len(merged) == 1


def test_merge_excludes_internal_chunk_passages() -> None:
    """Passages with internal_chunk_ sources should be excluded entirely."""
    fp_internal = FlaggedPassage(
        text="This is an internal duplication passage detected by semantic agent",
        similarity_score=0.95,
        source="internal_chunk_42",
        reason="internal duplication",
    )
    fp_web = FlaggedPassage(
        text="This web passage was matched against an external source online",
        similarity_score=0.80,
        source="http://example.com/article",
        reason="web match",
    )
    outputs = [
        AgentOutput(agent_name="semantic_agent", score=80, confidence=0.9, flagged_passages=[fp_internal]),
        AgentOutput(agent_name="web_search_agent", score=50, confidence=0.7, flagged_passages=[fp_web]),
    ]
    merged = merge_flagged_passages(outputs)
    assert len(merged) == 1
    assert merged[0].source == "http://example.com/article"


def test_merge_respects_max() -> None:
    passages = [
        FlaggedPassage(text=f"This is test passage number {i} with enough words to pass filter", similarity_score=0.5, reason="t")
        for i in range(10)
    ]
    outputs = [AgentOutput(agent_name="a", score=10, confidence=0.5, flagged_passages=passages)]
    merged = merge_flagged_passages(outputs, max_passages=3)
    assert len(merged) == 3


def test_merge_sorted_by_similarity() -> None:
    fp_low = FlaggedPassage(text="This passage has a lower similarity score overall", similarity_score=0.3, reason="")
    fp_high = FlaggedPassage(text="This passage has a much higher similarity score detected", similarity_score=0.95, reason="")
    outputs = [
        AgentOutput(agent_name="a", score=10, confidence=0.5, flagged_passages=[fp_low, fp_high]),
    ]
    merged = merge_flagged_passages(outputs)
    assert merged[0].similarity_score == 0.95


def test_merge_filters_short_fragments() -> None:
    """Fragments shorter than min thresholds should be excluded."""
    fp_short = FlaggedPassage(text="vs.", similarity_score=1.0, reason="too short")
    fp_ok = FlaggedPassage(
        text="The photovoltaic parameters of flexible solar cells were measured under standard conditions with variable illumination",
        similarity_score=0.85,
        reason="real match",
    )
    outputs = [
        AgentOutput(agent_name="a", score=50, confidence=0.8, flagged_passages=[fp_short, fp_ok]),
    ]
    merged = merge_flagged_passages(outputs)
    assert len(merged) == 1
    assert merged[0].text == fp_ok.text


def test_merge_filters_two_word_fragments() -> None:
    """Fragments with fewer than 3 words are excluded even if chars >= threshold."""
    fp_few_words = FlaggedPassage(text="Non-Flexible vs.", similarity_score=1.0, reason="")
    outputs = [
        AgentOutput(agent_name="a", score=10, confidence=0.5, flagged_passages=[fp_few_words]),
    ]
    merged = merge_flagged_passages(outputs)
    assert len(merged) == 0


def test_merge_filters_citation_metadata() -> None:
    """Passages with 2+ citation metadata indicators (emails, dates) are excluded."""
    citation = FlaggedPassage(
        text=(
            "Mohammad-Reza Zamani-Meymian *, Saeb Sheikholeslami and Milad Fallah "
            "School of Physics, Iran University; sheikholeslami@physics.iust.ac.ir (S.S.); "
            "mfallah@live.com (M.F.) *Correspondence: r_zamani@iust.ac.ir "
            "Received: 21 May 2020; Accepted: 2 July 2020; Published: 9 July 2020"
        ),
        similarity_score=0.82,
        reason="web match",
    )
    normal = FlaggedPassage(
        text="The as-deposited thin film was annealed in the atmosphere at 100C for 10 min to prepare it.",
        similarity_score=0.80,
        reason="web match",
    )
    outputs = [
        AgentOutput(agent_name="a", score=50, confidence=0.8, flagged_passages=[citation, normal]),
    ]
    merged = merge_flagged_passages(outputs)
    assert len(merged) == 1
    assert merged[0].text == normal.text


def test_merge_trims_leading_fragment() -> None:
    """Leading partial-word artefacts from chunk splits are trimmed."""
    fp = FlaggedPassage(
        text="rticle The stability of non-flexible inverted bulk-heterojunction organic solar cells was investigated under thermal stress conditions",
        similarity_score=0.82,
        reason="internal dup",
    )
    outputs = [
        AgentOutput(agent_name="a", score=50, confidence=0.8, flagged_passages=[fp]),
    ]
    merged = merge_flagged_passages(outputs)
    assert len(merged) == 1
    assert merged[0].text.startswith("The stability of non-flexible")


def test_trim_leading_fragment_no_op() -> None:
    """Text starting with a proper word is not trimmed."""
    assert _trim_leading_fragment("Article Stability of") == "Article Stability of"
    assert _trim_leading_fragment("The quick brown fox") == "The quick brown fox"


def test_trim_leading_fragment_trims() -> None:
    """Lowercase-only leading words up to 10 chars are trimmed when followed by uppercase."""
    assert _trim_leading_fragment("rticle Stability") == "Stability"
    assert _trim_leading_fragment("e Stability of") == "Stability of"
    assert _trim_leading_fragment("y Stirred for 60") == "Stirred for 60"


def test_trim_leading_fragment_preserves_lowercase_words() -> None:
    """Legitimate lowercase words (not followed by uppercase) are NOT trimmed."""
    assert _trim_leading_fragment("photovoltaic parameters") == "photovoltaic parameters"
    assert _trim_leading_fragment("stirred for 60 min") == "stirred for 60 min"


def test_is_citation_metadata_true() -> None:
    text = "author@university.edu *Correspondence: Received: 21 May 2020; test@test.com"
    assert _is_citation_metadata(text) is True


def test_is_citation_metadata_false() -> None:
    text = "The thin film was annealed in the atmosphere at 100 degrees for 10 minutes."
    assert _is_citation_metadata(text) is False


# ---------------------------------------------------------------------------
# get_agent_weight
# ---------------------------------------------------------------------------

def test_known_agent_weights() -> None:
    assert get_agent_weight("semantic_agent") == 0.0
    assert get_agent_weight("web_search_agent") == 0.35
    assert get_agent_weight("academic_agent") == 0.35
    assert get_agent_weight("ai_detection_agent") == 0.30


def test_unknown_agent_weight() -> None:
    assert get_agent_weight("nonexistent") == 0.0
