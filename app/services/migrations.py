"""Lightweight database migration runner.

Tracks applied migrations in a ``schema_migrations`` table and applies
new ones in order.  Migrations are defined as ``(version, description, sql)``
tuples.  The runner is idempotent — it only applies migrations that
haven't been applied yet.

Usage::

    from app.services.migrations import run_migrations
    run_migrations(db)
"""

from __future__ import annotations

from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Migration definitions — append new migrations at the bottom
# ---------------------------------------------------------------------------

# Each migration is (version: int, description: str, sql: str).
# SQL may contain multiple statements separated by ``---``.
# Use ``IF NOT EXISTS`` / ``IF EXISTS`` guards for safety.
MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "Add email_verifications table",
        """
        CREATE TABLE IF NOT EXISTS email_verifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            token       TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        2,
        "Add password_resets table",
        """
        CREATE TABLE IF NOT EXISTS password_resets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            token       TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            used        INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        3,
        "Add indexes on user_id foreign keys",
        """
        CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
        ---
        CREATE INDEX IF NOT EXISTS idx_email_verifications_user ON email_verifications(user_id);
        ---
        CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_resets(user_id);
        """,
    ),
]

# MSSQL variants — same version numbers, different syntax
MIGRATIONS_MSSQL: list[tuple[int, str, str]] = [
    (
        1,
        "Add email_verifications table",
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'email_verifications')
        CREATE TABLE email_verifications (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            user_id     INT NOT NULL,
            token       NVARCHAR(255) NOT NULL,
            created_at  DATETIME2 NOT NULL DEFAULT GETUTCDATE()
        );
        """,
    ),
    (
        2,
        "Add password_resets table",
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'password_resets')
        CREATE TABLE password_resets (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            user_id     INT NOT NULL,
            token       NVARCHAR(255) NOT NULL,
            expires_at  DATETIME2 NOT NULL,
            used        BIT NOT NULL DEFAULT 0,
            created_at  DATETIME2 NOT NULL DEFAULT GETUTCDATE()
        );
        """,
    ),
    (
        3,
        "Add indexes on user_id foreign keys",
        """
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_payments_user_id')
        CREATE INDEX idx_payments_user_id ON payments(user_id);
        ---
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_email_verifications_user')
        CREATE INDEX idx_email_verifications_user ON email_verifications(user_id);
        ---
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_password_resets_user')
        CREATE INDEX idx_password_resets_user ON password_resets(user_id);
        """,
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _ensure_migrations_table(db: Any, is_mssql: bool) -> None:
    """Create the schema_migrations tracking table if it doesn't exist."""
    if is_mssql:
        db.execute(
            "IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'schema_migrations') "
            "CREATE TABLE schema_migrations ("
            "  version INT NOT NULL PRIMARY KEY,"
            "  description NVARCHAR(255) NOT NULL,"
            "  applied_at DATETIME2 NOT NULL DEFAULT GETUTCDATE()"
            ")"
        )
    else:
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version INTEGER PRIMARY KEY,"
            "  description TEXT NOT NULL,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )


def _get_applied_versions(db: Any) -> set[int]:
    """Return the set of already-applied migration versions."""
    rows = db.fetch_all("SELECT version FROM schema_migrations", ())
    return {r["version"] for r in rows}


def _split_sql(sql: str) -> list[str]:
    """Split SQL on ``---`` separators."""
    return [s.strip() for s in sql.split("---") if s.strip()]


def run_migrations(db: Any) -> int:
    """Apply any outstanding migrations.

    Returns the number of newly applied migrations.
    """
    is_mssql = hasattr(db, "_connection_string")  # AzureSQLDatabase has _connection_string
    _ensure_migrations_table(db, is_mssql)

    applied = _get_applied_versions(db)
    migrations = MIGRATIONS_MSSQL if is_mssql else MIGRATIONS
    count = 0

    for version, description, sql in sorted(migrations, key=lambda m: m[0]):
        if version in applied:
            continue
        logger.info("applying_migration", version=version, description=description)
        for statement in _split_sql(sql):
            db.execute(statement)
        db.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            (version, description),
        )
        count += 1
        logger.info("migration_applied", version=version)

    if count:
        logger.info("migrations_complete", applied_count=count)
    return count
