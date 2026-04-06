"""Writing tools routes — citation, readability, grammar, batch analysis.

Endpoints for the extended writing toolkit that complements the core
plagiarism detection pipeline.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies.rate_limit import enforce_usage_limit, record_usage
from app.services.rate_limiter import PLAN_TO_TIER, UserTier
from app.tools.citation_tool import (
    generate_citations_from_sources,
    generate_citation,
    ALL_STYLES,
)
from app.tools.readability_tool import analyze_readability
from app.tools.grammar_tool import check_grammar
from app.services.ingestion import ingest_file
from app.services.orchestrator import run_pipeline
from app.tools.web_search_tool import search_web
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["writing-tools"])


# ═══════════════════════════════════════════════════════════════════════════
# Citation Generator
# ═══════════════════════════════════════════════════════════════════════════

class CitationSourceInput(BaseModel):
    """A single source to generate citations for."""
    url: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    year: int | str | None = None
    publisher: str | None = None
    source_type: str = "Internet"
    similarity: float = 0.0


class CitationRequest(BaseModel):
    """Request for citation generation."""
    sources: list[CitationSourceInput] = Field(
        ..., min_length=1, description="Sources to generate citations for"
    )
    style: Literal["apa", "mla", "chicago", "ieee"] = Field(
        default="apa", description="Citation style"
    )


class CitationAllStylesRequest(BaseModel):
    """Generate citations in all styles for given sources."""
    sources: list[CitationSourceInput] = Field(
        ..., min_length=1, description="Sources to generate citations for"
    )


@router.post(
    "/citations/generate",
    status_code=status.HTTP_200_OK,
    summary="Generate formatted citations from sources",
)
async def generate_citations_endpoint(request: CitationRequest) -> dict:
    """Generate properly formatted citations for detected sources."""
    source_dicts = [s.model_dump() for s in request.sources]
    result = generate_citations_from_sources(source_dicts, style=request.style)
    return result


@router.post(
    "/citations/all-styles",
    status_code=status.HTTP_200_OK,
    summary="Generate citations in all styles (APA, MLA, Chicago, IEEE)",
)
async def generate_all_styles_endpoint(request: CitationAllStylesRequest) -> dict:
    """Generate citations in all four styles at once."""
    source_dicts = [s.model_dump() for s in request.sources]
    results = {}
    for style in ALL_STYLES:
        results[style] = generate_citations_from_sources(source_dicts, style=style)
    return {"styles": results}


# ═══════════════════════════════════════════════════════════════════════════
# Readability Analyzer
# ═══════════════════════════════════════════════════════════════════════════

class ReadabilityRequest(BaseModel):
    """Request for readability analysis."""
    text: str = Field(..., min_length=1, description="Text to analyze")


@router.post(
    "/readability",
    status_code=status.HTTP_200_OK,
    summary="Analyze text readability and statistics",
    dependencies=[Depends(enforce_usage_limit)],
)
async def readability_endpoint(request: ReadabilityRequest, http_request: Request = None) -> dict:
    """Compute readability scores, text statistics, and reading time."""
    logger.info("readability_requested", text_length=len(request.text))
    result = analyze_readability(request.text)
    if http_request:
        record_usage(http_request, tool_type="readability")
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Grammar & Style Checker
# ═══════════════════════════════════════════════════════════════════════════

class GrammarRequest(BaseModel):
    """Request for grammar checking."""
    text: str = Field(..., min_length=1, description="Text to check")


@router.post(
    "/grammar/check",
    status_code=status.HTTP_200_OK,
    summary="Check text for grammar, spelling, and style issues",
    dependencies=[Depends(enforce_usage_limit)],
)
async def grammar_check_endpoint(request: GrammarRequest, http_request: Request = None) -> dict:
    """Analyze text for grammar errors, style issues, and suggest fixes."""
    logger.info("grammar_check_requested", text_length=len(request.text))
    try:
        result = await check_grammar(request.text)
        if http_request:
            record_usage(http_request, tool_type="grammar")
        return result
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Grammar check failed: {exc}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Batch Upload Analysis
# ═══════════════════════════════════════════════════════════════════════════

@router.post(
    "/analyze-batch",
    status_code=status.HTTP_200_OK,
    summary="Analyze multiple files for plagiarism in batch",
    dependencies=[Depends(enforce_usage_limit)],
)
async def analyze_batch_endpoint(
    files: list[UploadFile],
    request: Request,
) -> dict:
    """Accept multiple files and run plagiarism analysis on each.

    Premium only. Pro users get up to 5 files, Premium up to 10.
    Returns a summary table with scores per document.
    """
    # --- Tier gate: require Pro or Premium ------------------------------------
    user_id: int | None = getattr(request.state, "user_id", None)
    tier = UserTier.ANONYMOUS
    if user_id:
        plan_type = getattr(request.state, "plan_type", None)
        if not plan_type:
            from app.services.auth_service import get_user_by_id
            user = get_user_by_id(user_id)
            plan_type = user.get("plan_type", "free") if user else "free"
        tier = PLAN_TO_TIER.get(plan_type, UserTier.FREE)

    if tier not in (UserTier.PRO, UserTier.PREMIUM):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Batch analysis requires a Pro or Premium plan. Upgrade at /pricing.",
        )

    max_files = (
        settings.batch_max_files_premium
        if tier == UserTier.PREMIUM
        else settings.batch_max_files_pro
    )

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file is required.",
        )

    if len(files) > max_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {max_files} files per batch on your plan.",
        )

    results: list[dict] = []
    errors: list[dict] = []

    async def _process_file(file: UploadFile) -> dict | None:
        """Process a single file, returning result dict or appending to errors."""
        if file.filename is None:
            errors.append({"filename": "unknown", "error": "Filename required"})
            return None
        try:
            file_bytes = await file.read()
            ingestion = await ingest_file(file.filename, file_bytes)

            report = await run_pipeline(
                document_id=ingestion["document_id"],
                text=ingestion["text"],
            )

            logger.info(
                "batch_file_complete",
                filename=file.filename,
                score=report.plagiarism_score,
            )
            return {
                "filename": file.filename,
                "document_id": report.document_id,
                "plagiarism_score": report.plagiarism_score,
                "confidence_score": report.confidence_score,
                "risk_level": report.risk_level.value,
                "flagged_count": len(report.flagged_passages),
                "source_count": len(report.detected_sources),
            }
        except Exception as exc:
            errors.append({
                "filename": file.filename,
                "error": str(exc),
            })
            logger.warning(
                "batch_file_error",
                filename=file.filename,
                error=str(exc),
            )
            return None

    import asyncio
    sem = asyncio.Semaphore(3)

    async def _throttled(f):
        async with sem:
            return await _process_file(f)

    outcomes = await asyncio.gather(*[_throttled(f) for f in files])
    results = [r for r in outcomes if r is not None]

    return {
        "total_files": len(files),
        "completed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Quick Check — lightweight real-time plagiarism warning for live editor
# ═══════════════════════════════════════════════════════════════════════════

class QuickCheckRequest(BaseModel):
    """Lightweight text check for real-time writing mode."""
    text: str = Field(..., min_length=20, max_length=5000, description="Text to quick-check")


@router.post(
    "/quick-check",
    status_code=status.HTTP_200_OK,
    summary="Quick plagiarism check for real-time writing assistance",
)
async def quick_check_endpoint(body: QuickCheckRequest) -> dict:
    """Perform a lightweight plagiarism check suitable for real-time feedback.

    Takes the last ~paragraph of text, searches the web for matches,
    and returns any suspicious overlaps with confidence indicators.
    Does NOT run the full multi-agent pipeline — designed for <2s response.
    """
    import time as _time
    import re as _re

    start = _time.perf_counter()
    text = body.text.strip()

    # Extract meaningful sentences for search queries
    sentences = [s.strip() for s in _re.split(r'[.!?]+', text) if len(s.strip()) > 30]
    if not sentences:
        return {"warnings": [], "sentence_count": 0, "elapsed_s": 0.0}

    # Take up to 3 most recent substantial sentences as search queries
    queries = sentences[-3:]

    warnings: list[dict] = []
    try:
        search_results = await search_web(" ".join(queries[:2]), count=5)
        results = search_results.get("results", [])

        for result in results:
            snippet = (result.get("snippet") or "").lower()
            # Check if any sentence has significant overlap with snippets
            for sent in queries:
                sent_words = set(sent.lower().split())
                snippet_words = set(snippet.split())
                if len(sent_words) < 5:
                    continue
                overlap = sent_words & snippet_words
                overlap_ratio = len(overlap) / len(sent_words)
                if overlap_ratio >= 0.5:
                    warnings.append({
                        "sentence": sent[:200],
                        "matched_url": result.get("url", ""),
                        "matched_title": result.get("title", ""),
                        "overlap_ratio": round(overlap_ratio, 2),
                        "matched_snippet": result.get("snippet", "")[:300],
                    })
                    break  # one warning per search result

    except Exception as exc:
        logger.warning("quick_check_search_failed", error=str(exc))

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_warnings: list[dict] = []
    for w in warnings:
        if w["matched_url"] not in seen_urls:
            seen_urls.add(w["matched_url"])
            unique_warnings.append(w)

    elapsed = round(_time.perf_counter() - start, 3)

    return {
        "warnings": unique_warnings[:5],
        "warning_count": len(unique_warnings),
        "sentence_count": len(sentences),
        "elapsed_s": elapsed,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Citation for Source — generate citations for a single source in all styles
# ═══════════════════════════════════════════════════════════════════════════

class SourceCitationRequest(BaseModel):
    """Generate citations for a single source."""
    url: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    year: int | str | None = None
    publisher: str | None = None


@router.post(
    "/citations/for-source",
    status_code=status.HTTP_200_OK,
    summary="Generate citations in all styles for a single source",
)
async def citation_for_source_endpoint(body: SourceCitationRequest) -> dict:
    """Generate APA, MLA, Chicago, and IEEE citations for a single source.

    Useful for the auto-citation insertion feature in the report view.
    """
    source_dict = body.model_dump()
    source_dict["similarity"] = 0.0
    source_dict["source_type"] = "Internet"

    result: dict[str, str] = {}
    for style in ALL_STYLES:
        cit_data = generate_citations_from_sources([source_dict], style=style)
        citations = cit_data.get("citations", [])
        if citations:
            result[style] = citations[0]["citation"]

    return {"citations": result, "source": {"url": body.url, "title": body.title}}
