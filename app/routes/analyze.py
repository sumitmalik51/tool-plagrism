"""Analysis route — triggers the full plagiarism detection pipeline."""

from __future__ import annotations

import json
import uuid
import hashlib

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies.rate_limit import enforce_scan_limit, enforce_word_quota, record_scan, stored_text_excerpt
from app.models.schemas import PlagiarismReport
from app.services import progress as scan_progress
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
async def analyze_document(file: UploadFile, request: Request, document_id: str | None = Form(None)) -> PlagiarismReport:
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

    # --- Create progress tracker early so SSE can connect immediately --------
    effective_doc_id = document_id or uuid.uuid4().hex
    tracker = scan_progress.get_or_create(effective_doc_id)
    tracker.emit("upload", "Processing uploaded file...", 2)

    # --- Ingest ---------------------------------------------------------------
    try:
        ingestion_result = await ingest_file(file.filename, file_bytes, plan_type=plan_type, document_id=effective_doc_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # --- Enforce word quota (after ingestion so we count actual extracted text) -
    word_count = len(ingestion_result["text"].split())
    enforce_word_quota(request, word_count, "document")

    # --- Save document to DB --------------------------------------------------
    try:
        save_document(
            ingestion_result["document_id"],
            user_id=user_id,
            filename=ingestion_result["filename"],
            file_type=ingestion_result["file_type"],
            char_count=ingestion_result["char_count"],
            text_content=stored_text_excerpt(ingestion_result["text"]),
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

    # --- Create progress tracker early so SSE can connect immediately --------
    tracker = scan_progress.get_or_create(document_id)
    tracker.emit("upload", "Preparing text for analysis...", 2)

    # Resolve plan for premium query boost
    plan_type = "free"
    if user_id:
        from app.services.auth_service import get_user_by_id as _get_user
        _u = _get_user(user_id)
        if _u:
            plan_type = _u.get("plan_type", "free")

    # --- Enforce word quota ----------------------------------------------------
    word_count = len(body.text.split())
    enforce_word_quota(request, word_count, "text")

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
            text_content=stored_text_excerpt(body.text),
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

    def _sanitize(text: str) -> str:
        """Replace chars unsupported by Helvetica with ASCII equivalents."""
        return text.encode("ascii", "replace").decode("ascii")

    def _resolve_name(src: dict) -> str:
        """Derive a readable source name from title or URL."""
        title = src.get("title", "")
        if title and title != "Untitled" and len(title) > 2:
            return title
        url = src.get("url", "")
        if not url:
            return "Unknown Source"
        try:
            from urllib.parse import urlparse
            host = urlparse(url).hostname or ""
            host = host.removeprefix("www.")
            parts = host.split(".")
            if len(parts) > 1:
                parts = parts[:-1]
            return " ".join(p.capitalize() for p in parts)
        except Exception:
            return url[:60]

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    score = scan.get("plagiarism_score", 0) or 0
    confidence = scan.get("confidence_score", 0) or 0
    risk = (scan.get("risk_level") or "LOW").upper()
    sources_count = scan.get("sources_count", 0) or 0
    flagged_count = scan.get("flagged_count", 0) or 0
    original_pct = max(0, round(100 - score, 1))

    # ── Apply user dismissals (if any) ──
    from app.services.persistence import get_dismissals
    from app.utils.passage_key import adjusted_score, passage_key_for
    dismissals = get_dismissals(user_id, document_id) or {}
    raw_passages = report_data.get("flagged_passages", []) or []
    adj_score = adjusted_score(score, raw_passages, dismissals) if dismissals else score
    has_dismissals = bool(dismissals)
    # Display score = adjusted; original is shown alongside when dismissals exist.
    display_score = adj_score
    risk_colors = {"LOW": (0, 184, 148), "MEDIUM": (253, 203, 110), "HIGH": (225, 112, 85)}
    rc = risk_colors.get(risk, (100, 100, 100))

    # ── Header Banner ──
    pdf.set_fill_color(15, 17, 23)
    pdf.rect(0, 0, 210, 32, "F")
    # Accent stripe
    pdf.set_fill_color(108, 92, 231)
    pdf.rect(0, 32, 210, 1.2, "F")
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(255, 255, 255)
    pdf.set_y(7)
    pdf.cell(0, 10, "PlagiarismGuard", ln=True, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(180, 180, 200)
    pdf.cell(0, 5, "Originality Report", ln=True, align="C")
    pdf.ln(10)

    # ── Document Info Line ──
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 116, 139)
    doc_filename = scan.get("filename") or document_id[:20]
    pdf.cell(0, 4, f"{_sanitize(doc_filename)}   |   {scan.get('created_at', 'N/A')}   |   ID: {document_id[:16]}", ln=True)
    pdf.ln(4)

    # ── Hero Score Box ──
    hero_y = pdf.get_y()
    # Left side: big score
    pdf.set_draw_color(*rc)
    pdf.set_line_width(0.8)
    pdf.rect(10, hero_y, 60, 40, "D")
    pdf.set_xy(10, hero_y + 3)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(120, 120, 140)
    pdf.cell(60, 4, "OVERALL PLAGIARISM", align="C", ln=True)
    pdf.set_xy(10, hero_y + 9)
    pdf.set_font("Helvetica", "B", 36)
    pdf.set_text_color(*rc)
    pdf.cell(60, 16, f"{display_score:.0f}%", align="C", ln=True)
    # If user dismissed any passages, surface the original under the adjusted figure.
    if has_dismissals:
        pdf.set_xy(10, hero_y + 24)
        pdf.set_font("Helvetica", "", 6)
        pdf.set_text_color(120, 120, 140)
        pdf.cell(60, 3, f"Adjusted - original {score:.0f}%", align="C", ln=True)
    # Risk badge
    pdf.set_xy(22, hero_y + 27)
    pdf.set_fill_color(*rc)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    badge_w = pdf.get_string_width(f" {risk} Risk ") + 4
    pdf.cell(badge_w, 5, f" {risk} Risk ", fill=True, align="C")
    # Confidence
    pdf.set_xy(22, hero_y + 34)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(120, 120, 140)
    pdf.cell(36, 4, f"Confidence: {confidence:.0f}%", align="C")

    # Right side: breakdown bars
    match_groups = report_data.get("match_groups", [])
    bar_x = 80
    bar_y = hero_y + 2
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(50, 50, 60)
    pdf.set_xy(bar_x, bar_y)
    pdf.cell(120, 5, "Score Breakdown", ln=True)
    bar_y += 7

    cat_colors = {
        "Internet Matches": (225, 112, 85),
        "Research Papers": (108, 92, 231),
        "AI Generated Content": (253, 203, 110),
        "Paraphrased Similarity": (253, 203, 110),
    }

    if match_groups:
        for g in match_groups:
            cat = g.get("category", "")
            pct = g.get("percentage", 0) or 0
            color = cat_colors.get(cat, (150, 150, 150))

            pdf.set_xy(bar_x, bar_y)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(80, 80, 90)
            pdf.cell(60, 4, _sanitize(cat))
            pdf.set_text_color(*color)
            pdf.set_font("Helvetica", "B", 7)
            pdf.cell(20, 4, f"{pct:.1f}%", align="R")
            bar_y += 4

            # Progress bar background
            pdf.set_fill_color(230, 232, 240)
            pdf.rect(bar_x, bar_y, 80, 2.5, "F")
            # Progress bar fill
            bar_fill = max(min(pct, 100), 0.4)
            pdf.set_fill_color(*color)
            pdf.rect(bar_x, bar_y, 80 * bar_fill / 100, 2.5, "F")
            bar_y += 6
    else:
        pdf.set_xy(bar_x, bar_y)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(80, 80, 90)
        pdf.cell(0, 5, f"Plagiarism: {score:.1f}%  |  Original: {original_pct}%", ln=True)

    pdf.set_y(hero_y + 44)

    # ── Composition Strip ──
    comp_y = pdf.get_y()
    web_pct = 0.0
    para_pct = 0.0
    for g in match_groups:
        if g.get("category") == "Internet Matches":
            web_pct = g.get("percentage", 0) or 0
        if g.get("category") == "Paraphrased Similarity":
            para_pct = g.get("percentage", 0) or 0
    if not match_groups:
        web_pct = round(score * 0.35, 1)
        para_pct = round(score * 0.65, 1)

    strip_w = 190
    w_web = strip_w * web_pct / 100 if web_pct > 0 else 0
    w_para = strip_w * para_pct / 100 if para_pct > 0 else 0
    w_orig = max(0, strip_w - w_web - w_para)

    pdf.set_fill_color(225, 112, 85)
    if w_web > 0:
        pdf.rect(10, comp_y, w_web, 4, "F")
    pdf.set_fill_color(253, 203, 110)
    if w_para > 0:
        pdf.rect(10 + w_web, comp_y, w_para, 4, "F")
    pdf.set_fill_color(0, 184, 148)
    if w_orig > 0:
        pdf.rect(10 + w_web + w_para, comp_y, w_orig, 4, "F")

    pdf.set_y(comp_y + 5)
    pdf.set_font("Helvetica", "", 6)
    pdf.set_text_color(225, 112, 85)
    pdf.cell(35, 3, f"Web match {web_pct:.1f}%")
    pdf.set_text_color(253, 203, 110)
    pdf.cell(35, 3, f"Paraphrase {para_pct:.1f}%")
    pdf.set_text_color(0, 184, 148)
    pdf.cell(35, 3, f"Original {original_pct}%")
    pdf.ln(5)

    # ── Action Callout ──
    if score > 0:
        callout_y = pdf.get_y()
        pdf.set_fill_color(255, 248, 230)
        pdf.set_draw_color(253, 203, 110)
        pdf.set_line_width(0.3)
        pdf.rect(10, callout_y, 190, 8, "DF")
        pdf.set_xy(14, callout_y + 1.5)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(140, 100, 20)
        pdf.cell(0, 5, f"{score:.0f}% of this document matched external sources. "
                       f"Review the {sources_count} source(s) and {flagged_count} passage(s) below.", ln=True)
        pdf.ln(3)

    # ── Detected Sources ──
    sources = report_data.get("detected_sources", [])
    if sources:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, f"Detected Sources ({len(sources)})", ln=True)
        pdf.ln(1)

        for i, src in enumerate(sources[:25], 1):
            src_y = pdf.get_y()
            sim = src.get("similarity", 0) or 0
            sim_pct = sim * 100
            sim_color = (225, 112, 85) if sim > 0.7 else (253, 203, 110) if sim > 0.4 else (0, 184, 148)
            name = _sanitize(_resolve_name(src))
            url = src.get("url", "")
            stype = src.get("source_type", "Internet")
            matched = src.get("matched_words", 0) or 0
            blocks = src.get("text_blocks", 0) or 0

            # Light card background
            pdf.set_fill_color(247, 248, 252)
            pdf.rect(10, src_y, 190, 14, "F")
            # Left color bar
            pdf.set_fill_color(*sim_color)
            pdf.rect(10, src_y, 1.5, 14, "F")

            # Similarity %
            pdf.set_xy(14, src_y + 1)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*sim_color)
            pdf.cell(18, 5, f"{sim_pct:.1f}%")

            # Type badge
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(100, 100, 120)
            pdf.cell(18, 5, stype[:12])

            # Word count
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(130, 130, 150)
            pdf.cell(0, 5, f"{matched} words across {blocks} passage{'s' if blocks != 1 else ''}", ln=True)

            # Source name
            pdf.set_xy(14, src_y + 7)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(40, 40, 50)
            pdf.cell(105, 4, name[:65])

            # URL
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(108, 92, 231)
            pdf.cell(0, 4, _sanitize(url[:70]), ln=True)

            pdf.set_y(src_y + 16)

        pdf.ln(3)

    # ── Flagged Passages ──
    passages = report_data.get("flagged_passages", [])
    if passages:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 30, 30)
        header_label = f"Flagged Passages ({len(passages)})"
        if has_dismissals:
            dismissed_count = sum(1 for p in passages if passage_key_for(p) in dismissals)
            if dismissed_count:
                header_label += f"  -  {dismissed_count} dismissed"
        pdf.cell(0, 8, header_label, ln=True)
        pdf.ln(1)

        src_idx = {}
        for i, s in enumerate(sources, 1):
            if s.get("url"):
                src_idx[s["url"]] = i

        dismissal_label = {
            "quotation": "Quotation",
            "prior_work": "Prior work",
            "false_positive": "Not a match",
        }

        for i, p in enumerate(passages[:40], 1):
            text = (p.get("text") or "")[:300].replace("\n", " ")
            sim = p.get("similarity_score", 0) or 0
            sim_pct = sim * 100
            src_url = p.get("source", "")
            src_num = src_idx.get(src_url, "")
            pkey = passage_key_for(p)
            dismissal_info = dismissals.get(pkey)
            is_dismissed = dismissal_info is not None
            sim_color = (
                (160, 160, 170) if is_dismissed
                else (225, 112, 85) if sim > 0.7
                else (253, 203, 110) if sim > 0.4
                else (0, 184, 148)
            )

            p_y = pdf.get_y()
            # Left accent bar
            pdf.set_fill_color(*sim_color)
            pdf.rect(10, p_y, 2, 3, "F")

            # Header line
            pdf.set_xy(14, p_y)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*sim_color)
            label = f"{sim_pct:.1f}% similar"
            if src_num:
                label += f"  [Source {src_num}]"
            elif src_url:
                label += f"  - {_sanitize(src_url[:50])}"
            if is_dismissed:
                kind_label = dismissal_label.get(dismissal_info.get("kind", ""), "Dismissed")
                label += f"  - DISMISSED: {kind_label}"
            pdf.cell(0, 4, label, ln=True)

            # Passage text
            pdf.set_x(14)
            pdf.set_font("Helvetica", "", 7)
            # Slightly faded body text for dismissed entries
            pdf.set_text_color(*((140, 140, 150) if is_dismissed else (70, 70, 80)))
            pdf.multi_cell(186, 3.5, f'"{_sanitize(text)}"')
            pdf.ln(2)

    # ── Footer ──
    pdf.ln(6)
    pdf.set_fill_color(245, 246, 250)
    pdf.rect(0, pdf.get_y(), 210, 14, "F")
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(140, 140, 155)
    base_url = str(settings.app_base_url or "https://plagiarismguard.com").rstrip("/")
    pdf.cell(0, 5, f"Generated by PlagiarismGuard  |  {base_url}", ln=True, align="C")
    pdf.cell(0, 4, f"Report Date: {scan.get('created_at', 'N/A')}", ln=True, align="C")

    buf = BytesIO()
    buf.write(pdf.output())
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=plagiarismguard-report-{document_id[:12]}.pdf"},
    )


