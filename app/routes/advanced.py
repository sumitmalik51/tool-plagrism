"""Advanced analysis routes — SSE progress, section analysis, cross-doc comparison,
reference validation.

These endpoints extend the core plagiarism pipeline for large research paper workflows.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies.rate_limit import enforce_scan_limit, enforce_usage_limit, record_scan, record_usage
from app.services import progress as scan_progress
from app.services.ingestion import ingest_file
from app.services.orchestrator import run_pipeline
from app.services.persistence import save_document, save_scan, get_scan, get_user_scans
from app.tools.section_splitter import split_into_sections
from app.tools.citation_stripper import strip_reference_section
from app.tools.reference_validator import validate_references, extract_references
from app.tools.embedding_tool import generate_embeddings
from app.tools.similarity_tool import cosine_similarity_matrix
from app.tools.content_extractor_tool import chunk_text
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["advanced-analysis"])


# ═══════════════════════════════════════════════════════════════════════════
# Feature 1: SSE Progress Tracking
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/scan-progress/{document_id}",
    summary="Stream real-time scan progress via Server-Sent Events",
)
async def scan_progress_sse(document_id: str):
    """Stream progress updates for a running plagiarism scan.

    Returns SSE events with stage, message, percent (0-100), and metadata.
    The stream ends when the scan completes or after 5 minutes timeout.

    Frontend usage:
        const es = new EventSource('/api/v1/scan-progress/' + docId);
        es.onmessage = (e) => { const data = JSON.parse(e.data); ... };
    """
    tracker = scan_progress.get(document_id)
    if tracker is None:
        # Tracker not created yet (race) or scan already finished — wait briefly
        for _ in range(20):
            await asyncio.sleep(0.4)
            tracker = scan_progress.get(document_id)
            if tracker is not None:
                break
        if tracker is None:
            # Still nothing — return a single "done" event so the EventSource
            # closes gracefully instead of the browser retrying on 404.
            async def _no_op():
                yield 'data: {"stage": "done", "message": "Scan complete", "percent": 100}\n\n'
            return StreamingResponse(_no_op(), media_type="text/event-stream")

    async def _event_stream():
        queue = tracker.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300.0)
                except asyncio.TimeoutError:
                    yield "data: {\"stage\": \"timeout\", \"message\": \"Progress stream timed out\", \"percent\": -1}\n\n"
                    break

                if event is None:
                    # Scan completed
                    yield "data: {\"stage\": \"done\", \"message\": \"Scan complete\", \"percent\": 100}\n\n"
                    break

                payload = {
                    "stage": event.stage,
                    "message": event.message,
                    "percent": event.percent,
                    **event.data,
                }
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            tracker.unsubscribe(queue)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Feature 2: Section-by-Section Analysis
# ═══════════════════════════════════════════════════════════════════════════

class SectionAnalysisRequest(BaseModel):
    """Request for section-by-section plagiarism analysis."""
    text: str = Field(..., min_length=1, description="Full document text")
    excluded_domains: list[str] = Field(
        default_factory=list,
        description="Domains to exclude from detection",
    )


class SectionResult(BaseModel):
    """Result for a single section."""
    title: str
    word_count: int
    plagiarism_score: float = Field(ge=0.0, le=100.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    risk_level: str
    flagged_count: int
    source_count: int


@router.post(
    "/analyze-sections",
    status_code=status.HTTP_200_OK,
    summary="Analyze document with per-section plagiarism breakdown",
    dependencies=[Depends(enforce_scan_limit)],
)
async def analyze_sections(
    body: SectionAnalysisRequest,
    request: Request,
) -> dict:
    """Split a document by headings and run plagiarism detection per section.

    Returns an overall report PLUS a per-section breakdown showing which
    parts of the paper have the highest plagiarism scores.
    """
    document_id = uuid.uuid4().hex
    user_id = getattr(request.state, "user_id", None)

    logger.info(
        "section_analysis_started",
        document_id=document_id,
        text_length=len(body.text),
    )

    # --- Save document ---------------------------------------------------------
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

    # --- Split into sections --------------------------------------------------
    sections = split_into_sections(body.text)

    # --- Run full pipeline on entire document first ---------------------------
    overall_report = await run_pipeline(
        document_id=document_id,
        text=body.text,
        excluded_domains=body.excluded_domains or None,
    )

    # --- Analyze each section by mapping flagged passages to sections ----------
    section_results: list[dict] = []

    for section in sections:
        section_start = section["start_char"]
        section_end = section["end_char"]
        section_text = section["text"]

        # Find flagged passages that fall within this section
        section_flagged = []
        section_sources = set()
        for fp in overall_report.flagged_passages:
            # Check if the flagged passage text appears in this section
            if fp.text[:100] in section_text:
                section_flagged.append(fp)
                if fp.source:
                    section_sources.add(fp.source)

        # Compute per-section score based on chunk coverage
        if section["word_count"] < 20:
            section_score = 0.0
            section_confidence = 0.0
        elif section_flagged:
            # Approximate: ratio of flagged words to total section words
            flagged_words = sum(len(f.text.split()) for f in section_flagged)
            section_score = min(
                (flagged_words / section["word_count"]) * 100,
                100.0,
            )
            section_confidence = overall_report.confidence_score
        else:
            section_score = 0.0
            section_confidence = overall_report.confidence_score * 0.5

        # Risk level
        if section_score >= settings.risk_threshold_high and section_confidence >= 0.4:
            risk = "HIGH"
        elif section_score >= settings.risk_threshold_medium:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        section_results.append({
            "title": section["title"],
            "word_count": section["word_count"],
            "plagiarism_score": round(section_score, 2),
            "confidence_score": round(section_confidence, 2),
            "risk_level": risk,
            "flagged_count": len(section_flagged),
            "source_count": len(section_sources),
        })

    # --- Save scan & track usage -----------------------------------------------
    _persist_scan_simple(overall_report, user_id)
    remaining = record_scan(request)

    logger.info(
        "section_analysis_complete",
        document_id=document_id,
        sections_analyzed=len(section_results),
        overall_score=overall_report.plagiarism_score,
    )

    return {
        "document_id": document_id,
        "overall": {
            "plagiarism_score": overall_report.plagiarism_score,
            "confidence_score": overall_report.confidence_score,
            "risk_level": overall_report.risk_level.value,
            "flagged_count": len(overall_report.flagged_passages),
            "source_count": len(overall_report.detected_sources),
            "explanation": overall_report.explanation,
        },
        "sections": section_results,
        "section_count": len(section_results),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Feature 4: Reference / DOI Validation
# ═══════════════════════════════════════════════════════════════════════════

class ReferenceValidationRequest(BaseModel):
    """Request for reference validation."""
    text: str = Field(..., min_length=1, description="Full document text (references will be auto-extracted)")


@router.post(
    "/validate-references",
    status_code=status.HTTP_200_OK,
    summary="Validate that cited references actually exist",
    dependencies=[Depends(enforce_usage_limit)],
)
async def validate_references_endpoint(
    body: ReferenceValidationRequest,
    http_request: Request = None,
) -> dict:
    """Extract references from a document and verify each against OpenAlex.

    Identifies:
    - **Validated**: References confirmed to exist in academic databases
    - **Unverified**: Could not be found (may be obscure or misspelled)
    - **Suspicious**: No matching work found despite having searchable metadata

    Useful for detecting fabricated citations in research papers.
    """
    logger.info("reference_validation_requested", text_length=len(body.text))

    # Extract just the reference section for focused validation
    _, ref_section = strip_reference_section(body.text)
    text_to_validate = ref_section if ref_section else body.text

    result = await validate_references(text_to_validate)

    if http_request:
        record_usage(http_request, tool_type="reference_validation")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Feature 5: Cross-Document Comparison
# ═══════════════════════════════════════════════════════════════════════════

class CrossCompareRequest(BaseModel):
    """Request for comparing two texts for similarity."""
    text_a: str = Field(..., min_length=1, description="First document text")
    text_b: str = Field(..., min_length=1, description="Second document text")
    label_a: str = Field(default="Document A", description="Label for first document")
    label_b: str = Field(default="Document B", description="Label for second document")


@router.post(
    "/compare-documents",
    status_code=status.HTTP_200_OK,
    summary="Compare two documents for self-plagiarism or overlap",
    dependencies=[Depends(enforce_usage_limit)],
)
async def compare_documents(
    body: CrossCompareRequest,
    http_request: Request = None,
) -> dict:
    """Compare two documents directly using embedding similarity.

    Useful for:
    - **Self-plagiarism detection**: Compare an author's new paper against prior work
    - **Submission checking**: Compare two student submissions
    - **Version comparison**: Check how much text was reused between versions

    Returns overall similarity, per-chunk matches, and matched passages.
    """
    import time as _time
    import numpy as np

    start = _time.perf_counter()

    logger.info(
        "cross_compare_started",
        text_a_length=len(body.text_a),
        text_b_length=len(body.text_b),
    )

    # Chunk both documents
    chunks_a_result = chunk_text(body.text_a, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
    chunks_b_result = chunk_text(body.text_b, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
    chunks_a = chunks_a_result["chunks"]
    chunks_b = chunks_b_result["chunks"]

    if not chunks_a or not chunks_b:
        return {
            "similarity_score": 0.0,
            "overlap_percentage": 0.0,
            "matched_passages": [],
            "summary": "One or both documents are too short to compare.",
            "elapsed_s": 0.0,
        }

    # Generate embeddings for both
    all_chunks = chunks_a + chunks_b
    all_embeddings = await generate_embeddings(all_chunks)

    emb_a = all_embeddings[:len(chunks_a)]
    emb_b = all_embeddings[len(chunks_a):]

    # Compute cross-similarity matrix
    sim_matrix = cosine_similarity_matrix(emb_a, emb_b)

    # Find matching passages above threshold
    threshold = settings.semantic_similarity_threshold - 0.10  # Lower threshold for cross-doc
    matched_passages: list[dict] = []
    matched_a_indices: set[int] = set()

    for i in range(sim_matrix.shape[0]):
        best_j = int(np.argmax(sim_matrix[i]))
        best_sim = float(min(sim_matrix[i, best_j], 1.0))

        if best_sim >= threshold:
            matched_a_indices.add(i)
            matched_passages.append({
                "text_a": chunks_a[i][:settings.passage_display_length],
                "text_b": chunks_b[best_j][:settings.passage_display_length],
                "similarity": round(best_sim, 4),
                "chunk_a_index": i,
                "chunk_b_index": best_j,
            })

    # Sort by similarity (highest first)
    matched_passages.sort(key=lambda p: p["similarity"], reverse=True)
    matched_passages = matched_passages[:settings.flagged_passages_limit]

    # Overall metrics
    overlap_pct = round((len(matched_a_indices) / len(chunks_a)) * 100, 2) if chunks_a else 0.0
    avg_sim = float(np.mean(sim_matrix.max(axis=1))) if sim_matrix.size > 0 else 0.0
    max_sim = float(np.max(sim_matrix)) if sim_matrix.size > 0 else 0.0

    elapsed = round(_time.perf_counter() - start, 3)

    # Summary
    if overlap_pct >= 60:
        summary = f"High overlap detected: {overlap_pct:.0f}% of {body.label_a} matches {body.label_b}. Significant text reuse suspected."
    elif overlap_pct >= 30:
        summary = f"Moderate overlap: {overlap_pct:.0f}% of {body.label_a} matches {body.label_b}. Some sections may need revision."
    elif overlap_pct > 0:
        summary = f"Low overlap: {overlap_pct:.0f}% of {body.label_a} matches {body.label_b}. Minor similarities found."
    else:
        summary = f"No significant overlap found between {body.label_a} and {body.label_b}."

    if http_request:
        record_usage(http_request, tool_type="cross_compare")

    logger.info(
        "cross_compare_complete",
        overlap_pct=overlap_pct,
        matched_count=len(matched_passages),
        elapsed_s=elapsed,
    )

    return {
        "similarity_score": round(avg_sim * 100, 2),
        "max_similarity": round(max_sim, 4),
        "overlap_percentage": overlap_pct,
        "matched_passage_count": len(matched_passages),
        "chunks_a": len(chunks_a),
        "chunks_b": len(chunks_b),
        "label_a": body.label_a,
        "label_b": body.label_b,
        "matched_passages": matched_passages,
        "summary": summary,
        "elapsed_s": elapsed,
    }


@router.post(
    "/compare-files",
    status_code=status.HTTP_200_OK,
    summary="Upload and compare two files for overlap",
    dependencies=[Depends(enforce_usage_limit)],
)
async def compare_files(
    file_a: UploadFile,
    file_b: UploadFile,
    http_request: Request = None,
) -> dict:
    """Upload two files and compare them for text similarity.

    Supports PDF, DOCX, TXT, and TEX files.
    """
    if not file_a.filename or not file_b.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both filenames are required.",
        )

    # Ingest both files
    try:
        bytes_a = await file_a.read()
        bytes_b = await file_b.read()
        ingestion_a = await ingest_file(file_a.filename, bytes_a)
        ingestion_b = await ingest_file(file_b.filename, bytes_b)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Use the text compare logic
    body = CrossCompareRequest(
        text_a=ingestion_a["text"],
        text_b=ingestion_b["text"],
        label_a=file_a.filename,
        label_b=file_b.filename,
    )
    return await compare_documents(body, http_request)


# ═══════════════════════════════════════════════════════════════════════════
# Feature 6: Institutional Document Repository
# ═══════════════════════════════════════════════════════════════════════════

class RepositoryCheckRequest(BaseModel):
    """Request for checking text against institutional repository."""
    text: str = Field(..., min_length=1, description="Text to check against stored documents")


@router.post(
    "/repository-check",
    status_code=status.HTTP_200_OK,
    summary="Check text against institutional document repository",
    dependencies=[Depends(enforce_usage_limit)],
)
async def repository_check(
    body: RepositoryCheckRequest,
    http_request: Request = None,
) -> dict:
    """Compare text against all previously scanned documents using fingerprinting.

    Returns matching documents with Jaccard similarity scores.
    Useful for detecting self-plagiarism or overlap with prior submissions.
    """
    from app.services.repository import find_similar_documents

    user_id = getattr(http_request.state, "user_id", None) if http_request else None

    matches = find_similar_documents(
        body.text,
        user_id=user_id,
        threshold=0.02,
        limit=15,
    )

    return {
        "matches": matches,
        "total_checked": len(matches),
        "has_overlap": any(m["jaccard"] >= 0.05 for m in matches),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Feature: Scan History API
# ═══════════════════════════════════════════════════════════════════════════

class ScanHistoryParams(BaseModel):
    """Query parameters for scan history."""
    limit: int = Field(default=20, ge=1, le=100, description="Max results per page")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")
    risk_level: str | None = Field(default=None, description="Filter by risk level: LOW, MEDIUM, HIGH")
    sort_by: str = Field(default="created_at", description="Sort field: created_at, plagiarism_score, filename")
    sort_order: str = Field(default="desc", description="Sort direction: asc or desc")
    search: str | None = Field(default=None, description="Search in filename or document_id")


@router.get(
    "/scan-history",
    summary="Get paginated scan history with filtering",
)
async def scan_history_endpoint(
    http_request: Request,
    limit: int = 20,
    offset: int = 0,
    risk_level: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search: str | None = None,
) -> dict:
    """Return the user's scan history with pagination, filtering, and sorting.

    Supports filtering by risk level, searching by filename/document_id,
    and sorting by created_at, plagiarism_score, or filename.
    """
    user_id = getattr(http_request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)

    scans = get_user_scans(
        user_id,
        limit=limit + 1,  # Fetch one extra to detect if there are more pages
        offset=offset,
        risk_level=risk_level,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
    )

    has_more = len(scans) > limit
    if has_more:
        scans = scans[:limit]

    # Strip large report_json from list view for performance
    for s in scans:
        s.pop("report_json", None)

    return {
        "scans": scans,
        "count": len(scans),
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
    }


@router.get(
    "/scan-history/{document_id}",
    summary="Get detailed scan result for a specific document",
)
async def scan_detail_endpoint(
    document_id: str,
    http_request: Request,
) -> dict:
    """Return the full scan detail including the report JSON for a specific document."""
    user_id = getattr(http_request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    scan = get_scan(document_id, user_id)
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")

    # Parse report_json back to dict if present
    report_json = scan.get("report_json")
    if report_json and isinstance(report_json, str):
        try:
            scan["report"] = json.loads(report_json)
        except (json.JSONDecodeError, TypeError):
            scan["report"] = None
        scan.pop("report_json", None)

    return {"scan": scan}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _persist_scan_simple(report, user_id: int | None) -> None:
    """Save a scan result (best effort)."""
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
