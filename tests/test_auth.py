"""Tests for authentication and security middleware."""

from __future__ import annotations

import contextlib

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


# ---------------------------------------------------------------------------
# Helpers — create test app with specific auth config
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _override_api_keys(keys: list[str]):
    """Temporarily override settings.api_keys (bypasses Pydantic guards)."""
    original = settings.api_keys
    object.__setattr__(settings, "api_keys", keys)
    try:
        yield
    finally:
        object.__setattr__(settings, "api_keys", original)


# Reusable test client (settings overridden per-test via context manager)
_client = TestClient(app, raise_server_exceptions=False)

# Endpoint that exists and is not public (tools router is /tools/...)
_PROTECTED_ENDPOINT = "/tools/chunk"
_PROTECTED_PAYLOAD = {"text": "Hello world test text.", "chunk_size": 200}


# ---------------------------------------------------------------------------
# Auth disabled (no keys configured) — dev mode
# ---------------------------------------------------------------------------

class TestAuthDisabled:
    """When PG_API_KEYS_RAW is empty, all routes are open."""

    def test_health_public(self) -> None:
        with _override_api_keys([]):
            resp = _client.get("/health")
            assert resp.status_code == 200

    def test_api_open_without_keys(self) -> None:
        """API routes should be accessible when no keys are configured."""
        with _override_api_keys([]):
            resp = _client.post(_PROTECTED_ENDPOINT, json=_PROTECTED_PAYLOAD)
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth enabled (keys configured)
# ---------------------------------------------------------------------------

class TestAuthEnabled:
    """When PG_API_KEYS_RAW is set, API routes require auth."""

    API_KEY = "pg_sk_test123"

    def test_health_stays_public(self) -> None:
        with _override_api_keys([self.API_KEY]):
            resp = _client.get("/health")
            assert resp.status_code == 200

    def test_docs_stays_public(self) -> None:
        with _override_api_keys([self.API_KEY]):
            resp = _client.get("/docs")
            assert resp.status_code == 200

    def test_root_stays_public(self) -> None:
        with _override_api_keys([self.API_KEY]):
            resp = _client.get("/")
            # Root is now an API service-info JSON endpoint, must not require auth
            assert resp.status_code == 200
            assert resp.json().get("service")

    def test_static_assets_stay_public(self) -> None:
        with _override_api_keys([self.API_KEY]):
            resp = _client.get("/static/favicon.svg")
            # External manifests (Word add-in, OG cards) reach this without auth
            assert resp.status_code == 200

    def test_api_rejected_without_key(self) -> None:
        with _override_api_keys([self.API_KEY]):
            resp = _client.post(_PROTECTED_ENDPOINT, json=_PROTECTED_PAYLOAD)
            assert resp.status_code == 401
            assert "Unauthorized" in resp.json()["detail"]

    def test_api_rejected_wrong_key(self) -> None:
        with _override_api_keys([self.API_KEY]):
            resp = _client.post(
                _PROTECTED_ENDPOINT,
                json=_PROTECTED_PAYLOAD,
                headers={"X-API-Key": "wrong_key"},
            )
            assert resp.status_code == 401

    def test_api_allowed_correct_key(self) -> None:
        with _override_api_keys([self.API_KEY]):
            resp = _client.post(
                _PROTECTED_ENDPOINT,
                json=_PROTECTED_PAYLOAD,
                headers={"X-API-Key": self.API_KEY},
            )
            assert resp.status_code == 200

    def test_api_allowed_easy_auth(self) -> None:
        """Azure Easy Auth headers (principal + IDP) should bypass API key check."""
        with _override_api_keys([self.API_KEY]):
            resp = _client.post(
                _PROTECTED_ENDPOINT,
                json=_PROTECTED_PAYLOAD,
                headers={
                    "X-MS-CLIENT-PRINCIPAL": "eyJhbGciOi...dummytoken",
                    "X-MS-CLIENT-PRINCIPAL-IDP": "aad",
                },
            )
            assert resp.status_code == 200

    def test_easy_auth_without_idp_rejected(self) -> None:
        """X-MS-CLIENT-PRINCIPAL alone (no IDP header) should NOT bypass auth."""
        with _override_api_keys([self.API_KEY]):
            resp = _client.post(
                _PROTECTED_ENDPOINT,
                json=_PROTECTED_PAYLOAD,
                headers={"X-MS-CLIENT-PRINCIPAL": "eyJhbGciOi...dummytoken"},
            )
            assert resp.status_code == 401

    def test_multiple_keys_supported(self) -> None:
        """Multiple comma-separated keys should all work."""
        with _override_api_keys(["key_alpha", "key_beta", "key_gamma"]):
            resp = _client.post(
                _PROTECTED_ENDPOINT,
                json=_PROTECTED_PAYLOAD,
                headers={"X-API-Key": "key_beta"},
            )
            assert resp.status_code == 200

    def test_upload_requires_auth(self) -> None:
        """Upload endpoint should require auth (401 before validation)."""
        with _override_api_keys([self.API_KEY]):
            resp = _client.post("/api/v1/upload")
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    """Security headers should be present on all responses."""

    def test_x_content_type_options(self) -> None:
        resp = _client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self) -> None:
        resp = _client.get("/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self) -> None:
        resp = _client.get("/health")
        assert "strict-origin" in resp.headers.get("Referrer-Policy", "")


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

class TestGlobalExceptionHandler:
    """Unhandled exceptions should return sanitized 500."""

    def test_error_response_no_stack_trace(self) -> None:
        """The 500 response should NOT leak implementation details."""
        with _override_api_keys([]):
            resp = _client.post("/api/v1/upload")
            body = resp.text
            assert "Traceback" not in body
            assert "app/" not in body or resp.status_code == 422  # Pydantic 422 is OK


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

class TestApiKeyConfig:
    """api_keys model_validator parsing."""

    def test_empty_string(self) -> None:
        from app.config import Settings
        s = Settings(api_keys_raw="")
        assert s.api_keys == []

    def test_single_key(self) -> None:
        from app.config import Settings
        s = Settings(api_keys_raw="mykey123")
        assert s.api_keys == ["mykey123"]

    def test_multiple_keys(self) -> None:
        from app.config import Settings
        s = Settings(api_keys_raw="key1, key2 , key3")
        assert s.api_keys == ["key1", "key2", "key3"]

    def test_trailing_comma_ignored(self) -> None:
        from app.config import Settings
        s = Settings(api_keys_raw="key1,")
        assert s.api_keys == ["key1"]
