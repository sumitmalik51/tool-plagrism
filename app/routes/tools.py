"""Tool API routes — exposes each tool as an independent FastAPI endpoint.

Each endpoint:
  • Validates input using Pydantic models
  • Calls the corresponding tool function
  • Returns structured JSON response
  • Is independently accessible for Azure Foundry Agent orchestration
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.exceptions import ExternalServiceError, ValidationError
from app.tools.ai_detection_tool import detect_ai_text
from app.tools.content_extractor_tool import chunk_text, extract_text
from app.tools.embedding_tool import generate_embeddings_sync
from app.tools.similarity_tool import run_similarity_analysis
from app.tools.web_search_tool import search_web
from app.tools.scholar_tool import search_scholar
from app.tools.openalex_tool import search_openalex
from app.tools.arxiv_tool import search_arxiv
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class EmbeddingsRequest(BaseModel):
    """Input for the embeddings endpoint."""
    texts: list[str] = Field(..., min_length=1, description="List of text strings to embed")


class SimilarityRequest(BaseModel):
    """Input for the similarity endpoint."""
    texts_a: list[str] = Field(..., min_length=1, description="First set of texts")
    texts_b: list[str] = Field(..., min_length=1, description="Second set of texts")
    embeddings_a: list[list[float]] = Field(..., description="Embeddings for texts_a")
    embeddings_b: list[list[float]] = Field(..., description="Embeddings for texts_b")
    threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="Similarity threshold")


class WebSearchRequest(BaseModel):
    """Input for the web search endpoint."""
    query: str = Field(..., min_length=1, description="Search query")
    count: int = Field(default=10, ge=1, le=50, description="Number of results")


class AIDetectRequest(BaseModel):
    """Input for the AI detection endpoint."""
    text: str = Field(..., min_length=1, description="Text to analyse")
    chunks: list[str] | None = Field(default=None, description="Optional pre-split chunks")


class ScholarSearchRequest(BaseModel):
    """Input for the Google Scholar search endpoint."""
    query: str = Field(..., min_length=1, description="Search query for academic papers")
    max_results: int = Field(default=10, ge=1, le=20, description="Maximum number of results")


class ChunkRequest(BaseModel):
    """Input for the content extraction / chunking endpoint."""
    text: str = Field(..., min_length=1, description="Text to chunk")
    chunk_size: int | None = Field(default=None, ge=50, description="Target chunk size")
    overlap: int | None = Field(default=None, ge=0, description="Overlap between chunks")


class FlaggedPassageInput(BaseModel):
    """A single flagged passage for report generation."""
    text: str = Field(..., description="The flagged text passage")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Similarity score")
    source: str | None = Field(default=None, description="Source URL or reference")
    reason: str = Field(default="", description="Why this passage was flagged")


class DetectedSourceInput(BaseModel):
    """A detected source for report generation."""
    url: str | None = Field(default=None, description="URL of the matched source")
    title: str | None = Field(default=None, description="Title of the matched source")
    similarity: float = Field(..., ge=0.0, le=1.0, description="Similarity with the source")


class GenerateReportRequest(BaseModel):
    """Input for the report generation endpoint."""
    document_id: str = Field(..., description="Unique identifier for the document")
    plagiarism_score: float = Field(..., ge=0.0, le=100.0, description="Overall plagiarism score (0-100)")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Overall confidence (0-1)")
    ai_score: float | None = Field(default=None, ge=0.0, le=100.0, description="AI detection score (0-100)")
    flagged_passages: list[FlaggedPassageInput] = Field(default_factory=list, description="Flagged passages")
    detected_sources: list[DetectedSourceInput] = Field(default_factory=list, description="Detected sources")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/embeddings", summary="Generate text embeddings")
async def embeddings_endpoint(request: EmbeddingsRequest) -> dict:
    """Generate normalized vector embeddings for a list of text strings."""
    logger.info("tool_api_embeddings", text_count=len(request.texts))
    try:
        return generate_embeddings_sync(request.texts)
    except Exception as exc:
        logger.error("tool_api_embeddings_error", error=str(exc))
        raise ExternalServiceError(
            service_name="embedding_service",
            detail="Could not generate embeddings. Please try again.",
        )


@router.post("/similarity", summary="Compute text similarity")
async def similarity_endpoint(request: SimilarityRequest) -> dict:
    """Compute cosine similarity between two sets of pre-computed embeddings."""
    logger.info(
        "tool_api_similarity",
        texts_a=len(request.texts_a),
        texts_b=len(request.texts_b),
    )
    try:
        return run_similarity_analysis(
            texts_a=request.texts_a,
            texts_b=request.texts_b,
            embeddings_a=request.embeddings_a,
            embeddings_b=request.embeddings_b,
            threshold=request.threshold,
        )
    except Exception as exc:
        logger.error("tool_api_similarity_error", error=str(exc))
        raise ExternalServiceError(
            service_name="similarity_engine",
            detail="Could not compute similarity. Please try again.",
        )


@router.post("/web-search", summary="Search the web for matching content")
async def web_search_endpoint(request: WebSearchRequest) -> dict:
    """Search the web using Bing Search API."""
    logger.info("tool_api_web_search", query=request.query[:80])
    try:
        return await search_web(request.query, count=request.count)
    except Exception as exc:
        logger.error("tool_api_web_search_error", error=str(exc))
        raise ExternalServiceError(
            service_name="web_search",
            detail="Search service temporarily unavailable. Please try again.",
        )


@router.post("/scholar-search", summary="Search Google Scholar for academic papers")
async def scholar_search_endpoint(request: ScholarSearchRequest) -> dict:
    """Search Google Scholar for academic papers matching the query.

    Returns titles, authors, year, abstract snippets, citation counts,
    and URLs for matching publications.
    """
    logger.info("tool_api_scholar_search", query=request.query[:80])
    try:
        return await search_scholar(request.query, max_results=request.max_results)
    except Exception as exc:
        logger.error("tool_api_scholar_search_error", error=str(exc))
        raise ExternalServiceError(
            service_name="google_scholar",
            detail="Scholar search temporarily unavailable. Please try again.",
        )


@router.post("/openalex-search", summary="Search OpenAlex for academic papers")
async def openalex_search_endpoint(request: ScholarSearchRequest) -> dict:
    """Search OpenAlex for academic papers matching the query.

    Free, reliable alternative to Google Scholar. No API key needed.
    Returns titles, authors, year, abstracts, citation counts, and URLs.
    """
    logger.info("tool_api_openalex_search", query=request.query[:80])
    try:
        return await search_openalex(request.query, max_results=request.max_results)
    except Exception as exc:
        logger.error("tool_api_openalex_search_error", error=str(exc))
        raise ExternalServiceError(
            service_name="openalex",
            detail="OpenAlex service temporarily unavailable. Please try again.",
        )


@router.post("/arxiv-search", summary="Search arXiv for academic papers")
async def arxiv_search_endpoint(request: ScholarSearchRequest) -> dict:
    """Search arXiv for academic preprints matching the query.

    Free, no API key needed. Returns titles, authors, year, abstracts,
    arXiv IDs, PDF URLs, and categories.
    """
    logger.info("tool_api_arxiv_search", query=request.query[:80])
    try:
        return await search_arxiv(request.query, max_results=request.max_results)
    except Exception as exc:
        logger.error("tool_api_arxiv_search_error", error=str(exc))
        raise ExternalServiceError(
            service_name="arxiv",
            detail="arXiv service temporarily unavailable. Please try again.",
        )


@router.post("/content-extract", summary="Extract text from uploaded file")
async def content_extract_endpoint(file: UploadFile) -> dict:
    """Extract text content from a PDF, DOCX, or TXT file."""
    if file.filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required.",
        )
    logger.info("tool_api_content_extract", filename=file.filename)
    file_bytes = await file.read()
    try:
        return await extract_text(file_bytes, file.filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.post("/chunk", summary="Split text into chunks")
async def chunk_endpoint(request: ChunkRequest) -> dict:
    """Split text into overlapping chunks for analysis."""
    logger.info("tool_api_chunk", text_length=len(request.text))
    return chunk_text(
        text=request.text,
        chunk_size=request.chunk_size,
        overlap=request.overlap,
    )


@router.post("/ai-detect", summary="Detect AI-generated text")
async def ai_detect_endpoint(request: AIDetectRequest) -> dict:
    """Analyse text for AI-generated content indicators."""
    logger.info("tool_api_ai_detect", text_length=len(request.text))
    try:
        return await detect_ai_text(request.text, chunks=request.chunks)
    except Exception as exc:
        logger.error("tool_api_ai_detect_error", error=str(exc))
        raise ExternalServiceError(
            service_name="ai_detection",
            detail="AI detection service temporarily unavailable. Please try again.",
        )


@router.post("/generate-report", summary="Generate structured plagiarism report")
async def generate_report_endpoint(request: GenerateReportRequest) -> dict:
    """Generate a structured plagiarism report from pre-computed analysis results.

    Accepts plagiarism scores, confidence, flagged passages, and detected
    sources, then produces a structured JSON report with risk level,
    human-readable explanation, and all flagged passages.
    """
    from datetime import datetime, timezone

    logger.info(
        "tool_api_generate_report",
        document_id=request.document_id,
        plagiarism_score=request.plagiarism_score,
    )

    # --- Determine risk level (match thresholds from config) -------------------
    from app.config import settings as _settings

    if request.plagiarism_score >= _settings.risk_threshold_high and request.confidence_score >= 0.4:
        risk_level = "HIGH"
    elif request.plagiarism_score >= _settings.risk_threshold_medium:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # --- Build explanation ----------------------------------------------------
    explanation_parts: list[str] = []

    explanation_parts.append(
        f"Plagiarism analysis complete for document '{request.document_id}'."
    )
    explanation_parts.append(
        f"Overall plagiarism score: {request.plagiarism_score:.1f}/100 "
        f"(confidence: {request.confidence_score:.0%})."
    )
    explanation_parts.append(f"Risk level: {risk_level}.")

    if request.ai_score is not None:
        explanation_parts.append(
            f"AI-generated content likelihood: {request.ai_score:.1f}/100."
        )

    if request.flagged_passages:
        explanation_parts.append(
            f"{len(request.flagged_passages)} passage(s) flagged for review."
        )
        top_score = max(p.similarity_score for p in request.flagged_passages)
        explanation_parts.append(
            f"Highest passage similarity: {top_score:.0%}."
        )

    if request.detected_sources:
        explanation_parts.append(
            f"{len(request.detected_sources)} potential source(s) identified."
        )

    if risk_level == "HIGH":
        explanation_parts.append(
            "Recommendation: Manual review strongly recommended. "
            "Multiple passages show high similarity to external sources."
        )
    elif risk_level == "MEDIUM":
        explanation_parts.append(
            "Recommendation: Review flagged passages. Some sections may "
            "require paraphrasing or proper citation."
        )
    else:
        explanation_parts.append(
            "Recommendation: No significant plagiarism detected. "
            "The document appears to be largely original."
        )

    explanation = " ".join(explanation_parts)

    # --- Assemble report ------------------------------------------------------
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    report = {
        "document_id": request.document_id,
        "plagiarism_score": request.plagiarism_score,
        "confidence_score": request.confidence_score,
        "risk_level": risk_level,
        "flagged_passages": [
            {
                "text": p.text,
                "similarity_score": p.similarity_score,
                "source": p.source,
                "reason": p.reason,
            }
            for p in request.flagged_passages
        ],
        "detected_sources": [
            {
                "url": s.url,
                "title": s.title,
                "similarity": s.similarity,
            }
            for s in request.detected_sources
        ],
        "explanation": explanation,
        "generated_at": generated_at,
    }

    if request.ai_score is not None:
        report["ai_score"] = request.ai_score

    logger.info(
        "report_generated",
        document_id=request.document_id,
        risk_level=risk_level,
        flagged_count=len(request.flagged_passages),
    )

    return report


# ---------------------------------------------------------------------------
# BibTeX export
# ---------------------------------------------------------------------------

class BibTexPaperInput(BaseModel):
    """A single paper for BibTeX export."""
    title: str = Field(..., description="Paper title")
    authors: list[str] = Field(default_factory=list, description="List of author names")
    year: str = Field(default="", description="Publication year")
    abstract: str = Field(default="", description="Paper abstract")
    url: str = Field(default="", description="URL or DOI")
    venue: str = Field(default="", description="Journal/conference name")
    arxiv_id: str = Field(default="", description="arXiv ID (if applicable)")
    doi: str = Field(default="", description="DOI (if applicable)")


class BibTexExportRequest(BaseModel):
    """Input for the BibTeX export endpoint."""
    papers: list[BibTexPaperInput] = Field(..., min_length=1, description="List of papers to export")


@router.post("/bibtex-export", summary="Export papers as BibTeX")
async def bibtex_export_endpoint(request: BibTexExportRequest) -> dict:
    """Convert a list of paper metadata to BibTeX format.

    Accepts papers from OpenAlex, arXiv, or Scholar search results and
    produces a valid BibTeX string for import into reference managers.
    """
    from app.tools.bibtex_tool import papers_to_bibtex

    logger.info("tool_api_bibtex_export", paper_count=len(request.papers))
    papers = [p.model_dump() for p in request.papers]
    bibtex_str = papers_to_bibtex(papers)
    return {
        "bibtex": bibtex_str,
        "entry_count": len(request.papers),
    }


# ---------------------------------------------------------------------------
# Semantic Scholar author lookup
# ---------------------------------------------------------------------------

class AuthorSearchRequest(BaseModel):
    """Input for the author search endpoint."""
    query: str = Field(..., min_length=1, description="Author name to search for")
    max_results: int = Field(default=5, ge=1, le=20, description="Maximum number of results")


class AuthorPapersRequest(BaseModel):
    """Input for the author papers endpoint."""
    author_id: str = Field(..., min_length=1, description="Semantic Scholar author ID")
    max_results: int = Field(default=10, ge=1, le=50, description="Maximum number of papers")


@router.post("/author-lookup", summary="Search for authors via Semantic Scholar")
async def author_lookup_endpoint(request: AuthorSearchRequest) -> dict:
    """Search Semantic Scholar for academic authors matching the query.

    Returns author profiles with name, affiliations, paper count,
    citation count, and h-index.
    """
    from app.tools.semantic_scholar_tool import search_authors

    logger.info("tool_api_author_lookup", query=request.query[:80])
    try:
        return await search_authors(request.query, max_results=request.max_results)
    except Exception as exc:
        logger.error("tool_api_author_lookup_error", error=str(exc))
        raise ExternalServiceError(
            service_name="semantic_scholar",
            detail="Semantic Scholar service temporarily unavailable. Please try again.",
        )


@router.post("/author-papers", summary="Get author's publications")
async def author_papers_endpoint(request: AuthorPapersRequest) -> dict:
    """Get an author's publications from Semantic Scholar.

    Returns papers with title, year, citation count, venue, and URL.
    """
    from app.tools.semantic_scholar_tool import get_author_papers

    logger.info("tool_api_author_papers", author_id=request.author_id)
    try:
        return await get_author_papers(request.author_id, max_results=request.max_results)
    except Exception as exc:
        logger.error("tool_api_author_papers_error", error=str(exc))
        raise ExternalServiceError(
            service_name="semantic_scholar",
            detail="Semantic Scholar service temporarily unavailable. Please try again.",
        )


# ---------------------------------------------------------------------------
# Semantic relevance scoring
# ---------------------------------------------------------------------------

class RelevanceResultInput(BaseModel):
    """A single result item for relevance scoring."""
    title: str = Field(default="", description="Title of the result")
    abstract: str = Field(default="", description="Abstract or snippet text")


class RelevanceScoreRequest(BaseModel):
    """Input for the relevance scoring endpoint."""
    query: str = Field(..., min_length=1, description="Query text to compare against")
    results: list[RelevanceResultInput] = Field(..., min_length=1, description="Results to score")
    min_score: float = Field(default=0.15, ge=0.0, le=1.0, description="Minimum relevance score")


@router.post("/relevance-score", summary="Score search results by semantic relevance")
async def relevance_score_endpoint(request: RelevanceScoreRequest) -> dict:
    """Score and rank search results by their semantic relevance to a query.

    Adds a ``relevance_score`` to each result and returns them sorted
    by relevance (highest first). Results below ``min_score`` are filtered out.
    """
    from app.tools.relevance_scorer import score_relevance

    logger.info("tool_api_relevance_score", result_count=len(request.results))
    results = [r.model_dump() for r in request.results]
    try:
        scored = await score_relevance(
            request.query, results,
            text_key="abstract", fallback_key="title",
            min_score=request.min_score,
        )
        return {"results": scored, "count": len(scored)}
    except Exception as exc:
        logger.error("tool_api_relevance_score_error", error=str(exc))
        raise ExternalServiceError(
            service_name="relevance_scorer",
            detail="Relevance scoring temporarily unavailable. Please try again.",
        )
