"""Text chunking service — thin wrapper delegating to tools layer.

Preserves backward compatibility with existing code that imports from
``app.services.chunker``.  All logic lives in
``app.tools.content_extractor_tool``.
"""

from __future__ import annotations

from app.tools.content_extractor_tool import chunk_text as _chunk_text_tool


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[str]:
    """Split text into overlapping chunks.

    Delegates to ``app.tools.content_extractor_tool.chunk_text`` and
    returns just the list of chunk strings for backward compatibility.
    """
    result = _chunk_text_tool(text, chunk_size=chunk_size, overlap=overlap)
    return result["chunks"]
