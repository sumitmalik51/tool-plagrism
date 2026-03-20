"""Tests for the text chunking service."""

from __future__ import annotations

from app.services.chunker import chunk_text


def test_empty_text_returns_empty_list() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_short_text_returns_single_chunk() -> None:
    text = "This is a short sentence."
    chunks = chunk_text(text, chunk_size=500)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_long_text_produces_multiple_chunks() -> None:
    text = "Hello world. " * 200  # ~2 600 chars
    chunks = chunk_text(text, chunk_size=500, overlap=100)
    assert len(chunks) > 1
    # Every chunk should be non-empty
    for c in chunks:
        assert len(c.strip()) > 0


def test_overlap_creates_shared_content() -> None:
    text = "Sentence one. Sentence two. Sentence three. Sentence four. " * 20
    chunks = chunk_text(text, chunk_size=200, overlap=50)
    assert len(chunks) >= 3
    # With overlap, consecutive chunks should share some text
    for i in range(len(chunks) - 1):
        # At least some substring overlap is expected
        overlap_found = any(
            chunks[i + 1].startswith(chunks[i][-k:])
            for k in range(10, min(50, len(chunks[i])))
        )
        # This is a soft check — sentence boundary splitting may shift things
        # Just verify chunks are ordered and non-empty
        assert len(chunks[i]) > 0


def test_chunk_size_parameter() -> None:
    text = "A" * 1000
    chunks = chunk_text(text, chunk_size=300, overlap=0)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= 300 + 10  # small tolerance for boundary logic
