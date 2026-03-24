"""Tests for citation stripper — citation-aware preprocessing."""

import pytest
from app.tools.citation_stripper import (
    strip_reference_section,
    strip_inline_citations,
    prepare_text_for_scanning,
)


class TestStripReferenceSection:
    """Tests for removing reference/bibliography sections."""

    def test_removes_references_section_at_end(self):
        text = (
            "This is the main body of the paper. " * 20
            + "\n\nReferences\n\n[1] Author A. Title. 2020.\n[2] Author B. Title2. 2021."
        )
        cleaned, removed = strip_reference_section(text)
        assert "References" not in cleaned
        assert "[1] Author A" in removed

    def test_removes_bibliography_section(self):
        text = (
            "Main content of the document with many words. " * 20
            + "\n\nBibliography\n\nSmith, J. (2020). A paper.\nDoe, J. (2021). Another paper."
        )
        cleaned, removed = strip_reference_section(text)
        assert "Bibliography" not in cleaned
        assert "Smith, J" in removed

    def test_does_not_strip_references_in_middle(self):
        # Reference section in the first 50% of text — should NOT be stripped
        text = (
            "\n\nReferences\n\n[1] Early ref.\n\n"
            + "This is the second half of the paper with lots of content. " * 30
        )
        cleaned, removed = strip_reference_section(text)
        assert removed == ""
        assert "References" in cleaned

    def test_no_references_section(self):
        text = "This paper has no references section at all." * 10
        cleaned, removed = strip_reference_section(text)
        assert cleaned == text
        assert removed == ""


class TestStripInlineCitations:
    """Tests for removing inline citation markers."""

    def test_bracket_numbered_citations(self):
        text = "Neural networks [1] have been widely studied [2, 3] in recent years."
        result = strip_inline_citations(text)
        assert "[1]" not in result
        assert "[2, 3]" not in result
        assert "Neural networks" in result
        assert "have been widely studied" in result

    def test_bracket_range_citations(self):
        text = "Previous work [1-3] supports this claim."
        result = strip_inline_citations(text)
        assert "[1-3]" not in result
        assert "Previous work" in result

    def test_parenthetical_apa_citations(self):
        text = "Studies (Smith, 2020) have shown that (Doe et al., 2021) results vary."
        result = strip_inline_citations(text)
        assert "(Smith, 2020)" not in result
        assert "(Doe et al., 2021)" not in result
        assert "Studies" in result
        assert "have shown that" in result

    def test_preserves_non_citation_brackets(self):
        text = "The array [index] contains data."
        result = strip_inline_citations(text)
        # Simple variable names shouldn't be stripped
        assert "array" in result

    def test_no_double_spaces(self):
        text = "Some text [1] with [2] citations [3] everywhere."
        result = strip_inline_citations(text)
        assert "  " not in result


class TestPrepareTextForScanning:
    """Tests for the full preprocessing pipeline."""

    def test_returns_cleaned_text_and_metadata(self):
        text = (
            "Main body content. " * 30
            + "\n\nReferences\n\n[1] Author. Title. 2020."
        )
        cleaned, meta = prepare_text_for_scanning(text)
        assert meta["reference_section_removed"] is True
        assert meta["chars_removed"] > 0
        assert len(cleaned) < len(text)
        assert "original_length" in meta
        assert "cleaned_length" in meta

    def test_short_text_unchanged(self):
        text = "Short text with no refs."
        cleaned, meta = prepare_text_for_scanning(text)
        assert cleaned == text
        assert meta["reference_section_removed"] is False
        assert meta["chars_removed"] == 0
