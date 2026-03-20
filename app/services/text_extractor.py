"""Text extraction service — thin wrapper delegating to tools layer.

Preserves backward compatibility with existing code that imports from
``app.services.text_extractor``.  All logic lives in
``app.tools.content_extractor_tool``.
"""

from __future__ import annotations

from app.tools.content_extractor_tool import extract_text as _extract_text_tool


async def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract text content from an uploaded file.

    Delegates to ``app.tools.content_extractor_tool.extract_text`` and
    returns just the text string for backward compatibility.
    """
    result = await _extract_text_tool(file_bytes, filename)
    return result["text"]
