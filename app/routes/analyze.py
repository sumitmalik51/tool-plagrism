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
from app.services.rate_limiter import PLAN_TO_TIER, UserTier, limiter
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
    use_gpt_ai_detection: bool = Field(
        default=False,
        description="Enable GPT-powered AI detection (more accurate, uses API credits)",
    )
    language: str | None = Field(
        default=None,
        description="Override auto-detected language (ISO code: en, es, fr, de, hi, zh, ja, ko, ar, pt, it). Auto-detects if omitted.",
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

    # Resolve plan for tier-based file size limits
    plan_type = "free"
    if user_id:
        from app.services.auth_service import get_user_by_id
        user = get_user_by_id(user_id)
        if user:
            plan_type = user.get("plan_type", "free")

    # --- Ingest ---------------------------------------------------------------
    try:
        ingestion_result = await ingest_file(file.filename, file_bytes, plan_type=plan_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # --- Enforce word quota (after ingestion so we count actual extracted text) -
    word_count = len(ingestion_result["text"].split())
    if user_id:
        tier = PLAN_TO_TIER.get(plan_type, UserTier.FREE)
        wq = limiter.check_word_quota(user_id, tier, word_count=word_count)
        if not wq["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "word_quota_exceeded",
                    "message": f"Monthly word limit reached ({wq['limit']:,} words). "
                               f"Used {wq['used']:,}, this document has {word_count:,} words.",
                    "used": wq["used"],
                    "limit": wq["limit"],
                    "remaining": wq["remaining"],
                    "upgrade_url": "/pricing",
                },
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
        plan_type=plan_type,
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

    # Resolve plan for premium query boost
    plan_type = "free"
    if user_id:
        from app.services.auth_service import get_user_by_id as _get_user
        _u = _get_user(user_id)
        if _u:
            plan_type = _u.get("plan_type", "free")

    # --- Enforce word quota ----------------------------------------------------
    word_count = len(body.text.split())
    if user_id:
        tier = PLAN_TO_TIER.get(plan_type, UserTier.FREE)
        wq = limiter.check_word_quota(user_id, tier, word_count=word_count)
        if not wq["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "word_quota_exceeded",
                    "message": f"Monthly word limit reached ({wq['limit']:,} words). "
                               f"Used {wq['used']:,}, this text has {word_count:,} words.",
                    "used": wq["used"],
                    "limit": wq["limit"],
                    "remaining": wq["remaining"],
                    "upgrade_url": "/pricing",
                },
            )

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
        use_gpt_ai_detection=body.use_gpt_ai_detection,
        language_override=body.language,
        plan_type=plan_type,
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

    # Fire webhooks (async, best-effort)
    if user_id:
        try:
            import asyncio
            from app.routes.webhooks import fire_webhooks
            payload = {
                "event": "scan.complete",
                "document_id": report.document_id,
                "plagiarism_score": report.plagiarism_score,
                "confidence_score": report.confidence_score,
                "risk_level": report.risk_level.value,
                "sources_count": len(report.detected_sources),
                "flagged_count": len(report.flagged_passages),
            }
            loop = asyncio.get_running_loop()
            loop.create_task(fire_webhooks(user_id, "scan.complete", payload))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# PDF Report Export
# ---------------------------------------------------------------------------

@router.get("/export-pdf/{document_id}", summary="Download scan report as PDF")
async def export_pdf_report(document_id: str, request: Request):
    """Generate a branded PDF report for a scan result."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    from app.services.database import get_db
    db = get_db()
    scan = db.fetch_one(
        "SELECT * FROM scans WHERE document_id = ? AND user_id = ?",
        (document_id, user_id),
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")

    report_data = {}
    if scan.get("report_json"):
        report_data = __import__("json").loads(scan["report_json"])

    try:
        from fpdf import FPDF
    except ImportError:
        raise HTTPException(status_code=503, detail="PDF generation not available")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(79, 70, 229)
    pdf.cell(0, 12, "PlagiarismGuard Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 6, f"Document: {document_id}", ln=True, align="C")
    pdf.cell(0, 6, f"Generated: {scan.get('created_at', 'N/A')}", ln=True, align="C")
    pdf.ln(10)

    # Score Summary
    score = scan.get("plagiarism_score", 0)
    risk = scan.get("risk_level", "LOW")
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, "Score Summary", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 7, f"Plagiarism Score: {score:.1f}%", ln=True)
    pdf.cell(0, 7, f"Confidence: {scan.get('confidence_score', 0):.1%}", ln=True)
    pdf.cell(0, 7, f"Risk Level: {risk}", ln=True)
    pdf.cell(0, 7, f"Sources Found: {scan.get('sources_count', 0)}", ln=True)
    pdf.cell(0, 7, f"Flagged Passages: {scan.get('flagged_count', 0)}", ln=True)
    pdf.ln(8)

    # Detected Sources
    sources = report_data.get("detected_sources", [])
    if sources:
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 10, "Detected Sources", ln=True)
        pdf.set_font("Helvetica", "", 9)
        for i, src in enumerate(sources[:20], 1):
            pdf.set_text_color(60, 60, 60)
            title = src.get("title", "Unknown Source")[:80]
            url = src.get("url", "N/A")[:80]
            sim = src.get("similarity", 0)
            pdf.cell(0, 6, f"{i}. {title} ({sim:.0%} match)", ln=True)
            pdf.set_text_color(100, 116, 139)
            pdf.cell(0, 5, f"   {url}", ln=True)
        pdf.ln(6)

    # Flagged Passages
    passages = report_data.get("flagged_passages", [])
    if passages:
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 10, "Flagged Passages", ln=True)
        pdf.set_font("Helvetica", "", 9)
        for i, p in enumerate(passages[:30], 1):
            pdf.set_text_color(60, 60, 60)
            text = p.get("text", "")[:200].replace("\n", " ")
            pdf.multi_cell(0, 5, f"{i}. \"{text}\"")
            src_url = p.get("source", "")
            if src_url:
                pdf.set_text_color(100, 116, 139)
                pdf.cell(0, 5, f"   Source: {src_url[:80]}", ln=True)
            pdf.ln(2)

    # Footer
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    base_url = str(settings.app_base_url or "https://plagiarismguard.com").rstrip("/")
    pdf.cell(0, 5, f"Generated by PlagiarismGuard — {base_url}", ln=True, align="C")

    buf = BytesIO()
    buf.write(pdf.output())
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=plagiarismguard-report-{document_id[:12]}.pdf"},
    )


# ---------------------------------------------------------------------------
# Shareable report links
# ---------------------------------------------------------------------------

class ShareReportRequest(BaseModel):
    document_id: str = Field(..., description="Document ID of the scan to share")
    expires_in_days: int | None = Field(default=7, ge=1, le=90, description="Days until link expires (null = never)")


@router.post("/share-report", summary="Create a shareable link for a scan report")
async def share_report(body: ShareReportRequest, request: Request) -> JSONResponse:
    """Generate a unique share URL for an existing scan report."""
    from app.services.database import get_db

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    db = get_db()
    # Verify the scan exists and belongs to this user
    scan = db.fetch_one(
        "SELECT id FROM scans WHERE document_id = ? AND user_id = ?",
        (body.document_id, user_id),
    )
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")

    share_id = uuid.uuid4().hex

    if body.expires_in_days is not None:
        is_mssql = isinstance(db, type) and hasattr(db, '_conn_str') or hasattr(db, '_connection_string')
        if is_mssql:
            expires_clause = f"DATEADD(day, {int(body.expires_in_days)}, GETUTCDATE())"
        else:
            expires_clause = f"datetime('now', '+{int(body.expires_in_days)} days')"
    else:
        expires_clause = "NULL"

    db.execute(
        f"INSERT INTO shared_reports (share_id, scan_id, user_id, expires_at) "
        f"VALUES (?, ?, ?, {expires_clause})",
        (share_id, scan["id"], user_id),
    )

    logger.info("report_shared", document_id=body.document_id, share_id=share_id)
    return JSONResponse({"share_id": share_id})


@router.get("/shared/{share_id}", summary="Retrieve a shared report (public)")
async def get_shared_report(share_id: str) -> JSONResponse:
    """Return a shared report's JSON data. No authentication required."""
    from app.services.database import get_db

    if not share_id or len(share_id) > 64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid share ID")

    db = get_db()
    row = db.fetch_one(
        "SELECT sr.share_id, sr.expires_at, s.report_json, s.document_id, s.plagiarism_score, "
        "s.risk_level, s.created_at AS scanned_at "
        "FROM shared_reports sr JOIN scans s ON sr.scan_id = s.id "
        "WHERE sr.share_id = ?",
        (share_id,),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shared report not found or expired")

    # Check expiration
    if row.get("expires_at"):
        from datetime import datetime, timezone
        try:
            exp = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                raise HTTPException(status_code=status.HTTP_410_GONE, detail="This shared link has expired")
        except (ValueError, TypeError):
            pass  # If we can't parse, allow access

    report_data = json.loads(row["report_json"]) if row.get("report_json") else {}
    return JSONResponse({
        "share_id": row["share_id"],
        "document_id": row.get("document_id"),
        "plagiarism_score": row.get("plagiarism_score"),
        "risk_level": row.get("risk_level"),
        "scanned_at": str(row.get("scanned_at", "")),
        "report": report_data,
    })
