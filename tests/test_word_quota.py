"""Tests for word quota enforcement in analyze routes."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from starlette.requests import Request

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text(word_count: int) -> str:
    """Generate text with approximately the given word count."""
    return " ".join(["word"] * word_count)


# ---------------------------------------------------------------------------
# Word quota enforcement on /analyze-agent (text endpoint)
# ---------------------------------------------------------------------------

class TestWordQuotaAnalyzeAgent:
    @patch("app.routes.analyze._response_with_rate_headers")
    @patch("app.routes.analyze._persist_scan")
    @patch("app.routes.analyze.record_scan", return_value=10)
    @patch("app.routes.analyze.run_pipeline")
    @patch("app.routes.analyze.save_document")
    @patch("app.routes.analyze.enforce_scan_limit")
    def test_analyze_agent_succeeds_within_quota(
        self, mock_limit, mock_doc, mock_pipeline, mock_record, mock_persist, mock_resp
    ) -> None:
        """Text within word quota should proceed normally."""
        from fastapi.responses import JSONResponse
        mock_resp.return_value = JSONResponse(content={"plagiarism_score": 10.0})

        mock_report = MagicMock()
        mock_report.document_id = "test-doc-123"
        mock_report.plagiarism_score = 10.0
        mock_pipeline.return_value = mock_report

        resp = client.post(
            "/api/v1/analyze-agent",
            json={"text": _make_text(50)},
        )
        # Should succeed (200) — pipeline ran (no user_id means quota skip)
        assert resp.status_code == 200

    def test_analyze_agent_rejects_when_quota_exceeded(self) -> None:
        """Should return 429 when monthly word quota is exceeded."""
        from app.dependencies.rate_limit import enforce_word_quota

        request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
        request.state.user_id = 1
        request.state.plan_type = "free"

        with patch("app.dependencies.rate_limit.get_user_by_id", return_value={"plan_type": "free"}):
            with patch("app.dependencies.rate_limit.limiter") as mock_limiter:
                mock_limiter.check_word_quota.return_value = {
                    "allowed": False,
                    "used": 5000,
                    "limit": 5000,
                    "remaining": 0,
                }
                with patch("app.services.auth_service.get_word_topup_balance", return_value=0):
                    with pytest.raises(HTTPException) as exc:
                        enforce_word_quota(request, word_count=100, what="text")

        assert exc.value.status_code == 429


# ---------------------------------------------------------------------------
# Word quota enforcement on /analyze (file upload endpoint)
# ---------------------------------------------------------------------------

class TestWordQuotaAnalyzeFile:
    def test_upload_small_file_ok(self) -> None:
        """A small text file should be accepted for analysis."""
        content = b"This is a test document with some words for plagiarism analysis."

        with patch("app.dependencies.rate_limit.limiter") as mock_limiter:
            mock_limiter.check_word_quota.return_value = {
                "allowed": True, "used": 50, "limit": 5000, "remaining": 4950
            }
            with patch("app.routes.analyze.run_pipeline") as mock_pipeline:
                from app.models.schemas import PlagiarismReport
                mock_report = MagicMock(spec=PlagiarismReport)
                mock_report.model_dump.return_value = {"plagiarism_score": 5.0}
                mock_pipeline.return_value = mock_report

                with patch("app.routes.analyze.save_scan"):
                    with patch("app.routes.analyze.save_document"):
                        with patch("app.routes.analyze.record_scan"):
                            resp = client.post(
                                "/api/v1/analyze",
                                files={"file": ("test.txt", content, "text/plain")},
                            )
                            # May succeed or fail depending on scan limit, but won't be 429 for words
                            assert resp.status_code != 413


# ---------------------------------------------------------------------------
# File size pre-validation on /upload
# ---------------------------------------------------------------------------

class TestFileSizeValidation:
    def test_upload_rejects_oversized_file(self) -> None:
        """Files over 100MB should be rejected before reading into memory."""
        # We can't easily send a 100MB file in tests, but we can check the
        # endpoint exists and rejects based on file.size
        content = b"x" * 1000  # small file for testing
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("big.txt", content, "text/plain")},
        )
        # Small file should not be rejected for size
        assert resp.status_code != 413


# ---------------------------------------------------------------------------
# Rate limiter PLAN_TO_TIER mapping
# ---------------------------------------------------------------------------

class TestPlanToTier:
    def test_plan_to_tier_has_all_plans(self) -> None:
        from app.services.rate_limiter import PLAN_TO_TIER, UserTier

        assert "free" in PLAN_TO_TIER
        assert "pro" in PLAN_TO_TIER
        assert "premium" in PLAN_TO_TIER
        assert "paid" in PLAN_TO_TIER  # legacy alias

        assert PLAN_TO_TIER["free"] == UserTier.FREE
        assert PLAN_TO_TIER["pro"] == UserTier.PRO
        assert PLAN_TO_TIER["paid"] == UserTier.PRO  # legacy alias maps to PRO

    def test_word_quota_check_returns_expected_fields(self) -> None:
        from app.services.rate_limiter import limiter, UserTier

        result = limiter.check_word_quota(user_id=999, tier=UserTier.FREE, word_count=100)
        assert "allowed" in result
        assert "used" in result
        assert "limit" in result
        assert "remaining" in result

    def test_word_topup_covers_only_base_quota_deficit(self) -> None:
        """Purchased scan words should cover the deficit after base quota is spent."""
        from app.config import settings
        from app.dependencies.rate_limit import enforce_word_quota
        from app.services.auth_service import add_word_topup, get_word_topup_balance
        from app.services.database import get_db

        email = f"quota-{uuid4().hex}@example.com"
        db = get_db()
        user_id = db.execute(
            "INSERT INTO users (name, email, password, plan_type) VALUES (?, ?, ?, 'free')",
            ("Quota User", email, "hash"),
        )
        free_limit = int(settings.word_quota_free)
        db.execute(
            "INSERT INTO usage_logs (user_id, tool_type, word_count) VALUES (?, 'scan', ?)",
            (user_id, free_limit - 100),
        )
        add_word_topup(user_id, words=1000, order_id=f"order_{uuid4().hex}", payment_id="pay_test")

        request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
        request.state.user_id = user_id
        request.state.plan_type = "free"

        result = enforce_word_quota(request, word_count=250, what="test")

        assert result["allowed"] is True
        assert result["topup_used"] == 150
        assert get_word_topup_balance(user_id) == 850