# ---------------------------------------------------------------------------
# Report Trust Pack / verification certificate
# ---------------------------------------------------------------------------

def _certificate_payload(row: dict) -> dict:
    base_url = str(settings.app_base_url or "https://plagiarismguard.com").rstrip("/")
    return {
        "verification_id": row["verification_id"],
        "document_id": row["document_id"],
        "report_hash": row["report_hash"],
        "score": row["score"],
        "risk_level": row["risk_level"],
        "issued_at": str(row["issued_at"]),
        "verification_url": f"{base_url}/api/v1/verify-report/{row['verification_id']}",
        "certificate": "PlagiarismGuard Originality Report Certificate",
    }


@router.post("/report-certificate/{document_id}", summary="Create a verifiable report certificate")
async def create_report_certificate(document_id: str, request: Request) -> JSONResponse:
    """Create or return a stable verification certificate for a scan report."""
    from app.services.database import get_db

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    db = get_db()
    scan = db.fetch_one(
        "SELECT document_id, user_id, report_json, plagiarism_score, risk_level, created_at "
        "FROM scans WHERE document_id = ? AND user_id = ?",
        (document_id, user_id),
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")

    existing = db.fetch_one(
        "SELECT * FROM report_certificates WHERE document_id = ? AND user_id = ?",
        (document_id, user_id),
    )
    if existing:
        return JSONResponse(_certificate_payload(dict(existing)))

    canonical = json.dumps(json.loads(scan.get("report_json") or "{}"), sort_keys=True, separators=(",", ":"))
    report_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    verification_id = hashlib.sha256(
        f"{document_id}|{user_id}|{report_hash}|{scan.get('created_at', '')}".encode("utf-8")
    ).hexdigest()[:32]

    try:
        db.execute(
            "INSERT INTO report_certificates "
            "(verification_id, document_id, user_id, report_hash, score, risk_level) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                verification_id,
                document_id,
                user_id,
                report_hash,
                scan.get("plagiarism_score") or 0,
                scan.get("risk_level") or "LOW",
            ),
        )
    except Exception:
        # Idempotency for concurrent clicks.
        pass

    cert = db.fetch_one("SELECT * FROM report_certificates WHERE verification_id = ?", (verification_id,))
    if not cert:
        raise HTTPException(status_code=500, detail="Certificate could not be created.")
    return JSONResponse(_certificate_payload(dict(cert)))


@router.get("/verify-report/{verification_id}", summary="Verify a report certificate")
async def verify_report_certificate(verification_id: str) -> JSONResponse:
    """Public endpoint that verifies a report certificate by ID."""
    from app.services.database import get_db

    if not verification_id or len(verification_id) > 64:
        raise HTTPException(status_code=400, detail="Invalid verification ID.")

    db = get_db()
    row = db.fetch_one(
        "SELECT verification_id, document_id, report_hash, score, risk_level, issued_at "
        "FROM report_certificates WHERE verification_id = ?",
        (verification_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    payload = _certificate_payload(dict(row))
    payload["valid"] = True
    return JSONResponse(payload)


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
