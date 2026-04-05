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
    (
        4,
        "Add teams and team_members tables",
        """
        CREATE TABLE IF NOT EXISTS teams (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            owner_id    INTEGER NOT NULL REFERENCES users(id),
            plan_type   TEXT NOT NULL DEFAULT 'team',
            max_seats   INTEGER NOT NULL DEFAULT 5,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        ---
        CREATE TABLE IF NOT EXISTS team_members (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id     INTEGER NOT NULL REFERENCES teams(id),
            user_id     INTEGER NOT NULL REFERENCES users(id),
            role        TEXT NOT NULL DEFAULT 'member',
            invited_by  INTEGER REFERENCES users(id),
            joined_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(team_id, user_id)
        );
        ---
        CREATE TABLE IF NOT EXISTS team_invites (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id     INTEGER NOT NULL REFERENCES teams(id),
            email       TEXT NOT NULL,
            token       TEXT NOT NULL UNIQUE,
            invited_by  INTEGER NOT NULL REFERENCES users(id),
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        ---
        CREATE INDEX IF NOT EXISTS idx_team_members_team ON team_members(team_id);
        ---
        CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id);
        ---
        CREATE INDEX IF NOT EXISTS idx_team_invites_token ON team_invites(token);
        """,
    ),
    (
        5,
        "Add webhook_subscriptions table",
        """
        CREATE TABLE IF NOT EXISTS webhook_subscriptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            url         TEXT NOT NULL,
            events      TEXT NOT NULL DEFAULT 'scan.complete',
            secret      TEXT NOT NULL,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        ---
        CREATE INDEX IF NOT EXISTS idx_webhooks_user ON webhook_subscriptions(user_id);
        """,
    ),
    (
        6,
        "Add stripe_customer_id column to users",
        """
        ALTER TABLE users ADD COLUMN stripe_customer_id TEXT NULL;
        """,
    ),
    (
        7,
        "Add LTI platform and state tables",
        """
        CREATE TABLE IF NOT EXISTS lti_platforms (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer          TEXT NOT NULL UNIQUE,
            client_id       TEXT NOT NULL,
            auth_endpoint   TEXT NOT NULL,
            token_endpoint  TEXT NOT NULL,
            jwks_url        TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        ---
        CREATE TABLE IF NOT EXISTS lti_states (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            state       TEXT NOT NULL UNIQUE,
            nonce       TEXT NOT NULL,
            issuer      TEXT,
            client_id   TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        ---
        CREATE INDEX IF NOT EXISTS idx_lti_states_state ON lti_states(state);
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
    (
        4,
        "Add teams and team_members tables",
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'teams')
        CREATE TABLE teams (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            name        NVARCHAR(200) NOT NULL,
            owner_id    INT NOT NULL REFERENCES users(id),
            plan_type   NVARCHAR(20) NOT NULL DEFAULT 'team',
            max_seats   INT NOT NULL DEFAULT 5,
            created_at  DATETIME2 NOT NULL DEFAULT GETUTCDATE()
        );
        ---
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'team_members')
        CREATE TABLE team_members (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            team_id     INT NOT NULL REFERENCES teams(id),
            user_id     INT NOT NULL REFERENCES users(id),
            role        NVARCHAR(20) NOT NULL DEFAULT 'member',
            invited_by  INT NULL REFERENCES users(id),
            joined_at   DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
            UNIQUE(team_id, user_id)
        );
        ---
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'team_invites')
        CREATE TABLE team_invites (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            team_id     INT NOT NULL REFERENCES teams(id),
            email       NVARCHAR(255) NOT NULL,
            token       NVARCHAR(128) NOT NULL UNIQUE,
            invited_by  INT NOT NULL REFERENCES users(id),
            status      NVARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at  DATETIME2 NOT NULL DEFAULT GETUTCDATE()
        );
        ---
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_team_members_team')
        CREATE INDEX idx_team_members_team ON team_members(team_id);
        ---
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_team_members_user')
        CREATE INDEX idx_team_members_user ON team_members(user_id);
        ---
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_team_invites_token')
        CREATE INDEX idx_team_invites_token ON team_invites(token);
        """,
    ),
    (
        5,
        "Add webhook_subscriptions table",
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'webhook_subscriptions')
        CREATE TABLE webhook_subscriptions (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            user_id     INT NOT NULL REFERENCES users(id),
            url         NVARCHAR(500) NOT NULL,
            events      NVARCHAR(200) NOT NULL DEFAULT 'scan.complete',
            secret      NVARCHAR(128) NOT NULL,
            is_active   BIT NOT NULL DEFAULT 1,
            created_at  DATETIME2 NOT NULL DEFAULT GETUTCDATE()
        );
        ---
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_webhooks_user')
        CREATE INDEX idx_webhooks_user ON webhook_subscriptions(user_id);
        """,
    ),
    (
        6,
        "Add stripe_customer_id column to users",
        """
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'stripe_customer_id')
        ALTER TABLE users ADD stripe_customer_id NVARCHAR(100) NULL;
        """,
    ),
    (
        7,
        "Add LTI platform and state tables",
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'lti_platforms')
        CREATE TABLE lti_platforms (
            id              INT IDENTITY(1,1) PRIMARY KEY,
            issuer          NVARCHAR(500) NOT NULL UNIQUE,
            client_id       NVARCHAR(255) NOT NULL,
            auth_endpoint   NVARCHAR(500) NOT NULL,
            token_endpoint  NVARCHAR(500) NOT NULL,
            jwks_url        NVARCHAR(500) NOT NULL,
            created_at      DATETIME2 NOT NULL DEFAULT GETUTCDATE()
        );
        ---
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'lti_states')
        CREATE TABLE lti_states (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            state       NVARCHAR(128) NOT NULL UNIQUE,
            nonce       NVARCHAR(128) NOT NULL,
            issuer      NVARCHAR(500),
            client_id   NVARCHAR(255),
            created_at  DATETIME2 NOT NULL DEFAULT GETUTCDATE()
        );
        ---
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_lti_states_state')
        CREATE INDEX idx_lti_states_state ON lti_states(state);
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
