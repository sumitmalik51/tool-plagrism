"""Tests for the file upload endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    """GET /health should return 200 with status and checks."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "version" in data
    assert "checks" in data


def test_upload_txt_file() -> None:
    """POST /api/v1/upload with a .txt file should return 201."""
    content = b"This is a sample document for plagiarism testing."
    response = client.post(
        "/api/v1/upload",
        files={"file": ("sample.txt", content, "text/plain")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "sample.txt"
    assert data["file_type"] == "txt"
    assert data["char_count"] > 0
    assert "document_id" in data


def test_upload_unsupported_file_type() -> None:
    """POST /api/v1/upload with an unsupported extension should return 422."""
    content = b"<html><body>test</body></html>"
    response = client.post(
        "/api/v1/upload",
        files={"file": ("page.html", content, "text/html")},
    )
    assert response.status_code == 422


def test_upload_empty_file() -> None:
    """POST /api/v1/upload with an empty file should return 422."""
    response = client.post(
        "/api/v1/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 422
