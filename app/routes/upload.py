"""Upload route — handles file upload and Google Docs import requests."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.models.schemas import FileType, UploadResponse
from app.services.ingestion import ingest_file
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["upload"])


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document for plagiarism analysis",
)
async def upload_file(file: UploadFile) -> UploadResponse:
    """Accept a PDF, DOCX, or TXT file and extract its text content.

    Returns document metadata including a unique ``document_id`` that
    can be used in subsequent analysis requests.
    """
    if file.filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required.",
        )

    file_bytes = await file.read()

    try:
        result = await ingest_file(file.filename, file_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    logger.info(
        "upload_success",
        document_id=result["document_id"],
        filename=result["filename"],
    )

    return UploadResponse(
        document_id=result["document_id"],
        filename=result["filename"],
        file_type=FileType(result["file_type"]),
        char_count=result["char_count"],
    )


# ---------------------------------------------------------------------------
# Google Docs Import
# ---------------------------------------------------------------------------

_GDOC_ID_PATTERN = re.compile(
    r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)"
)


class GoogleDocsImportRequest(BaseModel):
    """Request body for Google Docs import."""
    url: str = Field(..., description="Google Docs sharing URL (document must be set to 'Anyone with the link')")


@router.post(
    "/import-google-doc",
    summary="Import text from a public Google Doc",
    status_code=status.HTTP_200_OK,
)
async def import_google_doc(body: GoogleDocsImportRequest):
    """Extract text from a publicly shared Google Doc.

    The document must have sharing set to *"Anyone with the link can view"*.
    We download it as plain text using Google's export URL — no OAuth needed.
    """
    # Extract document ID from URL
    match = _GDOC_ID_PATTERN.search(body.url)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Google Docs URL. Expected format: https://docs.google.com/document/d/{ID}/...",
        )

    doc_id = match.group(1)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"

    import httpx

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(export_url)

        if resp.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found. Check the URL and ensure the document exists.",
            )
        if resp.status_code in (401, 403):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Document is not publicly shared. Set sharing to 'Anyone with the link can view'.",
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Google returned status {resp.status_code}. Try again later.",
            )

        text = resp.text.strip()
        if not text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document appears to be empty.",
            )

        # Limit to 500KB of text
        if len(text) > 500_000:
            text = text[:500_000]

        logger.info("google_doc_imported", doc_id=doc_id, char_count=len(text))

        return {
            "text": text,
            "char_count": len(text),
            "source": f"Google Docs ({doc_id[:8]}…)",
        }

    except httpx.HTTPError as exc:
        logger.error("google_doc_fetch_failed", error=str(exc), doc_id=doc_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch document from Google. Check the URL and try again.",
        )
