"""Ingestion service — handles file upload persistence and orchestrates extraction."""

from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles

from app.config import settings
from app.services.text_extractor import extract_text
from app.utils.helpers import ensure_upload_dir, validate_file_extension, validate_file_size, get_upload_limit_mb
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def ingest_file(filename: str, file_bytes: bytes, plan_type: str = "free") -> dict:
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

    # --- Persist file ---------------------------------------------------------
    document_id = uuid.uuid4().hex
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
