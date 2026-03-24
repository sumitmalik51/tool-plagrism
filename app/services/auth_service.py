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
from datetime import datetime, timedelta, timezone
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
    verification_token = secrets.token_urlsafe(32)

    # Grant a 3-day Pro trial to every new user
    trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ensure_trial_ends_at_column(db)
    user_id = db.execute(
        "INSERT INTO users (name, email, password, plan_type, trial_ends_at) VALUES (?, ?, ?, ?, ?)",
        (name, email, hashed, "pro", trial_ends_at),
    )

    # Store verification token
    _ensure_email_verifications_table(db)
    try:
        db.execute(
            "INSERT INTO email_verifications (user_id, token) VALUES (?, ?)",
            (user_id, verification_token),
        )
    except Exception as exc:
        logger.warning("email_verification_insert_failed", error=str(exc))

    token = create_access_token(user_id, email)
    logger.info("user_created", user_id=user_id, email=email)

    return {
        "user": {"id": user_id, "name": name, "email": email, "plan_type": "pro", "trial_ends_at": trial_ends_at},
        "token": token,
        "verification_token": verification_token,
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

    # Fetch plan_type and trial info for the user
    _ensure_trial_ends_at_column(db)
    user_full = db.fetch_one(
        "SELECT plan_type, trial_ends_at FROM users WHERE id = ?", (row["id"],)
    )
    plan_type = user_full["plan_type"] if user_full else "free"
    trial_ends_at = user_full.get("trial_ends_at") if user_full else None

    # Check if trial has expired — downgrade to free
    plan_type, trial_ends_at = _check_trial_expiry(db, row["id"], plan_type, trial_ends_at)

    return {
        "user": {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "plan_type": plan_type,
            "trial_ends_at": trial_ends_at,
        },
        "token": token,
    }


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Fetch a user record by ID (without password).

    Also checks and handles trial expiry automatically.
    """
    db = get_db()
    _ensure_trial_ends_at_column(db)
    row = db.fetch_one(
        "SELECT id, name, email, is_paid, plan_type, trial_ends_at, created_at FROM users WHERE id = ?",
        (user_id,),
    )
    if row:
        plan_type, trial_ends_at = _check_trial_expiry(
            db, row["id"], row.get("plan_type", "free"), row.get("trial_ends_at")
        )
        row["plan_type"] = plan_type
        row["trial_ends_at"] = trial_ends_at
    return row


def update_user_plan(user_id: int, plan_type: str) -> bool:
    """Update a user's subscription plan.  Returns True on success."""
    valid_plans = ("free", "pro", "premium")
    if plan_type not in valid_plans:
        raise AuthError(f"Invalid plan type. Must be one of: {', '.join(valid_plans)}")

    db = get_db()
    is_paid = 1 if plan_type != "free" else 0
    affected = db.execute(
        "UPDATE users SET plan_type = ?, is_paid = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (plan_type, is_paid, user_id),
    )
    if affected:
        logger.info("user_plan_updated", user_id=user_id, plan_type=plan_type)
    return bool(affected)


# ---------------------------------------------------------------------------
# Password reset helpers
# ---------------------------------------------------------------------------

def create_password_reset_token(email: str) -> str | None:
    """Generate a password-reset token for the user with the given email.

    Returns the token string, or ``None`` if no user was found.
    The token expires in 1 hour.
    """
    email = email.strip().lower()
    db = get_db()
    user = db.fetch_one("SELECT id FROM users WHERE email = ?", (email,))
    if not user:
        return None

    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + 3600  # 1 hour

    # Store token in a simple table (create if needed)
    try:
        db.execute(
            "INSERT INTO password_resets (user_id, token, expires_at) VALUES (?, ?, ?)",
            (user["id"], token, expires_at),
        )
    except Exception:
        # Table might not exist yet in older DBs — create it
        _ensure_password_resets_table(db)
        db.execute(
            "INSERT INTO password_resets (user_id, token, expires_at) VALUES (?, ?, ?)",
            (user["id"], token, expires_at),
        )

    logger.info("password_reset_token_created", user_id=user["id"], email=email)
    return token


def reset_password(token: str, new_password: str) -> bool:
    """Reset a user's password using a valid token.  Returns True on success."""
    if len(new_password) < 6:
        raise AuthError("Password must be at least 6 characters.")

    db = get_db()

    _ensure_password_resets_table(db)

    row = db.fetch_one(
        "SELECT user_id, expires_at FROM password_resets WHERE token = ?",
        (token,),
    )
    if not row:
        raise AuthError("Invalid or expired reset link.")

    if int(row["expires_at"]) < int(time.time()):
        # Clean up expired token
        db.execute("DELETE FROM password_resets WHERE token = ?", (token,))
        raise AuthError("Reset link has expired. Please request a new one.")

    hashed = _hash_password(new_password)
    db.execute(
        "UPDATE users SET password = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (hashed, row["user_id"]),
    )
    # Remove the used token
    db.execute("DELETE FROM password_resets WHERE token = ?", (token,))

    logger.info("password_reset_completed", user_id=row["user_id"])
    return True


def _ensure_password_resets_table(db) -> None:
    """Create the password_resets table if it doesn't exist."""
    try:
        db.execute(
            """CREATE TABLE IF NOT EXISTS password_resets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                token       TEXT NOT NULL,
                expires_at  INTEGER NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
    except Exception:
        # MSSQL syntax
        try:
            db.execute(
                """IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'password_resets')
                CREATE TABLE password_resets (
                    id          INT IDENTITY(1,1) PRIMARY KEY,
                    user_id     INT NOT NULL,
                    token       NVARCHAR(255) NOT NULL,
                    expires_at  INT NOT NULL,
                    created_at  DATETIME2 NOT NULL DEFAULT GETUTCDATE()
                )"""
            )
        except Exception:
            pass  # Table likely already exists


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

def verify_email(token: str) -> bool:
    """Verify a user's email using a verification token. Returns True on success."""
    db = get_db()
    _ensure_email_verifications_table(db)

    row = db.fetch_one(
        "SELECT user_id FROM email_verifications WHERE token = ?",
        (token,),
    )
    if not row:
        raise AuthError("Invalid or already used verification link.")

    # Mark user as verified — add email_verified column if needed
    _ensure_email_verified_column(db)
    db.execute(
        "UPDATE users SET email_verified = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (row["user_id"],),
    )
    # Remove the used token
    db.execute("DELETE FROM email_verifications WHERE token = ?", (token,))

    logger.info("email_verified", user_id=row["user_id"])
    return True


def is_email_verified(user_id: int) -> bool:
    """Check if a user's email is verified."""
    db = get_db()
    _ensure_email_verified_column(db)
    row = db.fetch_one(
        "SELECT email_verified FROM users WHERE id = ?", (user_id,)
    )
    if not row:
        return False
    return bool(row.get("email_verified", 0))


def resend_verification_token(user_id: int) -> str:
    """Generate a new verification token for the user."""
    db = get_db()
    _ensure_email_verifications_table(db)

    # Remove old tokens
    db.execute("DELETE FROM email_verifications WHERE user_id = ?", (user_id,))

    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO email_verifications (user_id, token) VALUES (?, ?)",
        (user_id, token),
    )
    logger.info("verification_token_resent", user_id=user_id)
    return token


