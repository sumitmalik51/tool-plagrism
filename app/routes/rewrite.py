"""Rewrite route — AI-powered plagiarism rewriting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.tools.rewriter_tool import rewrite_paragraph, rewrite_document
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["rewrite"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class RewriteParagraphRequest(BaseModel):
    """Request body for paragraph rewriting."""

    text: str = Field(..., min_length=1, description="The flagged paragraph to rewrite")
    context: str = Field(default="", description="Surrounding text for context")
    tone: str = Field(default="academic", description="Writing tone: academic, professional, casual")


class RewriteParagraphResponse(BaseModel):
    """Response for paragraph rewriting."""

    original: str
    rewritten: str
    tone: str
    elapsed_s: float


class RewriteDocumentRequest(BaseModel):
    """Request body for full document rewriting."""

    text: str = Field(..., min_length=1, description="The full document text")
    flagged_passages: list[str] = Field(
        default_factory=list,
        description="Passages flagged as plagiarised (will be targeted for rewriting)",
    )
    tone: str = Field(default="academic", description="Writing tone: academic, professional, casual")


class RewriteDocumentResponse(BaseModel):
    """Response for document rewriting."""

    original: str
    rewritten: str
    passages_rewritten: int
    tone: str
    elapsed_s: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/rewrite/paragraph",
    response_model=RewriteParagraphResponse,
    status_code=status.HTTP_200_OK,
    summary="Rewrite a single paragraph to eliminate plagiarism",
)
async def rewrite_paragraph_endpoint(
    request: RewriteParagraphRequest,
) -> RewriteParagraphResponse:
    """Accept a flagged paragraph, rewrite it using AI, and return the
    rewritten version with the original preserved for comparison."""
    logger.info(
        "rewrite_paragraph_requested",
        text_length=len(request.text),
        tone=request.tone,
    )

    try:
        result = await rewrite_paragraph(
            text=request.text,
            context=request.context,
            tone=request.tone,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI rewrite failed: {exc}",
        )

    return RewriteParagraphResponse(**result)


@router.post(
    "/rewrite/document",
    response_model=RewriteDocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Rewrite flagged passages in a full document to eliminate plagiarism",
)
async def rewrite_document_endpoint(
    request: RewriteDocumentRequest,
) -> RewriteDocumentResponse:
    """Accept a full document and a list of flagged passages, rewrite
    only the flagged sections using AI, and return the complete document
    with rewrites applied."""
    logger.info(
        "rewrite_document_requested",
        doc_length=len(request.text),
        flagged_count=len(request.flagged_passages),
        tone=request.tone,
    )

    try:
        result = await rewrite_document(
            document_text=request.text,
            flagged_passages=request.flagged_passages,
            tone=request.tone,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI rewrite failed: {exc}",
        )

    return RewriteDocumentResponse(**result)
