"""Writing tools routes — citation, readability, grammar, batch analysis.

Endpoints for the extended writing toolkit that complements the core
plagiarism detection pipeline.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.tools.citation_tool import (
    generate_citations_from_sources,
    generate_citation,
    ALL_STYLES,
)
from app.tools.readability_tool import analyze_readability
from app.tools.grammar_tool import check_grammar
from app.services.ingestion import ingest_file
from app.services.orchestrator import run_pipeline
from app.config import settings
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
    text: str = Field(..., min_length=1, max_length=500_000, description="Text to analyze")


@router.post(
    "/readability",
    status_code=status.HTTP_200_OK,
    summary="Analyze text readability and statistics",
)
async def readability_endpoint(request: ReadabilityRequest) -> dict:
    """Compute readability scores, text statistics, and reading time."""
    logger.info("readability_requested", text_length=len(request.text))
    return analyze_readability(request.text)


# ═══════════════════════════════════════════════════════════════════════════
# Grammar & Style Checker
# ═══════════════════════════════════════════════════════════════════════════

class GrammarRequest(BaseModel):
    """Request for grammar checking."""
    text: str = Field(..., min_length=1, max_length=100_000, description="Text to check")


@router.post(
    "/grammar/check",
    status_code=status.HTTP_200_OK,
    summary="Check text for grammar, spelling, and style issues",
)
async def grammar_check_endpoint(request: GrammarRequest) -> dict:
    """Analyze text for grammar errors, style issues, and suggest fixes."""
    logger.info("grammar_check_requested", text_length=len(request.text))
    try:
        result = await check_grammar(request.text)
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
)
async def analyze_batch_endpoint(files: list[UploadFile]) -> dict:
    """Accept multiple files and run plagiarism analysis on each.

    Returns a summary table with scores per document.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file is required.",
        )

    if len(files) > settings.batch_max_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {settings.batch_max_files} files per batch.",
        )

    results: list[dict] = []
    errors: list[dict] = []

    for file in files:
        if file.filename is None:
            errors.append({"filename": "unknown", "error": "Filename required"})
            continue

        try:
            file_bytes = await file.read()
            ingestion = await ingest_file(file.filename, file_bytes)

            report = await run_pipeline(
                document_id=ingestion["document_id"],
                text=ingestion["text"],
            )

            results.append({
                "filename": file.filename,
                "document_id": report.document_id,
                "plagiarism_score": report.plagiarism_score,
                "confidence_score": report.confidence_score,
                "risk_level": report.risk_level.value,
                "flagged_count": len(report.flagged_passages),
                "source_count": len(report.detected_sources),
            })

            logger.info(
                "batch_file_complete",
                filename=file.filename,
                score=report.plagiarism_score,
            )

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

    return {
        "total_files": len(files),
        "completed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }
