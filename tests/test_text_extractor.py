"""Tests for the text extraction service."""

from __future__ import annotations

import pytest

from app.services.text_extractor import extract_text


@pytest.mark.asyncio
async def test_extract_txt() -> None:
    """Should extract text from a plain-text file."""
    content = b"Hello, this is a test document."
    result = await extract_text(content, "test.txt")
    assert result == "Hello, this is a test document."


@pytest.mark.asyncio
async def test_extract_unsupported_type() -> None:
    """Should raise ValueError for unsupported file types."""
    with pytest.raises(ValueError, match="Unsupported file type"):
        await extract_text(b"data", "file.csv")


@pytest.mark.asyncio
async def test_extract_empty_txt() -> None:
    """Should raise ValueError when extracted text is empty."""
    with pytest.raises(ValueError, match="empty"):
        await extract_text(b"   ", "blank.txt")
