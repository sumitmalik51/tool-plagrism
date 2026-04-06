"""Tests for LTI 1.3 / LMS integration routes."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import sys

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

LTI_PREFIX = "/api/v1/lti"


# ---------------------------------------------------------------------------
# Configuration / discovery endpoints (no auth needed)
# ---------------------------------------------------------------------------

class TestLTIConfig:
    def test_jwks_returns_keys_array(self) -> None:
        resp = client.get(f"{LTI_PREFIX}/jwks")
        assert resp.status_code == 200
        data = resp.json()
        assert "keys" in data
        assert isinstance(data["keys"], list)

    def test_openid_config_returns_required_fields(self) -> None:
        resp = client.get(f"{LTI_PREFIX}/.well-known/openid-configuration")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
            assert field in data, f"Missing field: {field}"

    def test_tool_config_returns_registration_info(self) -> None:
        resp = client.get(f"{LTI_PREFIX}/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "PlagiarismGuard"
        assert "oidc_initiation_url" in data
        assert "target_link_uri" in data
        assert "scopes" in data
        assert len(data["scopes"]) > 0


# ---------------------------------------------------------------------------
# Login initiation
# ---------------------------------------------------------------------------

class TestLTILogin:
    @patch("app.routes.lms.get_db")
    def test_login_get_redirects(self, mock_db) -> None:
        mock_instance = MagicMock()
        mock_instance.execute.return_value = None
        mock_instance.fetch_one.return_value = {"auth_endpoint": "https://canvas.example.com/api/lti/authorize_redirect"}
        mock_db.return_value = mock_instance

        resp = client.get(
            f"{LTI_PREFIX}/login",
            params={
                "login_hint": "student1",
                "target_link_uri": "http://testserver/api/v1/lti/launch",
                "client_id": "test-client",
                "iss": "https://canvas.example.com",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    @patch("app.routes.lms.get_db")
    def test_login_post_redirects(self, mock_db) -> None:
        mock_instance = MagicMock()
        mock_instance.execute.return_value = None
        mock_instance.fetch_one.return_value = {"auth_endpoint": "https://canvas.example.com/api/lti/authorize_redirect"}
        mock_db.return_value = mock_instance

        resp = client.post(
            f"{LTI_PREFIX}/login",
            data={
                "login_hint": "student1",
                "target_link_uri": "http://testserver/api/v1/lti/launch",
                "client_id": "test-client",
                "iss": "https://canvas.example.com",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Launch endpoint
# ---------------------------------------------------------------------------

class TestLTILaunch:
    def test_launch_missing_id_token_returns_400(self) -> None:
        resp = client.post(f"{LTI_PREFIX}/launch", data={"state": "abc"})
        assert resp.status_code == 400

    def test_launch_invalid_id_token_returns_400(self) -> None:
        with patch("app.routes.lms.get_db") as mock_db:
            mock_instance = MagicMock()
            mock_instance.fetch_one.return_value = {"nonce": "test-nonce", "created_at": "2025-01-01T00:00:00"}
            mock_instance.execute.return_value = None
            mock_db.return_value = mock_instance

            resp = client.post(
                f"{LTI_PREFIX}/launch",
                data={"id_token": "not.a.jwt", "state": "abc"},
            )
            assert resp.status_code == 400

    def test_launch_valid_token_renders_html(self) -> None:
        """Simulate a valid JWT payload with JWKS verification."""
        import base64
        import json

        # Build a mock JWT
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "kid": "test-kid"}).encode()).decode().rstrip("=")
        payload_data = {
            "iss": "https://canvas.example.com",
            "aud": "test-client-id",
            "name": "Test Student",
            "email": "student@example.com",
            "nonce": "test-nonce",
            "https://purl.imsglobal.org/spec/lti/claim/context": {"title": "Test Course"},
            "https://purl.imsglobal.org/spec/lti/claim/resource_link": {"title": "Test Assignment"},
        }
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).decode().rstrip("=")
        sig = base64.urlsafe_b64encode(b"fakesig").decode().rstrip("=")
        token = f"{header}.{payload}.{sig}"

        with patch("app.routes.lms.get_db") as mock_db:
            mock_instance = MagicMock()
            # fetch_one calls: (1) state lookup, (2) platform lookup with JWKS
            mock_instance.fetch_one.side_effect = [
                {"nonce": "test-nonce", "created_at": "2025-01-01T00:00:00"},
                {"jwks_uri": "https://canvas.example.com/jwks", "client_id": "test-client-id"},
            ]
            mock_instance.execute.return_value = None
            mock_db.return_value = mock_instance

            # Mock the JWKS fetch and JWT decode
            with patch("httpx.get") as mock_httpx, \
                 patch("jwt.decode", return_value=payload_data) as mock_jwt_decode:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"keys": [{"kid": "test-kid", "kty": "RSA"}]}
                mock_resp.raise_for_status.return_value = None
                mock_httpx.return_value = mock_resp

                # Patch RSAAlgorithm within the lms module's jwt import
                import jwt as jwt_mod
                with patch.object(jwt_mod.algorithms, "RSAAlgorithm", create=True) as mock_rsa:
                    mock_rsa.from_jwk = MagicMock(return_value="mock-key")

                    resp = client.post(
                        f"{LTI_PREFIX}/launch",
                        data={"id_token": token, "state": "test-state"},
                    )
                    assert resp.status_code == 200
                    assert "PlagiarismGuard" in resp.text
                    assert "Test Student" in resp.text


# ---------------------------------------------------------------------------
# Check endpoint
# ---------------------------------------------------------------------------

class TestLTICheck:
    def test_check_rejects_short_text(self) -> None:
        resp = client.post(f"{LTI_PREFIX}/check", json={"text": "short"})
        assert resp.status_code == 400

    @patch("app.services.orchestrator.run_pipeline")
    def test_check_runs_pipeline(self, mock_pipeline) -> None:
        from app.models.schemas import PlagiarismReport
        mock_report = MagicMock(spec=PlagiarismReport)
        mock_report.model_dump.return_value = {
            "plagiarism_score": 12.5,
            "risk_level": "LOW",
            "confidence_score": 0.85,
            "detected_sources": [],
        }
        mock_pipeline.return_value = mock_report

        # Also patch the chunk_text import inside the function
        with patch.dict("sys.modules", {"app.tools.chunker_tool": MagicMock(chunk_text=lambda t: ["chunk1"])}):
            resp = client.post(
                f"{LTI_PREFIX}/check",
                json={"text": "This is a sufficiently long text for plagiarism checking.", "user_email": "s@test.com"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "plagiarism_score" in data
