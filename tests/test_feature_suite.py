"""Tests for F1-F6 features: improvement suggestions, scan comparison, enhanced PDF,
citation generation on highlight, compare page route, theme toggle."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_REPORT = {
    "document_id": "abc123",
    "plagiarism_score": 42.5,
    "confidence_score": 0.85,
    "risk_level": "MEDIUM",
    "original_text": "This is some original text that was scanned for plagiarism.",
    "flagged_passages": [
        {
            "text": "This is a copied passage from the internet.",
            "similarity_score": 0.82,
            "source": "https://example.com/source1",
            "reason": "Web match",
        },
        {
            "text": "Another moderately matched passage here.",
            "similarity_score": 0.55,
            "source": "https://example.com/source2",
            "reason": "Web match",
        },
        {
            "text": "A low similarity match that barely registers.",
            "similarity_score": 0.25,
            "source": "https://example.com/source3",
            "reason": "Web match",
        },
    ],
    "detected_sources": [
        {
            "source_number": 1,
            "url": "https://example.com/source1",
            "title": "Example Source One",
            "similarity": 0.82,
            "source_type": "Internet",
            "text_blocks": 1,
            "matched_words": 20,
            "matched_passages": [
                {"text": "This is a copied passage from the internet.", "word_count": 8, "similarity_score": 0.82}
            ],
        },
        {
            "source_number": 2,
            "url": "https://example.com/source2",
            "title": "Example Source Two",
            "similarity": 0.55,
            "source_type": "Internet",
            "text_blocks": 1,
            "matched_words": 10,
            "matched_passages": [
                {"text": "Another moderately matched passage here.", "word_count": 5, "similarity_score": 0.55}
            ],
        },
    ],
}

_FAKE_SCAN_A = {
    "id": 1,
    "document_id": "abc123",
    "user_id": 1,
    "plagiarism_score": 42.5,
    "confidence_score": 0.85,
    "risk_level": "MEDIUM",
    "sources_count": 2,
    "flagged_count": 3,
    "report_json": json.dumps(_FAKE_REPORT),
    "created_at": "2026-04-01T10:00:00",
}

_REPORT_B = {
    **_FAKE_REPORT,
    "document_id": "def456",
    "plagiarism_score": 25.0,
    "risk_level": "LOW",
    "flagged_passages": [_FAKE_REPORT["flagged_passages"][1]],
    "detected_sources": [_FAKE_REPORT["detected_sources"][1]],
}

_FAKE_SCAN_B = {
    "id": 2,
    "document_id": "def456",
    "user_id": 1,
    "plagiarism_score": 25.0,
    "confidence_score": 0.85,
    "risk_level": "LOW",
    "sources_count": 1,
    "flagged_count": 1,
    "report_json": json.dumps(_REPORT_B),
    "created_at": "2026-04-06T10:00:00",
}

_AUTH_HEADERS = {"Authorization": "Bearer test-token"}

# Payload that verify_access_token returns for a valid JWT
_FAKE_JWT_PAYLOAD = {"sub": "1", "email": "test@example.com", "plan_type": "pro"}

_PATCH_VERIFY = "app.services.auth_service.verify_access_token"


# ---------------------------------------------------------------------------
# F2: Improvement Suggestions
# ---------------------------------------------------------------------------

class TestImprovementSuggestions:
    """Tests for POST /api/v1/improvement-suggestions."""

    def test_suggestions_returns_all_flagged(self):
        mock_db = MagicMock()
        mock_db.fetch_one.return_value = _FAKE_SCAN_A

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.post(
                    "/api/v1/improvement-suggestions",
                    json={"document_id": "abc123"},
                    headers=_AUTH_HEADERS,
                )

        assert r.status_code == 200
        data = r.json()
        assert data["document_id"] == "abc123"
        assert data["total_flagged"] == 3
        assert len(data["suggestions"]) == 3

    def test_suggestions_action_types(self):
        """High sim → rewrite, medium → paraphrase, low → cite."""
        mock_db = MagicMock()
        mock_db.fetch_one.return_value = _FAKE_SCAN_A

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.post(
                    "/api/v1/improvement-suggestions",
                    json={"document_id": "abc123"},
                    headers=_AUTH_HEADERS,
                )

        suggestions = r.json()["suggestions"]
        assert suggestions[0]["action"] == "rewrite_required"
        assert suggestions[1]["action"] == "paraphrase_and_cite"
        assert suggestions[2]["action"] == "add_citation"

    def test_suggestions_includes_source_title(self):
        mock_db = MagicMock()
        mock_db.fetch_one.return_value = _FAKE_SCAN_A

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.post(
                    "/api/v1/improvement-suggestions",
                    json={"document_id": "abc123"},
                    headers=_AUTH_HEADERS,
                )

        suggestions = r.json()["suggestions"]
        assert suggestions[0]["source_title"] == "Example Source One"

    def test_suggestions_scan_not_found(self):
        mock_db = MagicMock()
        mock_db.fetch_one.return_value = None

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.post(
                    "/api/v1/improvement-suggestions",
                    json={"document_id": "nonexistent"},
                    headers=_AUTH_HEADERS,
                )

        assert r.status_code == 404

    def test_suggestions_unauthenticated(self):
        r = client.post(
            "/api/v1/improvement-suggestions",
            json={"document_id": "abc123"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# F4: Scan Comparison
# ---------------------------------------------------------------------------

class TestScanComparison:
    """Tests for POST /api/v1/compare-scans."""

    def test_compare_score_diff(self):
        mock_db = MagicMock()
        mock_db.fetch_one.side_effect = [_FAKE_SCAN_A, _FAKE_SCAN_B]

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.post(
                    "/api/v1/compare-scans",
                    json={"document_id_a": "abc123", "document_id_b": "def456"},
                    headers=_AUTH_HEADERS,
                )

        assert r.status_code == 200
        data = r.json()
        sd = data["score_diff"]
        assert sd["plagiarism_score"]["a"] == 42.5
        assert sd["plagiarism_score"]["b"] == 25.0
        assert sd["plagiarism_score"]["change"] == -17.5

    def test_compare_source_changes(self):
        mock_db = MagicMock()
        mock_db.fetch_one.side_effect = [_FAKE_SCAN_A, _FAKE_SCAN_B]

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.post(
                    "/api/v1/compare-scans",
                    json={"document_id_a": "abc123", "document_id_b": "def456"},
                    headers=_AUTH_HEADERS,
                )

        data = r.json()
        # Source 1 was in A but not in B → removed
        assert len(data["removed_sources"]) == 1
        assert data["removed_sources"][0]["url"] == "https://example.com/source1"

    def test_compare_resolved_passages(self):
        mock_db = MagicMock()
        mock_db.fetch_one.side_effect = [_FAKE_SCAN_A, _FAKE_SCAN_B]

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.post(
                    "/api/v1/compare-scans",
                    json={"document_id_a": "abc123", "document_id_b": "def456"},
                    headers=_AUTH_HEADERS,
                )

        data = r.json()
        # Passages 1 and 3 from A were resolved in B (only passage 2 remains)
        assert len(data["resolved_passages"]) == 2

    def test_compare_scan_not_found(self):
        mock_db = MagicMock()
        mock_db.fetch_one.side_effect = [_FAKE_SCAN_A, None]

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.post(
                    "/api/v1/compare-scans",
                    json={"document_id_a": "abc123", "document_id_b": "nonexistent"},
                    headers=_AUTH_HEADERS,
                )

        assert r.status_code == 404

    def test_compare_unauthenticated(self):
        r = client.post(
            "/api/v1/compare-scans",
            json={"document_id_a": "abc123", "document_id_b": "def456"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# F3: Enhanced PDF Export
# ---------------------------------------------------------------------------

class TestEnhancedPDF:
    """Tests for the Turnitin-style PDF report."""

    def test_pdf_is_valid(self):
        mock_db = MagicMock()
        mock_db.fetch_one.return_value = _FAKE_SCAN_A

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.get(
                    "/api/v1/export-pdf/abc123",
                    headers=_AUTH_HEADERS,
                )

        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"

    def test_pdf_contains_source_table(self):
        """Verify PDF is larger than the old minimal version (has table + passages)."""
        mock_db = MagicMock()
        mock_db.fetch_one.return_value = _FAKE_SCAN_A

        with patch(_PATCH_VERIFY, return_value=_FAKE_JWT_PAYLOAD):
            with patch("app.services.database.get_db", return_value=mock_db):
                r = client.get(
                    "/api/v1/export-pdf/abc123",
                    headers=_AUTH_HEADERS,
                )

        # Enhanced PDF with tables should be at least 2KB
        assert len(r.content) > 2000


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

class TestPageRoutes:
    def test_compare_page(self):
        r = client.get("/compare")
        assert r.status_code == 200
        assert b"Compare Scans" in r.content

    def test_highlight_page(self):
        r = client.get("/highlight")
        assert r.status_code == 200
        assert b"Suggestions" in r.content
        assert b"Citations" in r.content

    def test_highlight_has_theme_toggle(self):
        r = client.get("/highlight")
        assert b"themeToggle" in r.content

    def test_batch_has_theme_toggle(self):
        r = client.get("/batch")
        assert b"themeToggle" in r.content

    def test_history_has_compare_link(self):
        r = client.get("/history")
        assert b"/compare" in r.content
