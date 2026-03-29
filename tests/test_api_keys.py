"""Tests for API key management — create, list, revoke, validate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_service import create_access_token, signup
from app.services.api_key_service import (
    _MAX_KEYS_PER_USER,
    create_api_key,
    list_api_keys,
    revoke_api_key,
    validate_api_key,
)
from app.services.database import get_db

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_db():
    db = get_db()
    db.execute("DELETE FROM user_api_keys")
    db.execute("DELETE FROM users")
    yield


def _create_user(plan: str = "pro") -> tuple[int, str]:
    """Create a user with the given plan and return (user_id, token)."""
    result = signup("Test User", f"apitest_{plan}@example.com", "secret123")
    uid = result["user"]["id"]
    db = get_db()
    db.execute("UPDATE users SET plan_type = ? WHERE id = ?", (plan, uid))
    token = create_access_token(uid)
    return uid, token


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests — api_key_service functions
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateApiKey:
    def test_creates_key_with_prefix(self):
        uid, _ = _create_user()
        result = create_api_key(uid, "CI Key")
        assert result["key"].startswith("pg_")
        assert result["prefix"].startswith("pg_")
        assert result["name"] == "CI Key"
        assert result["id"] > 0

    def test_max_keys_enforced(self):
        uid, _ = _create_user()
        for i in range(_MAX_KEYS_PER_USER):
            create_api_key(uid, f"Key {i}")
        with pytest.raises(ValueError, match="Maximum"):
            create_api_key(uid, "One too many")


class TestListApiKeys:
    def test_list_empty(self):
        uid, _ = _create_user()
        keys = list_api_keys(uid)
        assert keys == []

    def test_list_returns_metadata(self):
        uid, _ = _create_user()
        create_api_key(uid, "My Key")
        keys = list_api_keys(uid)
        assert len(keys) == 1
        assert keys[0]["name"] == "My Key"
        assert keys[0]["is_active"] is True
        # Full key should NOT be in list
        assert "key" not in keys[0]


class TestRevokeApiKey:
    def test_revoke_success(self):
        uid, _ = _create_user()
        result = create_api_key(uid, "To Revoke")
        assert revoke_api_key(uid, result["id"]) is True
        keys = list_api_keys(uid)
        assert keys[0]["is_active"] is False

    def test_revoke_wrong_user(self):
        uid1, _ = _create_user("pro")
        uid2, _ = _create_user("premium")
        result = create_api_key(uid1, "Owner's Key")
        assert revoke_api_key(uid2, result["id"]) is False

    def test_revoke_nonexistent(self):
        uid, _ = _create_user()
        assert revoke_api_key(uid, 9999) is False


class TestValidateApiKey:
    def test_valid_key(self):
        uid, _ = _create_user()
        result = create_api_key(uid, "Valid")
        user = validate_api_key(result["key"])
        assert user is not None
        assert user["user_id"] == uid

    def test_revoked_key_invalid(self):
        uid, _ = _create_user()
        result = create_api_key(uid, "Revoked")
        revoke_api_key(uid, result["id"])
        assert validate_api_key(result["key"]) is None

    def test_bad_prefix_invalid(self):
        assert validate_api_key("xyz_notakey") is None

    def test_empty_invalid(self):
        assert validate_api_key("") is None


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests — API endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestApiKeyEndpoints:
    def test_create_key_pro_user(self):
        _, token = _create_user("pro")
        res = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Test Key"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["key"].startswith("pg_")
        assert "won't be shown again" in data["message"]

    def test_create_key_free_user_forbidden(self):
        _, token = _create_user("free")
        res = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Free Key"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403
        assert "Pro or Premium" in res.json()["detail"]

    def test_list_keys(self):
        uid, token = _create_user("pro")
        create_api_key(uid, "Key A")
        res = client.get(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        keys = res.json()["keys"]
        assert len(keys) == 1
        assert keys[0]["name"] == "Key A"

    def test_revoke_key_endpoint(self):
        uid, token = _create_user("pro")
        result = create_api_key(uid, "To Revoke")
        res = client.post(
            "/api/v1/auth/api-keys/revoke",
            json={"key_id": result["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert res.json()["success"] is True

    def test_revoke_missing_key_id(self):
        _, token = _create_user("pro")
        res = client.post(
            "/api/v1/auth/api-keys/revoke",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 400

    def test_no_auth_header(self):
        res = client.get("/api/v1/auth/api-keys")
        assert res.status_code == 401
