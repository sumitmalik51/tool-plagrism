"""Tests for shareable report links feature."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_service import create_access_token, signup
from app.services.database import get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_db():
    db = get_db()
    db.execute("DELETE FROM shared_reports")
    db.execute("DELETE FROM payments")
    db.execute("DELETE FROM document_fingerprints")
    db.execute("DELETE FROM scans")
    db.execute("DELETE FROM documents")
    db.execute("DELETE FROM user_api_keys")
    db.execute("DELETE FROM users")
    yield


def _create_user(email: str = "share@test.com") -> int:
    """Create a test user and return the user_id."""
    result = signup("Test User", email, "secret123")
    return result["user"]["id"]


def _seed_scan(user_id: int, document_id: str = "doc-share-test") -> int:
    """Insert a minimal scan row and return its id."""
    db = get_db()
    return db.execute(
        "INSERT INTO scans (document_id, user_id, plagiarism_score, confidence_score, "
        "risk_level, sources_count, flagged_count, report_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (document_id, user_id, 25.0, 0.85, "LOW", 3, 1,
         json.dumps({"plagiarism_score": 25, "document_id": document_id})),
    )


def _auth_headers(user_id: int, email: str = "share@test.com") -> dict:
    """Return headers that simulate an authenticated user via JWT."""
    token = create_access_token(user_id, email)
    return {"Authorization": f"Bearer {token}"}


# ── POST /api/v1/share-report ─────────────────────────────────────────────


def test_share_report_success():
    uid = _create_user()
    doc_id = "doc-share-1"
    _seed_scan(user_id=uid, document_id=doc_id)
    resp = client.post(
        "/api/v1/share-report",
        json={"document_id": doc_id},
        headers=_auth_headers(uid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "share_id" in data
    assert len(data["share_id"]) == 32  # uuid hex


def test_share_report_unauthenticated():
    resp = client.post(
        "/api/v1/share-report",
        json={"document_id": "whatever"},
    )
    assert resp.status_code == 401


def test_share_report_not_found():
    uid = _create_user()
    resp = client.post(
        "/api/v1/share-report",
        json={"document_id": "nonexistent-doc-xyz"},
        headers=_auth_headers(uid),
    )
    assert resp.status_code == 404


# ── GET /api/v1/shared/{share_id} ─────────────────────────────────────────


def test_get_shared_report_success():
    uid = _create_user()
    doc_id = "doc-share-2"
    _seed_scan(user_id=uid, document_id=doc_id)
    # Create share link
    resp = client.post(
        "/api/v1/share-report",
        json={"document_id": doc_id},
        headers=_auth_headers(uid),
    )
    share_id = resp.json()["share_id"]
    # Fetch shared report (no auth required)
    resp2 = client.get(f"/api/v1/shared/{share_id}")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["share_id"] == share_id
    assert data["document_id"] == doc_id
    assert "report" in data


def test_get_shared_report_not_found():
    resp = client.get("/api/v1/shared/0000000000000000deadbeef00000000")
    assert resp.status_code == 404


def test_get_shared_report_expired():
    uid = _create_user()
    doc_id = "doc-share-expired"
    _seed_scan(user_id=uid, document_id=doc_id)
    resp = client.post(
        "/api/v1/share-report",
        json={"document_id": doc_id, "expires_in_days": 1},
        headers=_auth_headers(uid),
    )
    share_id = resp.json()["share_id"]
    # Manually set expires_at to the past
    db = get_db()
    db.execute(
        "UPDATE shared_reports SET expires_at = ? WHERE share_id = ?",
        ("2020-01-01T00:00:00", share_id),
    )
    resp2 = client.get(f"/api/v1/shared/{share_id}")
    assert resp2.status_code == 410


def test_share_report_invalid_share_id():
    resp = client.get("/api/v1/shared/" + "x" * 100)
    assert resp.status_code == 400


def test_share_report_with_custom_expiry():
    uid = _create_user()
    doc_id = "doc-share-custom"
    _seed_scan(user_id=uid, document_id=doc_id)
    resp = client.post(
        "/api/v1/share-report",
        json={"document_id": doc_id, "expires_in_days": 30},
        headers=_auth_headers(uid),
    )
    assert resp.status_code == 200
    share_id = resp.json()["share_id"]
    # Verify the share record exists with an expiry
    db = get_db()
    row = db.fetch_one("SELECT expires_at FROM shared_reports WHERE share_id = ?", (share_id,))
    assert row is not None
    assert row["expires_at"] is not None
