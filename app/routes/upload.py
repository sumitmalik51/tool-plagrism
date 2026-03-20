"""Upload route — handles file upload requests."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, status

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
