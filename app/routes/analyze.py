"""Analysis route — triggers the full plagiarism detection pipeline."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.dependencies.rate_limit import enforce_scan_limit, record_scan
from app.models.schemas import PlagiarismReport
from app.services.ingestion import ingest_file
from app.services.orchestrator import run_pipeline
from app.services.persistence import save_document, save_scan
from app.services.rate_limiter import UserTier
from app.services.report_generator import report_to_json
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["analysis"])


# ---------------------------------------------------------------------------
# Request schema for text-based analysis
# ---------------------------------------------------------------------------

class AnalyzeTextRequest(BaseModel):
    """JSON body for the /analyze-agent endpoint."""
    text: str = Field(..., min_length=1, description="Plain text to analyse for plagiarism")
    excluded_domains: list[str] = Field(
        default_factory=list,
        description="List of domains to exclude from plagiarism detection (e.g. your own website)",
    )
    document_id: str | None = Field(
        default=None,
        description="Optional client-generated document ID for SSE progress tracking",
    )


# ---------------------------------------------------------------------------
# File-based analysis (existing)
# ---------------------------------------------------------------------------

@router.post(
    "/analyze",
    response_model=PlagiarismReport,
    status_code=status.HTTP_200_OK,
    summary="Upload and analyse a document for plagiarism",
    dependencies=[Depends(enforce_scan_limit)],
)
async def analyze_document(file: UploadFile, request: Request) -> PlagiarismReport:
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
    user_id = getattr(request.state, "user_id", None)

    # --- Ingest ---------------------------------------------------------------
    try:
        ingestion_result = await ingest_file(file.filename, file_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # --- Save document to DB --------------------------------------------------
    try:
        save_document(
            ingestion_result["document_id"],
            user_id=user_id,
            filename=ingestion_result["filename"],
            file_type=ingestion_result["file_type"],
            char_count=ingestion_result["char_count"],
            text_content=ingestion_result["text"][:50000],  # cap stored text
        )
    except Exception as exc:
        logger.warning("document_save_failed", error=str(exc))

    # --- Run pipeline ---------------------------------------------------------
    report = await run_pipeline(
        document_id=ingestion_result["document_id"],
        text=ingestion_result["text"],
    )

    # --- Save scan result to DB -----------------------------------------------
    _persist_scan(report, user_id)

    # --- Record scan against rate limit & build response ----------------------
    remaining = record_scan(request)

    logger.info(
        "analysis_complete",
        document_id=report.document_id,
        plagiarism_score=report.plagiarism_score,
    )

    return _response_with_rate_headers(report, request, remaining)


# ---------------------------------------------------------------------------
# Text-based analysis (for Foundry agents & frontend)
# ---------------------------------------------------------------------------

@router.post(
    "/analyze-agent",
    response_model=PlagiarismReport,
    status_code=status.HTTP_200_OK,
    summary="Analyse pasted text for plagiarism",
    dependencies=[Depends(enforce_scan_limit)],
)
async def analyze_text(
    body: AnalyzeTextRequest,
    request: Request,
) -> PlagiarismReport:
    """Accept raw text, run every detection agent in parallel, and return
    a structured plagiarism report.

    This is the primary endpoint used by the frontend text-paste flow
    and by Azure Foundry agents.
    """
    document_id = body.document_id or uuid.uuid4().hex
    user_id = getattr(request.state, "user_id", None)

    logger.info(
        "analyze_agent_started",
        document_id=document_id,
        text_length=len(body.text),
    )

    # --- Save document to DB --------------------------------------------------
    try:
        save_document(
            document_id,
            user_id=user_id,
            filename=None,
            file_type="text",
            char_count=len(body.text),
            text_content=body.text[:50000],
        )
    except Exception as exc:
        logger.warning("document_save_failed", error=str(exc))

    report = await run_pipeline(
        document_id=document_id,
        text=body.text,
        excluded_domains=body.excluded_domains or None,
    )

    # --- Save scan result to DB -----------------------------------------------
    _persist_scan(report, user_id)

    # --- Record scan against rate limit & build response ----------------------
    remaining = record_scan(request)

    logger.info(
        "analyze_agent_complete",
        document_id=report.document_id,
        plagiarism_score=report.plagiarism_score,
    )

    return _response_with_rate_headers(report, request, remaining)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _response_with_rate_headers(
    report: PlagiarismReport,
    request: Request,
    remaining: int,
) -> JSONResponse:
    """Wrap the report in a JSONResponse with ``X-RateLimit-*`` headers."""
    tier: UserTier = getattr(request.state, "rate_limit_tier", UserTier.ANONYMOUS)

    from app.config import settings as _settings

    if tier in (UserTier.PRO, UserTier.PREMIUM):
        limit_val = "unlimited"
        remaining_val = "unlimited"
    elif tier == UserTier.FREE:
        limit_val = str(_settings.scan_limit_free)
        remaining_val = str(remaining)
    else:
        limit_val = str(_settings.scan_limit_anonymous)
        remaining_val = str(remaining)

    headers = {
        "X-RateLimit-Limit": limit_val,
        "X-RateLimit-Remaining": remaining_val,
        "X-RateLimit-Reset": "midnight UTC",
    }

    return JSONResponse(
        content=report.model_dump(mode="json"),
        headers=headers,
    )


def _persist_scan(report: PlagiarismReport, user_id: int | None) -> None:
    """Save a scan result to the database (best-effort, never raises)."""
    try:
        save_scan(
            report.document_id,
            user_id=user_id,
            plagiarism_score=report.plagiarism_score,
            confidence_score=report.confidence_score,
            risk_level=report.risk_level.value,
            sources_count=len(report.detected_sources),
            flagged_count=len(report.flagged_passages),
            report_json=report.model_dump_json(),
        )
    except Exception as exc:
        logger.warning("scan_save_failed", error=str(exc))
