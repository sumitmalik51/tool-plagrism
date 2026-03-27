"""Pydantic schemas for API requests, responses, and agent outputs."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Plagiarism risk classification."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FileType(str, Enum):
    """Supported file types for upload."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    TEX = "tex"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    """Response returned after a successful file upload."""

    document_id: str = Field(..., description="Unique identifier for the uploaded document")
    filename: str = Field(..., description="Original file name")
    file_type: FileType = Field(..., description="Detected file type")
    char_count: int = Field(..., ge=0, description="Number of characters in extracted text")
    message: str = Field(default="File uploaded and text extracted successfully")


# ---------------------------------------------------------------------------
# Agent I/O
# ---------------------------------------------------------------------------

class AgentInput(BaseModel):
    """Standard input schema passed to every detection agent."""

    document_id: str = Field(..., description="Document identifier")
    text: str = Field(..., min_length=1, description="Full extracted text")
    chunks: list[str] = Field(default_factory=list, description="Text chunks for analysis")
    max_queries: int | None = Field(default=None, description="Override for max search queries (set by adaptive scaling)")


class FlaggedPassage(BaseModel):
    """A passage flagged by an agent."""

    text: str = Field(..., description="The flagged text snippet")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Similarity score")
    source: str | None = Field(default=None, description="Matched source URL or reference")
    reason: str = Field(default="", description="Why this passage was flagged")


class AgentOutput(BaseModel):
    """Standard output schema returned by every detection agent."""

    agent_name: str = Field(..., description="Name of the agent that produced this output")
    score: float = Field(..., ge=0.0, le=100.0, description="Agent-level plagiarism score (0-100)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the score (0-1)")
    flagged_passages: list[FlaggedPassage] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict, description="Agent-specific metadata")


# ---------------------------------------------------------------------------
# Aggregated / Final Report
# ---------------------------------------------------------------------------

class SourceTextBlock(BaseModel):
    """A single matched text block belonging to a detected source."""

    text: str = Field(..., description="The flagged passage text")
    word_count: int = Field(default=0, description="Number of words in this block")
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)


class DetectedSource(BaseModel):
    """A source detected during plagiarism analysis."""

    source_number: int = Field(default=0, description="1-based index for source referencing")
    source_type: str = Field(default="Internet", description="Internet | Publication | Internal")
    url: str | None = Field(default=None, description="URL of the matched source")
    title: str | None = Field(default=None, description="Title of the matched source")
    similarity: float = Field(..., ge=0.0, le=1.0, description="Similarity with the source")
    text_blocks: int = Field(default=0, description="Number of flagged passages from this source")
    matched_words: int = Field(default=0, description="Total word count of matching passages")
    matched_passages: list[SourceTextBlock] = Field(default_factory=list, description="Text blocks from this source")


class MatchGroup(BaseModel):
    """Categorised match group for the similarity report."""

    category: str = Field(..., description="Web Match | Academic Match | Internal Duplication | AI Generated")
    icon: str = Field(default="", description="Emoji icon for the category")
    count: int = Field(default=0, description="Number of flagged passages in this group")
    percentage: float = Field(default=0.0, description="Percentage of document matched in this group")


class PlagiarismReport(BaseModel):
    """Final aggregated plagiarism report."""

    document_id: str
    plagiarism_score: float = Field(..., ge=0.0, le=100.0, description="Overall plagiarism score")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Overall confidence")
    risk_level: RiskLevel
    original_text: str = Field(default="", description="Original document text for the document viewer")
    language: str = Field(default="en", description="Detected language ISO code")
    language_name: str = Field(default="English", description="Detected language display name")
    citation_metadata: dict[str, Any] = Field(default_factory=dict, description="Citation stripping metadata")
    match_groups: list[MatchGroup] = Field(default_factory=list, description="Categorised match groups")
    detected_sources: list[DetectedSource] = Field(default_factory=list)
    flagged_passages: list[FlaggedPassage] = Field(default_factory=list)
    agent_results: list[AgentOutput] = Field(default_factory=list)
    explanation: str = Field(default="", description="Human-readable summary")
