"""Tests for the BibTeX export tool."""

from __future__ import annotations

from app.tools.bibtex_tool import (
    paper_to_bibtex,
    papers_to_bibtex,
    _sanitize_key,
    _escape_bibtex,
)


# ---------------------------------------------------------------------------
# _sanitize_key
# ---------------------------------------------------------------------------

def test_sanitize_key_basic() -> None:
    assert _sanitize_key("Smith2024Deep") == "Smith2024Deep"


def test_sanitize_key_special_chars() -> None:
    assert _sanitize_key("O'Brien (2024)") == "OBrien2024"


def test_sanitize_key_unicode() -> None:
    result = _sanitize_key("Müller2024Über")
    assert result.isascii()
    assert "ller" in result


def test_sanitize_key_empty() -> None:
    assert _sanitize_key("") == "unknown"


def test_sanitize_key_truncation() -> None:
    long = "A" * 100
    assert len(_sanitize_key(long)) == 40


# ---------------------------------------------------------------------------
# _escape_bibtex
# ---------------------------------------------------------------------------

def test_escape_bibtex_ampersand() -> None:
    assert _escape_bibtex("A & B") == r"A \& B"


def test_escape_bibtex_percent() -> None:
    assert _escape_bibtex("50% accuracy") == r"50\% accuracy"


def test_escape_bibtex_dollar() -> None:
    assert _escape_bibtex("$100") == r"\$100"


def test_escape_bibtex_clean_text() -> None:
    assert _escape_bibtex("Normal text here") == "Normal text here"


# ---------------------------------------------------------------------------
# paper_to_bibtex
# ---------------------------------------------------------------------------

def test_paper_to_bibtex_full() -> None:
    paper = {
        "title": "Deep Learning for NLP",
        "authors": ["Alice Smith", "Bob Jones"],
        "year": "2024",
        "abstract": "A study of deep learning applied to NLP tasks.",
        "url": "https://doi.org/10.1234/example",
        "venue": "Nature AI",
    }
    bib = paper_to_bibtex(paper)

    assert "@article{" in bib
    assert "Deep Learning for NLP" in bib
    assert "Smith, Alice" in bib
    assert "Jones, Bob" in bib
    assert "year = {2024}" in bib
    assert "journal = {Nature AI}" in bib
    assert "url = {https://doi.org/10.1234/example}" in bib


def test_paper_to_bibtex_arxiv() -> None:
    paper = {
        "title": "Vision Transformers",
        "authors": ["Charlie Brown"],
        "year": "2023",
        "arxiv_id": "2301.12345",
        "venue": "arXiv (cs.CV)",
    }
    bib = paper_to_bibtex(paper)

    assert "@misc{" in bib
    assert "eprint = {2301.12345}" in bib
    assert "archiveprefix = {arXiv}" in bib


def test_paper_to_bibtex_no_authors() -> None:
    paper = {"title": "Anonymous Work", "year": "2022"}
    bib = paper_to_bibtex(paper)
    assert "author = {Unknown}" in bib


def test_paper_to_bibtex_empty_title() -> None:
    paper = {"title": "", "authors": []}
    bib = paper_to_bibtex(paper)
    # Empty title uses default "Untitled" but it gets sanitized in the key
    # The entry should still be valid BibTeX
    assert "@" in bib
    assert "author" in bib


def test_paper_to_bibtex_doi_field() -> None:
    paper = {
        "title": "Test Paper",
        "authors": ["Test Author"],
        "doi": "https://doi.org/10.1000/test",
    }
    bib = paper_to_bibtex(paper)
    assert "doi = {10.1000/test}" in bib


# ---------------------------------------------------------------------------
# papers_to_bibtex
# ---------------------------------------------------------------------------

def test_papers_to_bibtex_multiple() -> None:
    papers = [
        {"title": "Paper A", "authors": ["Author A"], "year": "2023"},
        {"title": "Paper B", "authors": ["Author B"], "year": "2024"},
    ]
    bib = papers_to_bibtex(papers)

    assert bib.count("@") == 2
    assert "Paper A" in bib
    assert "Paper B" in bib


def test_papers_to_bibtex_empty() -> None:
    assert papers_to_bibtex([]) == ""


def test_papers_to_bibtex_dedup_keys() -> None:
    """Papers that would produce the same key should get unique keys."""
    papers = [
        {"title": "Deep Study", "authors": ["Smith"], "year": "2024"},
        {"title": "Deep Study", "authors": ["Smith"], "year": "2024"},
    ]
    bib = papers_to_bibtex(papers)

    # Both entries should exist with different keys
    assert bib.count("@") == 2
    # Keys should be unique — extract them
    import re
    keys = re.findall(r"@\w+\{(\w+),", bib)
    assert len(keys) == 2
    assert keys[0] != keys[1]


def test_papers_to_bibtex_special_chars_in_title() -> None:
    papers = [
        {"title": "50% Accuracy & Beyond", "authors": ["Test"], "year": "2024"},
    ]
    bib = papers_to_bibtex(papers)
    assert r"50\% Accuracy \& Beyond" in bib