def _ensure_email_verifications_table(db) -> None:
    """Create the email_verifications table if it doesn't exist."""
    try:
        db.execute(
            """CREATE TABLE IF NOT EXISTS email_verifications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                token       TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
    except Exception:
        try:
            db.execute(
                """IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'email_verifications')
                CREATE TABLE email_verifications (
                    id          INT IDENTITY(1,1) PRIMARY KEY,
                    user_id     INT NOT NULL,
                    token       NVARCHAR(255) NOT NULL,
                    created_at  DATETIME2 NOT NULL DEFAULT GETUTCDATE()
                )"""
            )
        except Exception:
            pass


def _ensure_email_verified_column(db) -> None:
    """Add email_verified column to users table if not present."""
    try:
        db.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
    except Exception:
        try:
            db.execute(
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'email_verified') "
                "ALTER TABLE users ADD email_verified BIT NOT NULL DEFAULT 0"
            )
        except Exception:
            pass  # Column already exists


def _ensure_trial_ends_at_column(db) -> None:
    """Add trial_ends_at column to users table if not present."""
    try:
        db.execute("ALTER TABLE users ADD COLUMN trial_ends_at TEXT NULL")
    except Exception:
        try:
            db.execute(
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'trial_ends_at') "
                "ALTER TABLE users ADD trial_ends_at DATETIME2 NULL"
            )
        except Exception:
            pass  # Column already exists


def _check_trial_expiry(db, user_id: int, plan_type: str, trial_ends_at) -> tuple[str, str | None]:
    """Check if a user's Pro trial has expired and downgrade if necessary.

    Returns (effective_plan_type, trial_ends_at_str).
    """
    if not trial_ends_at:
        return plan_type, None

    # Parse trial_ends_at (could be ISO string or datetime)
    trial_str = str(trial_ends_at)
    try:
        if "T" in trial_str:
            trial_dt = datetime.fromisoformat(trial_str.replace("Z", "+00:00"))
        else:
            trial_dt = datetime.fromisoformat(trial_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return plan_type, trial_str

    now = datetime.now(timezone.utc)
    if now >= trial_dt and plan_type == "pro":
        # Trial expired — check if user has any successful payment
        from app.services.database import get_db as _get_db
        payment = db.fetch_one(
            "SELECT id FROM payments WHERE user_id = ? AND status = 'paid'",
            (user_id,),
        )
        if not payment:
            # No payment → downgrade to free
            db.execute(
                "UPDATE users SET plan_type = 'free', is_paid = 0, trial_ends_at = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user_id,),
            )
            logger.info("trial_expired_downgraded", user_id=user_id)
            return "free", None

    return plan_type, trial_str
