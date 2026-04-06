"""Content extractor tool — extracts text from PDF, DOCX, TXT, and LaTeX files.

Standalone, framework-agnostic tool. Returns structured JSON.
Also provides text chunking functionality.
"""

from __future__ import annotations

import re
import time
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from pptx import Presentation
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
        ".tex": _extract_from_latex,
        ".pptx": _extract_from_pptx,
    }

    extractor = extractors.get(ext)
    if extractor is None:
        raise ValueError(f"Unsupported file type: {ext}")

    logger.info("extracting_text", filename=filename, file_type=ext)
    import asyncio
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, extractor, file_bytes)

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
    # Primary: pdfplumber (much better at preserving spaces)
    try:
        import pdfplumber
        pages: list[str] = []
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
        text = "\n".join(pages)
        if text.strip():
            return _fix_pdf_spacing(text)
    except Exception:
        logger.warning("pdfplumber_failed_falling_back_to_pypdf2")

    # Fallback: PyPDF2
    reader = PdfReader(BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            pages.append(page_text)
    return _fix_pdf_spacing("\n".join(pages))


def _fix_pdf_spacing(text: str) -> str:
    """Post-process extracted PDF text to restore missing spaces."""
    # Insert space between a lowercase letter and an uppercase letter (camelCase joins)
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # Insert space between a letter and an opening paren
    text = re.sub(r'([a-zA-Z])\(', r'\1 (', text)
    # Insert space between a closing paren/period/comma and a letter (no space after punctuation)
    text = re.sub(r'([.,;:)])([a-zA-Z])', r'\1 \2', text)
    # Insert space between a digit and a letter (but not inside known patterns like "3D")
    text = re.sub(r'(\d)([a-zA-Z]{2,})', r'\1 \2', text)
    # Collapse multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    return text


def _extract_from_docx(file_bytes: bytes) -> str:
    doc = DocxDocument(BytesIO(file_bytes))
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def _extract_from_txt(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace")


def _extract_from_pptx(file_bytes: bytes) -> str:
    """Extract text from a PowerPoint (.pptx) file."""
    prs = Presentation(BytesIO(file_bytes))
    slides_text: list[str] = []
    for slide in prs.slides:
        parts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = paragraph.text.strip()
                    if text:
                        parts.append(text)
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        text = cell.text.strip()
                        if text:
                            parts.append(text)
        if parts:
            slides_text.append("\n".join(parts))
    return "\n\n".join(slides_text)


def _extract_from_latex(file_bytes: bytes) -> str:
    """Extract plain text from a LaTeX (.tex) file by stripping commands."""
    raw = file_bytes.decode("utf-8", errors="replace")

    # Remove comments (lines starting with %)
    raw = re.sub(r"(?m)%.*$", "", raw)

    # Remove common preamble commands
    raw = re.sub(r"\\documentclass(\[.*?\])?\{.*?\}", "", raw)
    raw = re.sub(r"\\usepackage(\[.*?\])?\{.*?\}", "", raw)
    raw = re.sub(r"\\(begin|end)\{(document|abstract|figure|table|equation|align|itemize|enumerate|description|thebibliography|verbatim|lstlisting|tabular|array)\}", "", raw)

    # Remove label, ref, cite kept as text: [AuthorYear] style
    raw = re.sub(r"\\label\{[^}]*\}", "", raw)
    raw = re.sub(r"\\(ref|eqref|pageref)\{[^}]*\}", "[ref]", raw)
    raw = re.sub(r"\\(cite|citep|citet|parencite|textcite|autocite)(\[[^\]]*\])?\{([^}]*)\}", r"[\3]", raw)

    # Preserve text from formatting commands
    raw = re.sub(r"\\(textbf|textit|emph|underline|texttt|textrm|textsf|textsc)\{([^}]*)\}", r"\2", raw)
    raw = re.sub(r"\\(title|author|date|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\{([^}]*)\}", r"\2", raw)
    raw = re.sub(r"\\(footnote|footnotetext)\{([^}]*)\}", r" \2", raw)
    raw = re.sub(r"\\caption\{([^}]*)\}", r"\1", raw)

    # Remove math environments but keep simple inline math text
    raw = re.sub(r"\$\$.*?\$\$", " [equation] ", raw, flags=re.DOTALL)
    raw = re.sub(r"\$([^$]+)\$", r"\1", raw)
    raw = re.sub(r"\\begin\{(equation|align|gather|multline)\*?\}.*?\\end\{\1\*?\}", " [equation] ", raw, flags=re.DOTALL)

    # Remove remaining LaTeX commands but keep their text arguments
    raw = re.sub(r"\\[a-zA-Z]+\*?(\{[^}]*\})?", "", raw)

    # Clean up braces and special chars
    raw = raw.replace("{", "").replace("}", "")
    raw = raw.replace("~", " ").replace("``", '"').replace("''", '"')
    raw = re.sub(r"\\[&%$#_]", "", raw)

    # Normalise whitespace
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)

    return raw.strip()


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
