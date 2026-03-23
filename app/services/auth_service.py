"""User authentication service — signup, login, JWT management.

Uses the database abstraction layer (Azure SQL in production, SQLite
in local dev) for user storage and PBKDF2 for password hashing.
JWTs are issued on login and verified by the auth middleware.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Any

import jwt  # PyJWT

from app.config import settings
from app.services.database import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Password hashing helpers (PBKDF2-HMAC-SHA256 — stdlib, no C deps)
# ---------------------------------------------------------------------------
_HASH_ITERATIONS = 260_000  # OWASP 2023 recommendation for PBKDF2-SHA256


def _hash_password(password: str) -> str:
    """Return ``salt:hash`` string using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _HASH_ITERATIONS
    ).hex()
    return f"{salt}:{pw_hash}"


def _verify_password(password: str, stored: str) -> bool:
    """Constant-time comparison of *password* against *stored* ``salt:hash``."""
    salt, expected_hash = stored.split(":", 1)
    computed = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _HASH_ITERATIONS
    ).hex()
    return hmac.compare_digest(computed, expected_hash)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
_JWT_ALGORITHM = "HS256"


def _get_jwt_secret() -> str:
    """Return the JWT signing secret (create one automatically if missing)."""
    secret = settings.jwt_secret
    if not secret:
        # Fall back to a runtime-generated secret (tokens won't survive restart)
        secret = os.environ.setdefault("PG_JWT_SECRET", secrets.token_hex(32))
    return secret


def create_access_token(user_id: int, email: str) -> str:
    """Create a signed JWT for the given user."""
    now = time.time()
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now),
        "exp": int(now + settings.jwt_expiry_seconds),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


def verify_access_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT.  Returns the payload dict or ``None``."""
    try:
        payload = jwt.decode(
            token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.info("jwt_expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("jwt_invalid", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Raised for authentication / validation failures."""


def signup(name: str, email: str, password: str) -> dict[str, Any]:
    """Register a new user.  Returns ``{user, token}``."""
    # Basic validation
    if not name or not name.strip():
        raise AuthError("Name is required.")
    if not email or "@" not in email:
        raise AuthError("A valid email is required.")
    if len(password) < 6:
        raise AuthError("Password must be at least 6 characters.")

    email = email.strip().lower()
    name = name.strip()

    db = get_db()

    # Check duplicate
    existing = db.fetch_one(
        "SELECT id FROM users WHERE email = ?", (email,)
    )
    if existing:
        raise AuthError("An account with this email already exists.")

    hashed = _hash_password(password)
    user_id = db.execute(
        "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
        (name, email, hashed),
    )

    token = create_access_token(user_id, email)
    logger.info("user_created", user_id=user_id, email=email)

    return {
        "user": {"id": user_id, "name": name, "email": email},
        "token": token,
    }


def login(email: str, password: str) -> dict[str, Any]:
    """Authenticate user credentials.  Returns ``{user, token}``."""
    if not email or not password:
        raise AuthError("Email and password are required.")

    email = email.strip().lower()

    db = get_db()
    row = db.fetch_one(
        "SELECT id, name, email, password FROM users WHERE email = ?",
        (email,),
    )
    if not row:
        raise AuthError("Invalid email or password.")

    if not _verify_password(password, row["password"]):
        raise AuthError("Invalid email or password.")

    token = create_access_token(row["id"], row["email"])
    logger.info("user_login", user_id=row["id"], email=row["email"])

    return {
        "user": {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
        },
        "token": token,
    }


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Fetch a user record by ID (without password)."""
    db = get_db()
    row = db.fetch_one(
        "SELECT id, name, email, is_paid, created_at FROM users WHERE id = ?",
        (user_id,),
    )
    return row
