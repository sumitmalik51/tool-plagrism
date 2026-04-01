"""Tests for user signup / login service and auth API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.database import get_db
from app.services.auth_service import (
    AuthError,
    create_access_token,
    get_user_by_id,
    login,
    signup,
    verify_access_token,
)
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_db():
    """Reset all tables before each test."""
    db = get_db()
    db.execute("DELETE FROM shared_reports")
    db.execute("DELETE FROM payments")
    db.execute("DELETE FROM document_fingerprints")
    db.execute("DELETE FROM scans")
    db.execute("DELETE FROM documents")
    db.execute("DELETE FROM user_api_keys")
    db.execute("DELETE FROM users")
    yield


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests — auth_service functions
# ═══════════════════════════════════════════════════════════════════════════

class TestSignup:
    def test_signup_success(self):
        result = signup("Alice", "alice@example.com", "secret123")
        assert result["user"]["email"] == "alice@example.com"
        assert result["user"]["name"] == "Alice"
        assert isinstance(result["token"], str)
        assert len(result["token"]) > 20

    def test_signup_duplicate_email(self):
        signup("Alice", "alice@example.com", "secret123")
        with pytest.raises(AuthError, match="already exists"):
            signup("Bob", "alice@example.com", "otherpass")

    def test_signup_short_password(self):
        with pytest.raises(AuthError, match="at least 6"):
            signup("Alice", "alice@example.com", "ab")

    def test_signup_invalid_email(self):
        with pytest.raises(AuthError, match="valid email"):
            signup("Alice", "no-at-sign", "secret123")

    def test_signup_empty_name(self):
        with pytest.raises(AuthError, match="Name is required"):
            signup("", "alice@example.com", "secret123")

    def test_signup_whitespace_name_rejected(self):
        with pytest.raises(AuthError, match="Name is required"):
            signup("   ", "alice@example.com", "secret123")


class TestLogin:
    def test_login_success(self):
        signup("Alice", "alice@example.com", "secret123")
        result = login("alice@example.com", "secret123")
        assert result["user"]["email"] == "alice@example.com"
        assert "token" in result

    def test_login_wrong_password(self):
        signup("Alice", "alice@example.com", "secret123")
        with pytest.raises(AuthError, match="Invalid email or password"):
            login("alice@example.com", "wrongpass")

    def test_login_nonexistent_user(self):
        with pytest.raises(AuthError, match="Invalid email or password"):
            login("nobody@example.com", "secret123")

    def test_login_case_insensitive_email(self):
        signup("Alice", "Alice@Example.COM", "secret123")
        result = login("alice@example.com", "secret123")
        assert result["user"]["email"] == "alice@example.com"

    def test_login_empty_fields(self):
        with pytest.raises(AuthError, match="required"):
            login("", "")


class TestJWT:
    def test_create_and_verify_token(self):
        token = create_access_token(42, "alice@example.com")
        payload = verify_access_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["email"] == "alice@example.com"

    def test_invalid_token_returns_none(self):
        assert verify_access_token("not.a.valid.token") is None

    def test_tampered_token_returns_none(self):
        token = create_access_token(1, "alice@example.com")
        # Flip a character in the signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert verify_access_token(tampered) is None


class TestGetUser:
    def test_get_existing_user(self):
        result = signup("Alice", "alice@example.com", "secret123")
        user = get_user_by_id(result["user"]["id"])
        assert user is not None
        assert user["email"] == "alice@example.com"
        assert "name" in user
        assert "password" not in user  # password should NOT be returned

    def test_get_nonexistent_user(self):
        assert get_user_by_id(9999) is None


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests — API routes
# ═══════════════════════════════════════════════════════════════════════════

class TestSignupRoute:
    def test_signup_returns_201(self):
        res = client.post("/api/v1/auth/signup", json={
            "name": "Bob",
            "email": "bob@example.com",
            "password": "password123",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["user"]["email"] == "bob@example.com"
        assert data["user"]["name"] == "Bob"
        assert "token" in data

    def test_signup_short_password_422(self):
        res = client.post("/api/v1/auth/signup", json={
            "name": "Bob",
            "email": "bob@example.com",
            "password": "ab",
        })
        assert res.status_code == 422

    def test_signup_duplicate_400(self):
        client.post("/api/v1/auth/signup", json={
            "name": "Bob",
            "email": "bob@example.com",
            "password": "password123",
        })
        res = client.post("/api/v1/auth/signup", json={
            "name": "Bob2",
            "email": "bob@example.com",
            "password": "password456",
        })
        assert res.status_code == 400
        assert "already exists" in res.json()["detail"]


class TestLoginRoute:
    def test_login_success(self):
        client.post("/api/v1/auth/signup", json={
            "name": "Bob",
            "email": "bob@example.com",
            "password": "password123",
        })
        res = client.post("/api/v1/auth/login", json={
            "email": "bob@example.com",
            "password": "password123",
        })
        assert res.status_code == 200
        assert "token" in res.json()

    def test_login_bad_password(self):
        client.post("/api/v1/auth/signup", json={
            "name": "Bob",
            "email": "bob@example.com",
            "password": "password123",
        })
        res = client.post("/api/v1/auth/login", json={
            "email": "bob@example.com",
            "password": "wrongpassword",
        })
        assert res.status_code == 401


class TestMeRoute:
    def test_me_with_valid_token(self):
        res = client.post("/api/v1/auth/signup", json={
            "name": "Bob",
            "email": "bob@example.com",
            "password": "password123",
        })
        token = res.json()["token"]
        me_res = client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert me_res.status_code == 200
        assert me_res.json()["email"] == "bob@example.com"
        assert me_res.json()["name"] == "Bob"

    def test_me_without_token(self):
        res = client.get("/api/v1/auth/me")
        assert res.status_code == 401

    def test_me_with_invalid_token(self):
        res = client.get("/api/v1/auth/me", headers={
            "Authorization": "Bearer fake-token-12345",
        })
        assert res.status_code == 401


class TestAuthPages:
    def test_login_page_served(self):
        res = client.get("/login")
        assert res.status_code == 200
        assert "Sign In" in res.text

    def test_signup_page_served(self):
        res = client.get("/signup")
        assert res.status_code == 200
        assert "Create your account" in res.text
