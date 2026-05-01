"""API key management service — generate, validate, revoke user API keys."""

from __future__ import annotations

import hashlib
import hmac
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
    """Hash an API key for storage.

    Uses HMAC-SHA256 with `settings.api_key_pepper` when configured — a
    stolen DB without the pepper cannot be brute-forced offline. When the
    pepper is empty, falls back to bare SHA-256 so existing keys hashed
    without a pepper continue to validate. Rotate by setting the pepper and
    asking users to regenerate keys.
    """
    raw_bytes = raw_key.encode()
    pepper = (settings.api_key_pepper or "").encode()
    if pepper:
        return hmac.new(pepper, raw_bytes, hashlib.sha256).hexdigest()
    return hashlib.sha256(raw_bytes).hexdigest()


def _hash_candidates(raw_key: str) -> list[str]:
    """Return all hashes a raw key could match against.

    During pepper rollout we have to validate keys created BEFORE the pepper
    was set (bare SHA-256) and keys created AFTER (HMAC). Look up both.
    """
    raw_bytes = raw_key.encode()
    sha = hashlib.sha256(raw_bytes).hexdigest()
    pepper = (settings.api_key_pepper or "").encode()
    if pepper:
        hmac_hash = hmac.new(pepper, raw_bytes, hashlib.sha256).hexdigest()
        # HMAC first — the common case once rollout completes.
        return [hmac_hash, sha]
    return [sha]


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


def delete_api_key(user_id: int, key_id: int) -> bool:
    """Permanently delete an API key. Returns True if found and deleted."""
    db = get_db()
    affected = db.execute(
        "DELETE FROM user_api_keys WHERE id = ? AND user_id = ?",
        (key_id, user_id),
    )
    if affected:
        logger.info("api_key_deleted", user_id=user_id, key_id=key_id)
    return bool(affected)


def regenerate_api_key(user_id: int, key_id: int) -> dict[str, Any] | None:
    """Regenerate an existing API key — replaces the hash/prefix, keeps name and id."""
    db = get_db()
    row = db.fetch_one(
        "SELECT id, name FROM user_api_keys WHERE id = ? AND user_id = ? AND is_active = 1",
        (key_id, user_id),
    )
    if not row:
        return None

    raw_key = _KEY_PREFIX + secrets.token_urlsafe(32)
    prefix = raw_key[:12] + "…"
    key_hash = _hash_key(raw_key)

    db.execute(
        "UPDATE user_api_keys SET key_prefix = ?, key_hash = ?, last_used_at = NULL WHERE id = ? AND user_id = ?",
        (prefix, key_hash, key_id, user_id),
    )
    logger.info("api_key_regenerated", user_id=user_id, key_id=key_id)

    return {
        "id": row["id"],
        "key": raw_key,
        "prefix": prefix,
        "name": row["name"],
    }


def validate_api_key(raw_key: str) -> dict[str, Any] | None:
    """Validate a raw API key. Returns user info if valid, None otherwise.

    Also updates ``last_used_at`` timestamp.

    During pepper rollout we look up against BOTH the new HMAC hash and the
    legacy bare-SHA-256 hash, so existing keys keep working until users
    regenerate them.
    """
    if not raw_key or not raw_key.startswith(_KEY_PREFIX):
        return None

    db = get_db()
    candidates = _hash_candidates(raw_key)

    # Try each candidate hash. Most deployments will hit the first; the
    # fallback only fires for legacy keys hashed before the pepper was set.
    row = None
    for candidate in candidates:
        row = db.fetch_one(
            "SELECT k.id, k.user_id, k.name, u.email, u.plan_type "
            "FROM user_api_keys k JOIN users u ON k.user_id = u.id "
            "WHERE k.key_hash = ? AND k.is_active = 1",
            (candidate,),
        )
        if row:
            break
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
