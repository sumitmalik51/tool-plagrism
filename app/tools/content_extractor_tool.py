"""Content extractor tool — extracts text from PDF, DOCX, and TXT files.

Standalone, framework-agnostic tool. Returns structured JSON.
Also provides text chunking functionality.
"""

from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from PyPDF2 import PdfReader

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def extract_text(file_bytes: bytes, filename: str) -> dict:
    """Extract text content from an uploaded file.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename: Original filename (used to determine type).

    Returns:
        Dict with ``filename``, ``file_type``, ``text``, ``char_count``, ``elapsed_s``.

    Raises:
        ValueError: If the file type is unsupported or extraction fails.
    """
    ext = Path(filename).suffix.lower()
    start = time.perf_counter()

    extractors: dict[str, callable] = {
        ".pdf": _extract_from_pdf,
        ".docx": _extract_from_docx,
        ".txt": _extract_from_txt,
    }

    extractor = extractors.get(ext)
    if extractor is None:
        raise ValueError(f"Unsupported file type: {ext}")

    logger.info("extracting_text", filename=filename, file_type=ext)
    text = extractor(file_bytes)

    if not text.strip():
        raise ValueError("Extracted text is empty — the file may be scanned or corrupt.")

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "extraction_complete",
        filename=filename,
        char_count=len(text),
        elapsed_s=elapsed,
    )

    return {
        "filename": filename,
        "file_type": ext.lstrip("."),
        "text": text,
        "char_count": len(text),
        "elapsed_s": elapsed,
    }


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> dict:
    """Split text into overlapping chunks.

    Uses sentence-boundary-aware splitting.

    Args:
        text: The full document text.
        chunk_size: Target chars per chunk (default from settings).
        overlap: Overlap chars between chunks (default from settings).

    Returns:
        Dict with ``chunks``, ``chunk_count``, ``chunk_size``, ``overlap``.
    """
    if chunk_size is None:
        chunk_size = settings.chunk_size
    if overlap is None:
        overlap = settings.chunk_overlap

    start = time.perf_counter()
    text = text.strip()

    if not text:
        return {"chunks": [], "chunk_count": 0, "chunk_size": chunk_size, "overlap": overlap}

    if len(text) <= chunk_size:
        return {"chunks": [text], "chunk_count": 1, "chunk_size": chunk_size, "overlap": overlap}

    chunks: list[str] = []
    pos = 0

    while pos < len(text):
        end = pos + chunk_size

        if end < len(text):
            boundary = _find_sentence_boundary(text, pos, end)
            if boundary > pos:
                end = boundary

        chunk = text[pos:end].strip()
        if chunk:
            chunks.append(chunk)

        step = max(end - pos - overlap, 1)
        pos += step

        # Align to word boundary — never start a chunk mid-word
        if 0 < pos < len(text) and not text[pos - 1].isspace():
            scan_start = pos
            while pos < len(text) and not text[pos].isspace():
                pos += 1
            # Skip past the whitespace to the first char of the next word
            while pos < len(text) and text[pos].isspace():
                pos += 1
            # Safety: revert if we had to skip more than 50 chars
            if pos - scan_start > 50:
                pos = scan_start

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "text_chunked",
        total_chunks=len(chunks),
        chunk_size=chunk_size,
        overlap=overlap,
        elapsed_s=elapsed,
    )

    return {
        "chunks": chunks,
        "chunk_count": len(chunks),
        "chunk_size": chunk_size,
        "overlap": overlap,
        "elapsed_s": elapsed,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    pages: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            pages.append(page_text)
    return "\n".join(pages)


def _extract_from_docx(file_bytes: bytes) -> str:
    doc = DocxDocument(BytesIO(file_bytes))
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def _extract_from_txt(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace")


def _find_sentence_boundary(text: str, start: int, end: int) -> int:
    """Find position just after the last sentence-ending char in [start, end)."""
    best = start
    for sep in (".\n", "\n\n", ". ", ".\t"):
        pos = text.rfind(sep, start, end)
        if pos != -1:
            candidate = pos + len(sep)
            if candidate > best:
                best = candidate
    if best == start:
        pos = text.rfind(".", start, end)
        if pos != -1:
            best = pos + 1
    return best
