"""Tests for advanced analysis features: section splitting, reference validation,
cross-document comparison, and progress tracking."""

from __future__ import annotations

import asyncio
import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Section Splitter Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSectionSplitter:
    """Test section detection and splitting in academic papers."""

    def test_numbered_sections(self):
        from app.tools.section_splitter import split_into_sections

        text = """Abstract

This paper discusses AI detection.

1. Introduction

Machine learning has transformed many fields. We explore detection methods.

2. Background

Previous work by Smith et al. established foundational approaches.

2.1 Related Work

Several studies have examined this problem.

3. Methodology

We propose a novel approach using embeddings.

4. Results

Our method achieves 95% accuracy on the benchmark.

5. Conclusion

We presented a new detection method with promising results."""

        sections = split_into_sections(text)
        assert len(sections) >= 4
        titles = [s["title"] for s in sections]
        # Should detect numbered headings
        assert any("Introduction" in t for t in titles)
        assert any("Methodology" in t or "Methods" in t for t in titles)
        assert all(s["word_count"] > 0 for s in sections)

    def test_all_caps_sections(self):
        from app.tools.section_splitter import split_into_sections

        text = """ABSTRACT

This paper explores plagiarism detection using AI techniques.

INTRODUCTION

Plagiarism is a growing concern in academic publishing.

METHODS

We developed a multi-agent detection system.

RESULTS

The system achieved high accuracy scores.

CONCLUSION

Our approach demonstrates effective detection."""

        sections = split_into_sections(text)
        assert len(sections) >= 3
        titles = [s["title"] for s in sections]
        assert any("ABSTRACT" in t for t in titles)
        assert any("INTRODUCTION" in t for t in titles)

    def test_short_text_no_sections(self):
        from app.tools.section_splitter import split_into_sections

        text = "This is a very short text without any sections."
        sections = split_into_sections(text)
        assert len(sections) == 1
        assert sections[0]["title"] == "Full Document"

    def test_latex_sections(self):
        from app.tools.section_splitter import split_into_sections

        text = r"""\section{Introduction}

This paper presents our findings on plagiarism detection.

\section{Methodology}

We employ a multi-agent approach using embedding similarity.

\subsection{Data Collection}

Data was collected from academic repositories.

\section{Results}

Our system achieves 92% accuracy."""

        sections = split_into_sections(text)
        assert len(sections) >= 3
        titles = [s["title"] for s in sections]
        assert any("Introduction" in t for t in titles)
        assert any("Methodology" in t for t in titles)

    def test_section_word_counts_positive(self):
        from app.tools.section_splitter import split_into_sections

        text = """1. Introduction

This is the introduction section with several words to count.

2. Methods

This is the methods section also containing multiple words."""

        sections = split_into_sections(text)
        for s in sections:
            assert s["word_count"] > 0
            assert s["start_char"] >= 0
            assert s["end_char"] > s["start_char"]


# ═══════════════════════════════════════════════════════════════════════════
# Reference Validator Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestReferenceExtractor:
    """Test reference extraction from academic text."""

    def test_numbered_references(self):
        from app.tools.reference_validator import extract_references

        text = """
[1] Smith, J. and Jones, K. (2020). "Deep learning for text analysis." Journal of AI, 15(3), 45-67.
[2] Doe, A. (2019). Machine learning applications. Springer. doi: 10.1234/ml.2019.001
[3] Brown, B. et al. (2021). A survey of NLP methods. IEEE Trans., 8(2), 100-115.
"""
        refs = extract_references(text)
        assert len(refs) == 3
        assert refs[0]["number"] == 1
        assert refs[1]["doi"] is not None
        assert "10.1234" in refs[1]["doi"]
        assert refs[2]["year"] == "2021"

    def test_apa_references(self):
        from app.tools.reference_validator import extract_references

        text = """
Smith, J. A. (2020). Deep learning for plagiarism detection. Journal of AI Research, 15(3), 45-67.
Doe, A. B. (2019). Machine learning in education. Springer Publishing.
"""
        refs = extract_references(text)
        assert len(refs) >= 1
        # Should extract year
        assert any(r.get("year") == "2020" for r in refs)

    def test_no_references(self):
        from app.tools.reference_validator import extract_references

        text = "This is just a regular paragraph with no references at all."
        refs = extract_references(text)
        assert len(refs) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Progress Tracking Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestScanProgress:
    """Test the in-memory progress tracking system."""

    def test_create_and_emit(self):
        from app.services.progress import get_or_create

        tracker = get_or_create("test-doc-1")
        tracker.emit("start", "Starting scan", 0)
        tracker.emit("chunking", "Splitting text", 20)

        assert len(tracker.events) == 2
        assert tracker.events[0].stage == "start"
        assert tracker.events[1].percent == 20
        assert not tracker.is_completed

    def test_complete(self):
        from app.services.progress import get_or_create

        tracker = get_or_create("test-doc-2")
        tracker.emit("start", "Starting", 0)
        tracker.complete()
        assert tracker.is_completed

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        from app.services.progress import get_or_create

        tracker = get_or_create("test-doc-3")
        queue = tracker.subscribe()

        tracker.emit("step1", "Step 1", 50)
        tracker.complete()

        # Should receive the event and then None sentinel
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event.stage == "step1"

        done = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert done is None

    @pytest.mark.asyncio
    async def test_subscribe_replays_existing(self):
        from app.services.progress import get_or_create

        tracker = get_or_create("test-doc-4")
        tracker.emit("a", "First", 10)
        tracker.emit("b", "Second", 50)

        # Subscribe after events emitted — should replay
        queue = tracker.subscribe()
        e1 = await asyncio.wait_for(queue.get(), timeout=1.0)
        e2 = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert e1.stage == "a"
        assert e2.stage == "b"


# ═══════════════════════════════════════════════════════════════════════════
# Adaptive Query Count Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAdaptiveQueryCount:
    """Test that search query counts scale with document size."""

    def test_short_document(self):
        from app.services.orchestrator import _adaptive_query_count
        web_q, scholar_q = _adaptive_query_count(3000)
        assert web_q == 8  # default
        assert scholar_q == 8

    def test_medium_document(self):
        from app.services.orchestrator import _adaptive_query_count
        web_q, scholar_q = _adaptive_query_count(15000)
        assert web_q == 12
        assert scholar_q == 12

    def test_large_document(self):
        from app.services.orchestrator import _adaptive_query_count
        web_q, scholar_q = _adaptive_query_count(35000)
        assert web_q == 16
        assert scholar_q == 16

    def test_very_large_document(self):
        from app.services.orchestrator import _adaptive_query_count
        web_q, scholar_q = _adaptive_query_count(80000)
        assert web_q == 20
        assert scholar_q == 20
