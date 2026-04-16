"""Tests for the scan history API endpoints."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth_header(user_id: int = 1) -> dict[str, str]:
    """Create a mock auth header."""
    from app.services.auth_service import create_access_token
    token = create_access_token(user_id, email="test@example.com")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /api/v1/scan-history
# ---------------------------------------------------------------------------

def test_scan_history_requires_auth() -> None:
    resp = client.get("/api/v1/scan-history")
    assert resp.status_code == 401


def test_scan_history_returns_scans() -> None:
    mock_scans = [
        {
            "document_id": "doc1",
            "filename": "test.pdf",
            "plagiarism_score": 45.0,
            "confidence_score": 0.8,
            "risk_level": "MEDIUM",
            "created_at": "2024-01-01T00:00:00Z",
        },
        {
            "document_id": "doc2",
            "filename": "essay.docx",
            "plagiarism_score": 10.0,
            "confidence_score": 0.7,
            "risk_level": "LOW",
            "created_at": "2024-01-02T00:00:00Z",
        },
    ]

    with patch("app.routes.advanced.get_user_scans", return_value=mock_scans):
        resp = client.get("/api/v1/scan-history", headers=_auth_header())

    assert resp.status_code == 200
    data = resp.json()
    assert "scans" in data
    assert data["count"] == 2
    assert data["has_more"] is False


def test_scan_history_pagination() -> None:
    # Return limit+1 items to indicate there are more
    mock_scans = [{"document_id": f"doc{i}", "filename": f"test{i}.pdf"} for i in range(6)]

    with patch("app.routes.advanced.get_user_scans", return_value=mock_scans):
        resp = client.get("/api/v1/scan-history?limit=5&offset=0", headers=_auth_header())

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 5
    assert data["has_more"] is True
    assert data["limit"] == 5
    assert data["offset"] == 0


def test_scan_history_strips_report_json() -> None:
    mock_scans = [
        {
            "document_id": "doc1",
            "report_json": '{"large": "json data"}',
        },
    ]

    with patch("app.routes.advanced.get_user_scans", return_value=mock_scans):
        resp = client.get("/api/v1/scan-history", headers=_auth_header())

    data = resp.json()
    for scan in data["scans"]:
        assert "report_json" not in scan


def test_scan_history_filter_by_risk_level() -> None:
    with patch("app.routes.advanced.get_user_scans", return_value=[]) as mock:
        resp = client.get("/api/v1/scan-history?risk_level=HIGH", headers=_auth_header())

    assert resp.status_code == 200
    # Verify the filter was passed through
    mock.assert_called_once()
    call_kwargs = mock.call_args
    assert call_kwargs.kwargs.get("risk_level") == "HIGH" or "HIGH" in str(call_kwargs)


# ---------------------------------------------------------------------------
# GET /api/v1/scan-history/{document_id}
# ---------------------------------------------------------------------------

def test_scan_detail_requires_auth() -> None:
    resp = client.get("/api/v1/scan-history/doc123")
    assert resp.status_code == 401


def test_scan_detail_not_found() -> None:
    with patch("app.routes.advanced.get_scan", return_value=None):
        resp = client.get("/api/v1/scan-history/nonexistent", headers=_auth_header())

    assert resp.status_code == 404


def test_scan_detail_returns_full_scan() -> None:
    mock_scan = {
        "document_id": "doc1",
        "filename": "test.pdf",
        "plagiarism_score": 45.0,
        "report_json": json.dumps({"flagged_passages": [], "score": 45.0}),
    }

    with patch("app.routes.advanced.get_scan", return_value=mock_scan):
        resp = client.get("/api/v1/scan-history/doc1", headers=_auth_header())

    assert resp.status_code == 200
    data = resp.json()
    assert data["scan"]["document_id"] == "doc1"
    assert "report" in data["scan"]
    assert data["scan"]["report"]["score"] == 45.0
    assert "report_json" not in data["scan"]
