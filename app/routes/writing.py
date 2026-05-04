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
from app.dependencies.rate_limit import (
    enforce_usage_limit,
    enforce_word_quota,
    get_request_plan_type,
    record_usage,
)
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
# Writing Improvement Suggestions (for flagged passages)
# ═══════════════════════════════════════════════════════════════════════════

class ImprovementRequest(BaseModel):
    """Request to get rewrite/citation suggestions for flagged passages."""
    document_id: str = Field(..., description="Scan document ID")


@router.post(
    "/improvement-suggestions",
    status_code=status.HTTP_200_OK,
    summary="Get rewrite and citation suggestions for flagged passages",
)
async def improvement_suggestions_endpoint(
    body: ImprovementRequest, request: Request,
) -> dict:
    """Analyze flagged passages from a completed scan and suggest how to
    properly paraphrase or cite each one."""
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    from app.services.database import get_db
    import json as _json

    db = get_db()
    scan = db.fetch_one(
        "SELECT report_json FROM scans WHERE document_id = ? AND user_id = ?",
        (body.document_id, user_id),
    )
    if not scan or not scan.get("report_json"):
        raise HTTPException(status_code=404, detail="Scan not found")

    report_data = _json.loads(scan["report_json"])
    flagged = report_data.get("flagged_passages", [])
    sources = report_data.get("detected_sources", [])

    # Build source lookup by URL
    source_map = {s.get("url", ""): s for s in sources if s.get("url")}

    suggestions = []
    for i, fp in enumerate(flagged[:20]):
        text = fp.get("text", "")
        sim = fp.get("similarity_score", 0)
        source_url = fp.get("source", "")
        source_info = source_map.get(source_url, {})

        suggestion = {
            "passage_index": i,
            "original_text": text[:300],
            "similarity_score": sim,
            "source_url": source_url,
            "source_title": source_info.get("title", "Unknown Source"),
        }

        # Generate rewrite suggestion (simple paraphrase guidance)
        if sim > 0.7:
            suggestion["action"] = "rewrite_required"
            suggestion["advice"] = (
                "This passage closely matches the source. Rewrite it entirely in your own words, "
                "or quote it directly with proper citation."
            )
        elif sim > 0.4:
            suggestion["action"] = "paraphrase_and_cite"
            suggestion["advice"] = (
                "This passage has moderate overlap. Paraphrase the key ideas and add an in-text citation."
            )
        else:
            suggestion["action"] = "add_citation"
            suggestion["advice"] = (
                "Minor overlap detected. Adding a citation to acknowledge the source should suffice."
            )

        # Generate citation for the source
        if source_info:
            citation_input = {
                "url": source_url,
                "title": source_info.get("title"),
                "source_type": source_info.get("source_type", "Internet"),
            }
            try:
                from app.tools.citation_tool import generate_citation
                citation = generate_citation(citation_input, style="apa")
                suggestion["suggested_citation"] = citation
            except Exception:
                suggestion["suggested_citation"] = None
        else:
            suggestion["suggested_citation"] = None

        suggestions.append(suggestion)

    return {
        "document_id": body.document_id,
        "total_flagged": len(flagged),
        "suggestions": suggestions,
    }

# ═══════════════════════════════════════════════════════════════════════════
class ScanComparisonRequest(BaseModel):
    """Compare two scans side-by-side."""
    document_id_a: str = Field(..., description="First scan document ID")
    document_id_b: str = Field(..., description="Second scan document ID")


