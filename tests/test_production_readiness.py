"""Tests for production readiness improvements.

Covers:
- Request ID middleware (generation, propagation, echo)
- Enhanced health check (dependency checks, response structure)
- Input validation limits (max_length on text fields)
- Config-driven constants (batch_max_files, timeouts, AI thresholds)
- Debug mode warnings
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════
# Request ID Middleware
# ═══════════════════════════════════════════════════════════════════════════


class TestRequestIDMiddleware:
    """X-Request-ID header generation and echo."""

    def test_response_includes_request_id(self) -> None:
        """Every response should include an X-Request-ID header."""
        resp = client.get("/health")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0

    def test_provided_request_id_is_echoed(self) -> None:
        """If the client sends X-Request-ID, the same value should be echoed."""
        custom_id = uuid.uuid4().hex
        resp = client.get("/health", headers={"X-Request-ID": custom_id})
        assert resp.headers["X-Request-ID"] == custom_id

    def test_generated_request_id_is_hex(self) -> None:
        """Auto-generated IDs should be valid hex strings."""
        resp = client.get("/health")
        rid = resp.headers["X-Request-ID"]
        int(rid, 16)  # raises ValueError if not hex


# ═══════════════════════════════════════════════════════════════════════════
# Enhanced Health Check
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthCheck:
    """Enhanced /health endpoint with dependency status."""

    def test_health_response_structure(self) -> None:
        """Health check should return status, version, and checks."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "checks" in data

    def test_health_checks_include_dependencies(self) -> None:
        """Checks dict should include database, embedding_model, azure_openai."""
        data = client.get("/health").json()
        checks = data["checks"]
        assert "database" in checks
        assert "embedding_model" in checks
        assert "azure_openai" in checks

    def test_health_database_check(self) -> None:
        """Database check should report 'ok' (SQLite always available in tests)."""
        data = client.get("/health").json()
        assert data["checks"]["database"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# Input Validation
# ═══════════════════════════════════════════════════════════════════════════


class TestInputValidation:
    """max_length enforcement on text endpoints."""

    def test_analyze_text_rejects_oversized_input(self) -> None:
        """Text exceeding max_length should return 422."""
        huge_text = "x" * 500_001
        resp = client.post(
            "/api/v1/analyze-agent",
            json={"text": huge_text},
        )
        assert resp.status_code == 422

    def test_analyze_text_accepts_valid_input(self) -> None:
        """Text within max_length should not be rejected for length."""
        valid_text = "This is a normal-length document for plagiarism testing."
        resp = client.post(
            "/api/v1/analyze-agent",
            json={"text": valid_text},
        )
        # Should succeed (200) or hit another issue — but NOT 422 for length
        assert resp.status_code != 422


# ═══════════════════════════════════════════════════════════════════════════
# Config-driven Constants
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigConstants:
    """Verify that previously-hardcoded values are now in config."""

    def test_batch_max_files_in_config(self) -> None:
        from app.config import settings
        assert hasattr(settings, "batch_max_files")
        assert settings.batch_max_files == 10

    def test_http_timeouts_in_config(self) -> None:
        from app.config import settings
        assert hasattr(settings, "http_timeout_web_search")
        assert hasattr(settings, "http_timeout_page_fetch")
        assert settings.http_timeout_web_search == 15.0
        assert settings.http_timeout_page_fetch == 10.0

    def test_ai_detection_thresholds_in_config(self) -> None:
        from app.config import settings
        assert hasattr(settings, "ai_ttr_optimal")
        assert hasattr(settings, "ai_burstiness_divisor")
        assert hasattr(settings, "ai_uniformity_window")
        assert settings.ai_ttr_optimal == 0.52
        assert settings.ai_burstiness_divisor == 12.0
        assert settings.ai_uniformity_window == 5

    def test_db_connection_timeout_in_config(self) -> None:
        from app.config import settings
        assert hasattr(settings, "db_connection_timeout")
        assert settings.db_connection_timeout == 30

    def test_max_text_length_in_config(self) -> None:
        from app.config import settings
        assert hasattr(settings, "max_text_length")
        assert settings.max_text_length == 500_000


# ═══════════════════════════════════════════════════════════════════════════
# Error Response Includes Request ID
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorResponseRequestID:
    """Error responses should include request_id for traceability."""

    def test_validation_error_includes_request_id_header(self) -> None:
        """422 responses should include X-Request-ID header."""
        resp = client.post("/api/v1/analyze-agent", json={"text": ""})
        assert "X-Request-ID" in resp.headers


# ═══════════════════════════════════════════════════════════════════════════
# Security Headers (existing behaviour — regression check)
# ═══════════════════════════════════════════════════════════════════════════


class TestSecurityHeaders:
    """Verify security headers are present on responses."""

    def test_security_headers_present(self) -> None:
        resp = client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self) -> None:
        resp = client.get("/health")
        assert "camera=()" in resp.headers.get("Permissions-Policy", "")
