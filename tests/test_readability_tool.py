"""Tests for the readability analyzer tool."""

from __future__ import annotations

import pytest

from app.tools.readability_tool import analyze_readability, _count_syllables


class TestSyllableCount:
    """Test the syllable counting heuristic."""

    def test_simple_words(self):
        assert _count_syllables("the") == 1
        assert _count_syllables("cat") == 1
        assert _count_syllables("hello") == 2

    def test_complex_words(self):
        assert _count_syllables("university") >= 4
        assert _count_syllables("beautiful") >= 3

    def test_empty_or_short(self):
        assert _count_syllables("a") == 1
        assert _count_syllables("I") == 1
        assert _count_syllables("") == 1


class TestAnalyzeReadability:
    """Test the readability analyzer."""

    def test_empty_text(self):
        result = analyze_readability("")
        assert result["level"] == "N/A"
        assert result["elapsed_s"] == 0.0

    def test_simple_text(self):
        text = "The cat sat on the mat. The dog ran fast. It was a sunny day."
        result = analyze_readability(text)

        assert "scores" in result
        assert "statistics" in result
        assert "reading_time" in result
        assert "level" in result
        assert result["elapsed_s"] >= 0

        scores = result["scores"]
        assert "flesch_reading_ease" in scores
        assert "flesch_kincaid_grade" in scores
        assert "gunning_fog" in scores
        assert "coleman_liau" in scores
        assert "automated_readability_index" in scores
        assert "average_grade_level" in scores

    def test_statistics(self):
        text = "One sentence here. Another sentence there. A third one too."
        result = analyze_readability(text)

        stats = result["statistics"]
        assert stats["word_count"] > 0
        assert stats["sentence_count"] >= 3
        assert stats["avg_sentence_length"] > 0
        assert stats["vocabulary_diversity"] > 0
        assert stats["vocabulary_diversity"] <= 1.0

    def test_reading_time_increases_with_length(self):
        short = analyze_readability("Hello world. Short text.")
        long_text = " ".join(["The quick brown fox jumps over the lazy dog."] * 100)
        long_result = analyze_readability(long_text)

        assert long_result["reading_time"]["minutes"] > short["reading_time"]["minutes"]

    def test_complex_text_higher_grade(self):
        simple = "The cat sat. The dog ran. It was fun."
        complex_text = (
            "The epistemological implications of contemporary quantum mechanics "
            "necessitate a fundamental reconceptualization of our understanding "
            "of empirical observation and phenomenological experience. "
            "Furthermore, the methodological considerations inherent in "
            "interdisciplinary research paradigms require comprehensive "
            "analytical frameworks."
        )
        simple_result = analyze_readability(simple)
        complex_result = analyze_readability(complex_text)

        # Complex text should have higher grade level
        assert complex_result["scores"]["average_grade_level"] > simple_result["scores"]["average_grade_level"]

    def test_level_labels(self):
        result = analyze_readability("Simple words. Short text. Easy read.")
        assert result["level"] in [
            "Elementary", "Middle School", "High School", "College", "Graduate"
        ]