@router.post(
    "/compare-scans",
    status_code=status.HTTP_200_OK,
    summary="Compare two scan results side-by-side",
)
async def compare_scans_endpoint(
    body: ScanComparisonRequest, request: Request,
) -> dict:
    """Return a diff-style comparison of two scans showing score changes,
    new/removed flagged passages, and source differences."""
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    from app.services.database import get_db
    import json as _json

    db = get_db()
    scan_a = db.fetch_one(
        "SELECT * FROM scans WHERE document_id = ? AND user_id = ?",
        (body.document_id_a, user_id),
    )
    scan_b = db.fetch_one(
        "SELECT * FROM scans WHERE document_id = ? AND user_id = ?",
        (body.document_id_b, user_id),
    )

    if not scan_a:
        raise HTTPException(status_code=404, detail=f"Scan A not found: {body.document_id_a}")
    if not scan_b:
        raise HTTPException(status_code=404, detail=f"Scan B not found: {body.document_id_b}")

    report_a = _json.loads(scan_a.get("report_json", "{}")) if scan_a.get("report_json") else {}
    report_b = _json.loads(scan_b.get("report_json", "{}")) if scan_b.get("report_json") else {}

    # Score comparison
    score_diff = {
        "plagiarism_score": {
            "a": scan_a.get("plagiarism_score", 0),
            "b": scan_b.get("plagiarism_score", 0),
            "change": round((scan_b.get("plagiarism_score", 0) - scan_a.get("plagiarism_score", 0)), 2),
        },
        "confidence_score": {
            "a": scan_a.get("confidence_score", 0),
            "b": scan_b.get("confidence_score", 0),
            "change": round((scan_b.get("confidence_score", 0) - scan_a.get("confidence_score", 0)), 2),
        },
        "risk_level": {
            "a": scan_a.get("risk_level", "LOW"),
            "b": scan_b.get("risk_level", "LOW"),
        },
        "sources_count": {
            "a": scan_a.get("sources_count", 0),
            "b": scan_b.get("sources_count", 0),
            "change": (scan_b.get("sources_count", 0) - scan_a.get("sources_count", 0)),
        },
        "flagged_count": {
            "a": scan_a.get("flagged_count", 0),
            "b": scan_b.get("flagged_count", 0),
            "change": (scan_b.get("flagged_count", 0) - scan_a.get("flagged_count", 0)),
        },
    }

    # Source comparison — find new, removed, and common sources
    sources_a = {s.get("url", ""): s for s in report_a.get("detected_sources", []) if s.get("url")}
    sources_b = {s.get("url", ""): s for s in report_b.get("detected_sources", []) if s.get("url")}

    urls_a = set(sources_a.keys())
    urls_b = set(sources_b.keys())

    new_sources = [sources_b[u] for u in (urls_b - urls_a)]
    removed_sources = [sources_a[u] for u in (urls_a - urls_b)]
    common_sources = []
    for u in (urls_a & urls_b):
        common_sources.append({
            "url": u,
            "title": sources_b[u].get("title", sources_a[u].get("title", "")),
            "similarity_a": sources_a[u].get("similarity", 0),
            "similarity_b": sources_b[u].get("similarity", 0),
        })

    # Passage comparison — find new and resolved passages
    passages_a_texts = {p.get("text", "").lower().strip() for p in report_a.get("flagged_passages", [])}
    passages_b_texts = {p.get("text", "").lower().strip() for p in report_b.get("flagged_passages", [])}

    new_passages = [p for p in report_b.get("flagged_passages", [])
                    if p.get("text", "").lower().strip() not in passages_a_texts]
    resolved_passages = [p for p in report_a.get("flagged_passages", [])
                         if p.get("text", "").lower().strip() not in passages_b_texts]

    return {
        "scan_a": {
            "document_id": body.document_id_a,
            "created_at": str(scan_a.get("created_at", "")),
        },
        "scan_b": {
            "document_id": body.document_id_b,
            "created_at": str(scan_b.get("created_at", "")),
        },
        "score_diff": score_diff,
        "new_sources": new_sources[:20],
        "removed_sources": removed_sources[:20],
        "common_sources": common_sources[:20],
        "new_passages": [{"text": p.get("text", "")[:200], "source": p.get("source", "")}
                         for p in new_passages[:15]],
        "resolved_passages": [{"text": p.get("text", "")[:200], "source": p.get("source", "")}
                              for p in resolved_passages[:15]],
    }


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
    dependencies=[Depends(enforce_usage_limit)],
)
async def generate_citations_endpoint(request: CitationRequest, http_request: Request = None) -> dict:
    """Generate properly formatted citations for detected sources."""
    source_dicts = [s.model_dump() for s in request.sources]
    result = generate_citations_from_sources(source_dicts, style=request.style)
    if http_request:
        record_usage(http_request, tool_type="citation")
    return result


