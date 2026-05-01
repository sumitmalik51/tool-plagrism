"""Ingestion service — handles file upload persistence and orchestrates extraction."""

from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles

from app.config import settings
from app.services.text_extractor import extract_text
from app.utils.helpers import (
    ensure_upload_dir,
    get_upload_limit_mb,
    validate_file_extension,
    validate_file_signature,
    validate_file_size,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def ingest_file(filename: str, file_bytes: bytes, plan_type: str = "free", document_id: str | None = None) -> dict:
    """Validate, persist, and extract text from an uploaded file.

    Returns:
        A dict with ``document_id``, ``filename``, ``file_type``,
        ``text``, and ``char_count``.

    Raises:
        ValueError: On validation failure.
    """
    # --- Validation -----------------------------------------------------------
    if not validate_file_extension(filename):
        allowed = ", ".join(settings.allowed_extensions)
        raise ValueError(f"Unsupported file type. Allowed: {allowed}")

    if not validate_file_size(len(file_bytes), plan_type=plan_type):
        limit = get_upload_limit_mb(plan_type)
        raise ValueError(
            f"File exceeds maximum allowed size of {limit} MB."
        )

    # Magic-byte sniffing — reject spoofed binary formats (e.g. a .pdf whose
    # body is actually a zip) before they hit PyPDF2 / python-docx parsers,
    # both of which have a history of CVEs on malformed input.
    if not validate_file_signature(filename, file_bytes):
        ext = Path(filename).suffix.lower().lstrip(".") or "file"
        logger.warning(
            "file_signature_mismatch",
            filename=filename,
            extension=ext,
            head_hex=file_bytes[:8].hex(),
        )
        raise ValueError(
            f"Uploaded file does not appear to be a valid {ext.upper()} document."
        )

    # --- Persist file ---------------------------------------------------------
    document_id = document_id or uuid.uuid4().hex
    ext = Path(filename).suffix.lower()
    upload_dir = ensure_upload_dir()
    dest_path = upload_dir / f"{document_id}{ext}"

    async with aiofiles.open(dest_path, "wb") as f:
        await f.write(file_bytes)

    logger.info("file_persisted", document_id=document_id, path=str(dest_path))

    # --- Extract text ---------------------------------------------------------
    text = await extract_text(file_bytes, filename)

    return {
        "document_id": document_id,
        "filename": filename,
        "file_type": ext.lstrip("."),
        "text": text,
        "char_count": len(text),
    }
