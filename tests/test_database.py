"""Tests for the database abstraction layer and persistence service."""

from __future__ import annotations

import pytest

from app.services.database import get_db
from app.services.persistence import (
    save_document,
    get_document,
    get_user_documents,
    save_scan,
    get_scan,
    get_user_scans,
    get_user_stats,
)
from app.services.auth_service import signup


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_tables():
    """Clear all tables before each test."""
    db = get_db()
    db.execute("DELETE FROM shared_reports")
    db.execute("DELETE FROM payments")
    db.execute("DELETE FROM document_fingerprints")
    db.execute("DELETE FROM scans")
    db.execute("DELETE FROM documents")
    db.execute("DELETE FROM user_api_keys")
    db.execute("DELETE FROM users")
    yield


def _create_test_user() -> dict:
    """Helper — create a user and return the result dict."""
    return signup("Test User", "test@example.com", "password123")


# ═══════════════════════════════════════════════════════════════════════════
# Database abstraction
# ═══════════════════════════════════════════════════════════════════════════

class TestSQLiteDatabase:
    def test_execute_and_fetch(self):
        db = get_db()
        db.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            ("Alice", "alice_db@test.com", "hash"),
        )
        row = db.fetch_one("SELECT name, email FROM users WHERE email = ?", ("alice_db@test.com",))
        assert row is not None
        assert row["name"] == "Alice"

    def test_fetch_all(self):
        db = get_db()
        db.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", ("A", "a@t.com", "h"))
        db.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", ("B", "b@t.com", "h"))
        rows = db.fetch_all("SELECT name FROM users ORDER BY name")
        assert len(rows) == 2
        assert rows[0]["name"] == "A"
        assert rows[1]["name"] == "B"

    def test_fetch_one_returns_none(self):
        db = get_db()
        assert db.fetch_one("SELECT * FROM users WHERE email = ?", ("nobody@test.com",)) is None


# ═══════════════════════════════════════════════════════════════════════════
# Document persistence
# ═══════════════════════════════════════════════════════════════════════════

class TestDocumentPersistence:
    def test_save_and_get_document(self):
        row_id = save_document(
            "doc_abc123",
            filename="report.pdf",
            file_type="pdf",
            char_count=5000,
            text_content="Hello world " * 100,
        )
        assert row_id > 0

        doc = get_document("doc_abc123")
        assert doc is not None
        assert doc["document_id"] == "doc_abc123"
        assert doc["filename"] == "report.pdf"
        assert doc["char_count"] == 5000

    def test_save_document_with_user(self):
        result = _create_test_user()
        user_id = result["user"]["id"]

        save_document("doc_user1", user_id=user_id, filename="f.txt", file_type="txt", char_count=100)
        docs = get_user_documents(user_id)
        assert len(docs) == 1
        assert docs[0]["document_id"] == "doc_user1"

    def test_get_nonexistent_document(self):
        assert get_document("nonexistent") is None

    def test_user_documents_empty(self):
        assert get_user_documents(9999) == []


# ═══════════════════════════════════════════════════════════════════════════
# Scan persistence
# ═══════════════════════════════════════════════════════════════════════════

class TestScanPersistence:
    def test_save_and_get_scan(self):
        save_document("doc_scan1", filename="f.txt", file_type="txt", char_count=500)
        row_id = save_scan(
            "doc_scan1",
            plagiarism_score=45.2,
            confidence_score=0.87,
            risk_level="MEDIUM",
            sources_count=3,
            flagged_count=5,
            report_json='{"test": true}',
        )
        assert row_id > 0

        scan = get_scan("doc_scan1")
        assert scan is not None
        assert scan["plagiarism_score"] == pytest.approx(45.2)
        assert scan["risk_level"] == "MEDIUM"
        assert scan["sources_count"] == 3

    def test_user_scans(self):
        result = _create_test_user()
        user_id = result["user"]["id"]

        save_document("doc_s1", user_id=user_id, filename="a.pdf", file_type="pdf", char_count=100)
        save_document("doc_s2", user_id=user_id, filename="b.pdf", file_type="pdf", char_count=200)
        save_scan("doc_s1", user_id=user_id, plagiarism_score=10, risk_level="LOW")
        save_scan("doc_s2", user_id=user_id, plagiarism_score=70, risk_level="HIGH")

        scans = get_user_scans(user_id)
        assert len(scans) == 2

    def test_get_nonexistent_scan(self):
        save_document("doc_noscan", filename="x.txt", file_type="txt", char_count=1)
        assert get_scan("doc_noscan") is None


# ═══════════════════════════════════════════════════════════════════════════
# User stats
# ═══════════════════════════════════════════════════════════════════════════

class TestUserStats:
    def test_stats_with_data(self):
        result = _create_test_user()
        user_id = result["user"]["id"]

        save_document("doc_st1", user_id=user_id, filename="a.pdf", file_type="pdf", char_count=100)
        save_document("doc_st2", user_id=user_id, filename="b.pdf", file_type="pdf", char_count=200)
        save_scan("doc_st1", user_id=user_id, plagiarism_score=20, risk_level="LOW")
        save_scan("doc_st2", user_id=user_id, plagiarism_score=80, risk_level="HIGH")

        stats = get_user_stats(user_id)
        assert stats["total_scans"] == 2
        assert stats["total_documents"] == 2
        assert stats["average_score"] == 50.0
        assert stats["risk_breakdown"]["LOW"] == 1
        assert stats["risk_breakdown"]["HIGH"] == 1

    def test_stats_empty_user(self):
        stats = get_user_stats(9999)
        assert stats["total_scans"] == 0
        assert stats["total_documents"] == 0
        assert stats["average_score"] == 0
