"""Tests for the /api/v1/analyze endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
def test_analyze_txt_file(mock_embed: AsyncMock) -> None:
    """POST /api/v1/analyze should return a structured report."""
    mock_embed.return_value = np.random.default_rng(0).random((6, 384)).astype(np.float32)

    content = b"This is a reasonably sized test document for analysis. " * 30
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("paper.txt", content, "text/plain")},
    )

    assert response.status_code == 200
    data = response.json()
    assert "plagiarism_score" in data
    assert "confidence_score" in data
    assert "risk_level" in data
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    assert "flagged_passages" in data
    assert "agent_results" in data
    assert "explanation" in data
    assert "Report generated at" in data["explanation"]


@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
def test_analyze_unsupported_type(mock_embed: AsyncMock) -> None:
    """Unsupported file type should return 422."""
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("page.html", b"<html></html>", "text/html")},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /api/v1/analyze-agent  (text-based analysis)
# ---------------------------------------------------------------------------


@patch("app.agents.semantic_agent.generate_embeddings", new_callable=AsyncMock)
def test_analyze_agent_text(mock_embed: AsyncMock) -> None:
    """POST /api/v1/analyze-agent with text should return a structured report."""
    mock_embed.return_value = np.random.default_rng(0).random((6, 384)).astype(np.float32)

    text = "This is a reasonably sized test document for analysis. " * 30
    response = client.post(
        "/api/v1/analyze-agent",
        json={"text": text},
    )

    assert response.status_code == 200
    data = response.json()
    assert "plagiarism_score" in data
    assert "confidence_score" in data
    assert "risk_level" in data
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    assert "flagged_passages" in data
    assert "agent_results" in data
    assert "explanation" in data


def test_analyze_agent_empty_text() -> None:
    """POST /api/v1/analyze-agent with empty text should return 422."""
    response = client.post(
        "/api/v1/analyze-agent",
        json={"text": ""},
    )
    assert response.status_code == 422


def test_analyze_agent_missing_text() -> None:
    """POST /api/v1/analyze-agent without text field should return 422."""
    response = client.post(
        "/api/v1/analyze-agent",
        json={},
    )
    assert response.status_code == 422
