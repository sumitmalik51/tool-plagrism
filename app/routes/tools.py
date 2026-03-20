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

from app.tools.ai_detection_tool import detect_ai_text
from app.tools.content_extractor_tool import chunk_text, extract_text
from app.tools.embedding_tool import generate_embeddings_sync
from app.tools.similarity_tool import run_similarity_analysis
from app.tools.web_search_tool import search_web
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
    count: int = Field(default=5, ge=1, le=50, description="Number of results")


class AIDetectRequest(BaseModel):
    """Input for the AI detection endpoint."""
    text: str = Field(..., min_length=1, description="Text to analyse")
    chunks: list[str] | None = Field(default=None, description="Optional pre-split chunks")


class ChunkRequest(BaseModel):
    """Input for the content extraction / chunking endpoint."""
    text: str = Field(..., min_length=1, description="Text to chunk")
    chunk_size: int | None = Field(default=None, ge=50, description="Target chunk size")
    overlap: int | None = Field(default=None, ge=0, description="Overlap between chunks")


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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Embedding generation failed: {exc}",
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Similarity analysis failed: {exc}",
        )


@router.post("/web-search", summary="Search the web for matching content")
async def web_search_endpoint(request: WebSearchRequest) -> dict:
    """Search the web using Bing Search API."""
    logger.info("tool_api_web_search", query=request.query[:80])
    try:
        return await search_web(request.query, count=request.count)
    except Exception as exc:
        logger.error("tool_api_web_search_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Web search failed: {exc}",
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI detection failed: {exc}",
        )
