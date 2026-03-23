"""Tests for the report generation service."""

from __future__ import annotations

from app.models.schemas import (
    AgentOutput,
    DetectedSource,
    FlaggedPassage,
    PlagiarismReport,
    RiskLevel,
)
from app.services.report_generator import build_report, report_to_json


def _agg_output(score: float = 55.0, confidence: float = 0.7) -> AgentOutput:
    """Build a realistic aggregation_agent output."""
    return AgentOutput(
        agent_name="aggregation_agent",
        score=score,
        confidence=confidence,
        flagged_passages=[
            FlaggedPassage(
                text="Some flagged text passage here",
                similarity_score=0.92,
                source="http://example.com/paper",
                reason="High similarity with external source",
            ),
            FlaggedPassage(
                text="Web matched passage found here",
                similarity_score=0.85,
                source="http://other-site.com/article",
                reason="Web search hit",
            ),
        ],
        details={
            "risk_level": "MEDIUM",
            "explanation": "PlagiarismGuard analysis complete.\nOverall plagiarism score: 55.0/100 (confidence: 70%).\nRisk level: MEDIUM.",
            "agent_scores": {
                "semantic_agent": {"score": 60.0, "confidence": 0.8},
                "web_search_agent": {"score": 50.0, "confidence": 0.7},
            },
        },
    )


def _detection_outputs() -> list[AgentOutput]:
    """Build minimal detection agent outputs for testing."""
    return [
        AgentOutput(
            agent_name="semantic_agent",
            score=60.0,
            confidence=0.8,
            flagged_passages=[
                FlaggedPassage(
                    text="Duplicate text found",
                    similarity_score=0.88,
                    source="http://example.com/paper",
                    reason="Semantic match",
                ),
            ],
            details={},
        ),
        AgentOutput(
            agent_name="web_search_agent",
            score=50.0,
            confidence=0.7,
            flagged_passages=[
                FlaggedPassage(
                    text="Web matched passage",
                    similarity_score=0.85,
                    source="http://other-site.com/article",
                    reason="Web search hit",
                ),
            ],
            details={
                "sources": [
                    {"url": "http://other-site.com/article", "title": "Some Article", "similarity": 0.85},
                    {"url": "http://third.com/page", "title": "Third Page", "similarity": 0.6},
                ],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

def test_build_report_returns_plagiarism_report() -> None:
    report = build_report("doc-1", _agg_output(), _detection_outputs())
    assert isinstance(report, PlagiarismReport)
    assert report.document_id == "doc-1"


def test_build_report_score_and_confidence() -> None:
    report = build_report("doc-2", _agg_output(55.0, 0.7), _detection_outputs())
    assert report.plagiarism_score == 55.0
    assert report.confidence_score == 0.7


def test_build_report_risk_level() -> None:
    report = build_report("doc-3", _agg_output(), _detection_outputs())
    assert report.risk_level == RiskLevel.MEDIUM


def test_build_report_contains_explanation() -> None:
    report = build_report("doc-4", _agg_output(), _detection_outputs())
    assert "PlagiarismGuard" in report.explanation
    assert "Report generated at" in report.explanation


def test_build_report_flagged_passages() -> None:
    report = build_report("doc-5", _agg_output(), _detection_outputs())
    assert len(report.flagged_passages) > 0
    assert report.flagged_passages[0].similarity_score > 0


def test_build_report_agent_results_preserved() -> None:
    outputs = _detection_outputs()
    report = build_report("doc-6", _agg_output(), outputs)
    assert len(report.agent_results) == len(outputs)
    names = {r.agent_name for r in report.agent_results}
    assert "semantic_agent" in names
    assert "web_search_agent" in names


def test_build_report_detected_sources() -> None:
    report = build_report("doc-7", _agg_output(), _detection_outputs())
    assert len(report.detected_sources) > 0
    urls = [s.url for s in report.detected_sources]
    assert "http://example.com/paper" in urls
    assert "http://other-site.com/article" in urls


def test_build_report_sources_only_from_flagged() -> None:
    """Sources listed in agent details but with no flagged passages should NOT appear."""
    report = build_report("doc-7b", _agg_output(), _detection_outputs())
    urls = [s.url for s in report.detected_sources]
    # http://third.com/page is only in details["sources"], no flagged passage references it
    assert "http://third.com/page" not in urls


def test_build_report_sources_have_text_blocks() -> None:
    """Each detected source should have at least 1 text block and matched words."""
    report = build_report("doc-7c", _agg_output(), _detection_outputs())
    for src in report.detected_sources:
        assert src.text_blocks > 0, f"Source {src.url} has 0 text blocks"
        assert src.matched_words > 0, f"Source {src.url} has 0 matched words"


def test_build_report_sources_deduplicated() -> None:
    """The same URL from multiple agents should appear only once."""
    report = build_report("doc-8", _agg_output(), _detection_outputs())
    urls = [s.url for s in report.detected_sources]
    assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# report_to_json
# ---------------------------------------------------------------------------

def test_report_to_json_returns_dict() -> None:
    report = build_report("doc-9", _agg_output(), _detection_outputs())
    data = report_to_json(report)
    assert isinstance(data, dict)
    assert data["document_id"] == "doc-9"


def test_report_to_json_has_all_keys() -> None:
    report = build_report("doc-10", _agg_output(), _detection_outputs())
    data = report_to_json(report)
    required_keys = {
        "document_id",
        "plagiarism_score",
        "confidence_score",
        "risk_level",
        "original_text",
        "match_groups",
        "detected_sources",
        "flagged_passages",
        "agent_results",
        "explanation",
    }
    assert required_keys.issubset(data.keys())


def test_report_to_json_risk_level_is_string() -> None:
    report = build_report("doc-11", _agg_output(), _detection_outputs())
    data = report_to_json(report)
    assert data["risk_level"] == "MEDIUM"


def test_report_to_json_sources_are_dicts() -> None:
    report = build_report("doc-12", _agg_output(), _detection_outputs())
    data = report_to_json(report)
    for src in data["detected_sources"]:
        assert isinstance(src, dict)
        assert "url" in src
        assert "similarity" in src
        assert "source_number" in src
        assert "source_type" in src
        assert "text_blocks" in src
        assert "matched_words" in src


# ---------------------------------------------------------------------------
# New fields: original_text, match_groups, enriched sources
# ---------------------------------------------------------------------------

def test_build_report_original_text() -> None:
    """original_text should be included when provided."""
    report = build_report(
        "doc-13", _agg_output(), _detection_outputs(),
        original_text="This is the original document text."
    )
    assert report.original_text == "This is the original document text."


def test_build_report_match_groups() -> None:
    """Match groups should be populated."""
    report = build_report(
        "doc-14", _agg_output(), _detection_outputs(),
        original_text="dummy text for word count"
    )
    assert len(report.match_groups) > 0
    categories = [g.category for g in report.match_groups]
    assert "Web Match" in categories


def test_build_report_source_numbers() -> None:
    """Each source should have a sequential source_number."""
    report = build_report("doc-15", _agg_output(), _detection_outputs())
    numbers = [s.source_number for s in report.detected_sources]
    assert numbers == list(range(1, len(numbers) + 1))


def test_build_report_source_type() -> None:
    """Sources from web agent should be Internet, from academic should be Publication."""
    report = build_report("doc-16", _agg_output(), _detection_outputs())
    types = {s.source_type for s in report.detected_sources}
    # Our test fixtures only have web sources (semantic_agent / web_search_agent)
    assert "Internet" in types
