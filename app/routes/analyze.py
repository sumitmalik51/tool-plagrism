"""Analysis route — triggers the full plagiarism detection pipeline."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.models.schemas import PlagiarismReport
from app.services.ingestion import ingest_file
from app.services.orchestrator import run_pipeline
from app.services.report_generator import report_to_json
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post(
    "/analyze",
    response_model=PlagiarismReport,
    status_code=status.HTTP_200_OK,
    summary="Upload and analyse a document for plagiarism",
)
async def analyze_document(file: UploadFile) -> PlagiarismReport:
    """Accept a file, run every detection agent in parallel, and return
    a structured plagiarism report with scores, flagged passages, and
    a human-readable explanation.
    """
    if file.filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required.",
        )

    file_bytes = await file.read()

    # --- Ingest ---------------------------------------------------------------
    try:
        ingestion_result = await ingest_file(file.filename, file_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # --- Run pipeline ---------------------------------------------------------
    report = await run_pipeline(
        document_id=ingestion_result["document_id"],
        text=ingestion_result["text"],
    )

    logger.info(
        "analysis_complete",
        document_id=report.document_id,
        plagiarism_score=report.plagiarism_score,
    )

    return report