@router.post(
    "/citations/all-styles",
    status_code=status.HTTP_200_OK,
    summary="Generate citations in all styles (APA, MLA, Chicago, IEEE)",
    dependencies=[Depends(enforce_usage_limit)],
)
async def generate_all_styles_endpoint(request: CitationAllStylesRequest, http_request: Request = None) -> dict:
    """Generate citations in all four styles at once."""
    source_dicts = [s.model_dump() for s in request.sources]
    results = {}
    for style in ALL_STYLES:
        results[style] = generate_citations_from_sources(source_dicts, style=style)
    if http_request:
        record_usage(http_request, tool_type="citation")
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
    word_count = len(request.text.split())
    if http_request:
        enforce_word_quota(http_request, word_count, "readability analysis")
    result = analyze_readability(request.text)
    if http_request:
        record_usage(http_request, tool_type="readability", word_count=word_count)
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
    word_count = len(request.text.split())
    if http_request:
        enforce_word_quota(http_request, word_count, "grammar check")
    try:
        result = await check_grammar(request.text)
        if http_request:
            record_usage(http_request, tool_type="grammar", word_count=word_count)
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
    plan_type = get_request_plan_type(request)
    tier = PLAN_TO_TIER.get(plan_type, UserTier.FREE) if user_id else UserTier.ANONYMOUS

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

    errors: list[dict] = []
    ingestions: list[dict] = []

    for file in files:
        if file.filename is None:
            errors.append({"filename": "unknown", "error": "Filename required"})
            continue
        try:
            file_bytes = await file.read()
            ingestion = await ingest_file(file.filename, file_bytes, plan_type=plan_type)
            ingestions.append(ingestion)
        except Exception as exc:
            errors.append({"filename": file.filename, "error": str(exc)})
            logger.warning("batch_file_ingest_error", filename=file.filename, error=str(exc))

    total_word_count = sum(len(item["text"].split()) for item in ingestions)
    if ingestions:
        enforce_word_quota(request, total_word_count, "batch")

    async def _process_file(ingestion: dict) -> dict | None:
        """Process a single file, returning result dict or appending to errors."""
        filename = ingestion.get("filename") or "unknown"
        try:
            report = await run_pipeline(
                document_id=ingestion["document_id"],
                text=ingestion["text"],
                plan_type=plan_type,
            )

            logger.info(
                "batch_file_complete",
                filename=filename,
                score=report.plagiarism_score,
            )
            return {
                "filename": filename,
                "document_id": report.document_id,
                "plagiarism_score": report.plagiarism_score,
                "confidence_score": report.confidence_score,
                "risk_level": report.risk_level.value,
                "flagged_count": len(report.flagged_passages),
                "source_count": len(report.detected_sources),
            }
        except Exception as exc:
            errors.append({
                "filename": filename,
                "error": str(exc),
            })
            logger.warning(
                "batch_file_error",
                filename=filename,
                error=str(exc),
            )
            return None

    import asyncio
    sem = asyncio.Semaphore(settings.batch_analysis_concurrency)

    async def _throttled(item):
        async with sem:
            return await _process_file(item)

    outcomes = await asyncio.gather(*[_throttled(item) for item in ingestions])
    results = [r for r in outcomes if r is not None]

    if results:
        record_usage(request, tool_type="batch_analysis", word_count=total_word_count)

    return {
        "total_files": len(files),
        "completed": len(results),
        "failed": len(errors),
        "total_word_count": total_word_count,
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
    dependencies=[Depends(enforce_usage_limit)],
)
async def quick_check_endpoint(body: QuickCheckRequest, http_request: Request = None) -> dict:
    """Perform a lightweight plagiarism check suitable for real-time feedback.

    Takes the last ~paragraph of text, searches the web for matches,
    and returns any suspicious overlaps with confidence indicators.
    Does NOT run the full multi-agent pipeline — designed for <2s response.
    """
    import time as _time
    import re as _re

    start = _time.perf_counter()
    text = body.text.strip()
    word_count = len(text.split())
    if http_request:
        enforce_word_quota(http_request, word_count, "quick check")

    # Extract meaningful sentences for search queries
    sentences = [s.strip() for s in _re.split(r'[.!?]+', text) if len(s.strip()) > 30]
    if not sentences:
        if http_request:
            record_usage(http_request, tool_type="quick_check", word_count=word_count)
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

    if http_request:
        record_usage(http_request, tool_type="quick_check", word_count=word_count)

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
    dependencies=[Depends(enforce_usage_limit)],
)
async def citation_for_source_endpoint(body: SourceCitationRequest, http_request: Request = None) -> dict:
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

    if http_request:
        record_usage(http_request, tool_type="citation")
    return {"citations": result, "source": {"url": body.url, "title": body.title}}
