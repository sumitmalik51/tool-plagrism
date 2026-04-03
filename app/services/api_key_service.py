"""API key management service — generate, validate, revoke user API keys."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from app.config import settings
from app.services.database import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

_KEY_PREFIX = "pg_"


def _max_keys_for_plan(plan_type: str) -> int:
    """Return the max active API keys allowed for the given plan."""
    if plan_type == "premium":
        return settings.api_keys_limit_premium
    return settings.api_keys_limit_pro  # pro (and fallback)


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key (we never store the full key)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_api_key(user_id: int, name: str = "Default", plan_type: str = "pro") -> dict[str, Any]:
    """Generate a new API key for the user.

    Returns the full key (shown once) and key metadata.
    """
    db = get_db()

    # Check limit based on plan
    max_keys = _max_keys_for_plan(plan_type)
    existing = db.fetch_all(
        "SELECT id FROM user_api_keys WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    if len(existing) >= max_keys:
        raise ValueError(f"Maximum {max_keys} active API keys allowed on your plan.")

    raw_key = _KEY_PREFIX + secrets.token_urlsafe(32)
    prefix = raw_key[:12] + "…"
    key_hash = _hash_key(raw_key)

    key_id = db.execute(
        "INSERT INTO user_api_keys (user_id, key_prefix, key_hash, name) VALUES (?, ?, ?, ?)",
        (user_id, prefix, key_hash, name[:100]),
    )

    logger.info("api_key_created", user_id=user_id, key_id=key_id, name=name)

    return {
        "id": key_id,
        "key": raw_key,  # Only returned once at creation
        "prefix": prefix,
        "name": name[:100],
    }


def list_api_keys(user_id: int) -> list[dict[str, Any]]:
    """List all API keys for a user (without the full key)."""
    db = get_db()
    rows = db.fetch_all(
        "SELECT id, key_prefix, name, is_active, last_used_at, created_at "
        "FROM user_api_keys WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )
    return [
        {
            "id": r["id"],
            "prefix": r["key_prefix"],
            "name": r["name"],
            "is_active": bool(r["is_active"]),
            "last_used_at": r["last_used_at"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def revoke_api_key(user_id: int, key_id: int) -> bool:
    """Revoke (deactivate) an API key. Returns True if found and revoked."""
    db = get_db()
    affected = db.execute(
        "UPDATE user_api_keys SET is_active = 0 WHERE id = ? AND user_id = ?",
        (key_id, user_id),
    )
    if affected:
        logger.info("api_key_revoked", user_id=user_id, key_id=key_id)
    return bool(affected)


def validate_api_key(raw_key: str) -> dict[str, Any] | None:
    """Validate a raw API key. Returns user info if valid, None otherwise.

    Also updates ``last_used_at`` timestamp.
    """
    if not raw_key or not raw_key.startswith(_KEY_PREFIX):
        return None

    db = get_db()
    key_hash = _hash_key(raw_key)

    row = db.fetch_one(
        "SELECT k.id, k.user_id, k.name, u.email, u.plan_type "
        "FROM user_api_keys k JOIN users u ON k.user_id = u.id "
        "WHERE k.key_hash = ? AND k.is_active = 1",
        (key_hash,),
    )
    if not row:
        return None

    # Update last_used_at
    db.execute(
        "UPDATE user_api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
        (row["id"],),
    )

    return {
        "key_id": row["id"],
        "user_id": row["user_id"],
        "key_name": row["name"],
        "email": row["email"],
        "plan_type": row["plan_type"],
    }
