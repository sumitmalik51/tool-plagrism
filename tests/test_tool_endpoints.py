"""Tests for the /tools/* API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_chunk_endpoint() -> None:
    """POST /tools/chunk should return chunks."""
    response = client.post("/tools/chunk", json={"text": "Hello world. " * 100})
    assert response.status_code == 200
    data = response.json()
    assert "chunks" in data
    assert "chunk_count" in data
    assert data["chunk_count"] > 0


def test_chunk_endpoint_empty_text() -> None:
    """POST /tools/chunk with empty text should fail validation."""
    response = client.post("/tools/chunk", json={"text": ""})
    assert response.status_code == 422


def test_ai_detect_endpoint() -> None:
    """POST /tools/ai-detect should return detection result."""
    response = client.post(
        "/tools/ai-detect",
        json={"text": "The quick brown fox jumps over the lazy dog. " * 10},
    )
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert "confidence" in data
    assert "indicators" in data


def test_content_extract_txt() -> None:
    """POST /tools/content-extract with a .txt file should extract text."""
    response = client.post(
        "/tools/content-extract",
        files={"file": ("test.txt", b"Hello content here.", "text/plain")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "Hello content here."
    assert data["file_type"] == "txt"


def test_content_extract_unsupported() -> None:
    """POST /tools/content-extract with unsupported type should return 422."""
    response = client.post(
        "/tools/content-extract",
        files={"file": ("test.csv", b"a,b,c", "text/csv")},
    )
    assert response.status_code == 422


def test_web_search_no_api_key() -> None:
    """POST /tools/web-search without BING_API_KEY should return error info."""
    response = client.post(
        "/tools/web-search",
        json={"query": "test query", "count": 3},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["result_count"] == 0
    assert "error" in data or data["results"] == []


def test_similarity_endpoint() -> None:
    """POST /tools/similarity should compute similarity."""
    import numpy as np

    vecs = np.random.default_rng(0).random((2, 3)).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    normalized = (vecs / norms).tolist()

    response = client.post(
        "/tools/similarity",
        json={
            "texts_a": ["text a1", "text a2"],
            "texts_b": ["text b1", "text b2"],
            "embeddings_a": normalized,
            "embeddings_b": normalized,
            "threshold": 0.8,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert "high_similarity_pairs" in data


# ---------------------------------------------------------------------------
# Generate report endpoint
# ---------------------------------------------------------------------------


def test_generate_report_minimal() -> None:
    """POST /tools/generate-report with minimal input should return report."""
    response = client.post(
        "/tools/generate-report",
        json={
            "document_id": "doc-001",
            "plagiarism_score": 15.0,
            "confidence_score": 0.8,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["document_id"] == "doc-001"
    assert data["plagiarism_score"] == 15.0
    assert data["risk_level"] == "LOW"
    assert "explanation" in data
    assert "generated_at" in data
    assert data["flagged_passages"] == []
    assert data["detected_sources"] == []


def test_generate_report_high_risk() -> None:
    """POST /tools/generate-report with high score should return HIGH risk."""
    response = client.post(
        "/tools/generate-report",
        json={
            "document_id": "doc-002",
            "plagiarism_score": 85.0,
            "confidence_score": 0.95,
            "ai_score": 72.0,
            "flagged_passages": [
                {
                    "text": "This is a copied passage.",
                    "similarity_score": 0.92,
                    "source": "https://example.com/paper",
                    "reason": "High cosine similarity",
                }
            ],
            "detected_sources": [
                {
                    "url": "https://example.com/paper",
                    "title": "Original Paper",
                    "similarity": 0.92,
                }
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["risk_level"] == "HIGH"
    assert len(data["flagged_passages"]) == 1
    assert len(data["detected_sources"]) == 1
    assert data["ai_score"] == 72.0
    assert "Manual review" in data["explanation"]


def test_generate_report_medium_risk() -> None:
    """POST /tools/generate-report with medium score returns MEDIUM risk."""
    response = client.post(
        "/tools/generate-report",
        json={
            "document_id": "doc-003",
            "plagiarism_score": 50.0,
            "confidence_score": 0.7,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["risk_level"] == "MEDIUM"
    assert "Review flagged" in data["explanation"]


def test_generate_report_validation() -> None:
    """POST /tools/generate-report with invalid data should return 422."""
    response = client.post(
        "/tools/generate-report",
        json={"document_id": "doc-bad"},
    )
    assert response.status_code == 422
