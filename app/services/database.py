"""Database abstraction layer — Azure SQL (production) with SQLite fallback (dev).

Provides a unified interface for all database operations, automatically using
Azure SQL when ``PG_SQL_CONNECTION_STRING`` is set, or falling back to SQLite
for local development.

Usage::

    from app.services.database import get_db

    db = get_db()
    db.execute("INSERT INTO users (name, email) VALUES (?, ?)", ("Alice", "a@b.com"))
    rows = db.fetch_all("SELECT * FROM users WHERE email = ?", ("a@b.com",))
"""

from __future__ import annotations

import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Abstract interface
# ═══════════════════════════════════════════════════════════════════════════

class Database(ABC):
    """Minimal DB interface used by all services."""

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> int:
        """Execute a write query. Returns lastrowid (INSERT) or rowcount."""

    @abstractmethod
    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Fetch a single row as a dict, or None."""

    @abstractmethod
    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Fetch all matching rows as a list of dicts."""

    @abstractmethod
    def init_schema(self) -> None:
        """Create tables if they don't exist."""

    @abstractmethod
    def close(self) -> None:
        """Release any held connections."""


# ═══════════════════════════════════════════════════════════════════════════
# SQLite implementation (local development)
# ═══════════════════════════════════════════════════════════════════════════

class SQLiteDatabase(Database):
    """Thread-safe SQLite database for local development."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._local = threading.local()
        logger.info("db_backend", backend="sqlite", path=self._db_path)

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def execute(self, sql: str, params: tuple = ()) -> int:
        conn = self._conn()
        cursor = conn.execute(sql, params)
        conn.commit()
        trimmed = sql.strip().upper()
        if trimmed.startswith(("INSERT",)):
            return cursor.lastrowid  # type: ignore[return-value]
        return cursor.rowcount  # type: ignore[return-value]

    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        row = self._conn().execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        rows = self._conn().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def init_schema(self) -> None:
        conn = self._conn()
        conn.executescript(_SQLITE_SCHEMA)
        # Migration: add word_count column if missing (existing databases)
        try:
            conn.execute("SELECT word_count FROM usage_logs LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE usage_logs ADD COLUMN word_count INTEGER NOT NULL DEFAULT 0")
        # Migration: add stripe_customer_id column if missing
        try:
            conn.execute("SELECT stripe_customer_id FROM users LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT NULL")
        conn.commit()
        logger.info("db_schema_initialized", backend="sqlite")

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ═══════════════════════════════════════════════════════════════════════════
# Azure SQL implementation (production)
# ═══════════════════════════════════════════════════════════════════════════

class AzureSQLDatabase(Database):
    """Azure SQL Database via pyodbc."""

    def __init__(self, connection_string: str):
        import pyodbc
        self._connection_string = self._resolve_driver(connection_string, pyodbc)
        self._pyodbc = pyodbc
        self._local = threading.local()
        logger.info("db_backend", backend="azure_sql")

    @staticmethod
    def _resolve_driver(conn_str: str, pyodbc_mod: Any) -> str:
        """Replace the Driver= token with the best available ODBC driver.

        The env var may reference 'ODBC Driver 18 for SQL Server' but the
        local machine might only have 'ODBC Driver 17 for SQL Server' or
        the legacy 'SQL Server' driver.  This method finds the best match
        and rewrites the connection string so pyodbc.connect() succeeds.
        """
        import re
        available = pyodbc_mod.drivers()
        # Preference order: 18 > 17 > 13 > legacy
        preferred = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server",
            "SQL Server",
        ]
        best = next((d for d in preferred if d in available), None)
        if best is None:
            logger.warning("no_sql_server_odbc_driver_found", available=available)
            return conn_str  # return as-is, let pyodbc raise

        # Replace whatever Driver={...} is in the string
        new_str = re.sub(
            r"Driver=\{[^}]*\}", f"Driver={{{best}}}", conn_str, flags=re.IGNORECASE
        )
        if new_str != conn_str:
            logger.info("odbc_driver_resolved", requested="(from conn string)", using=best)
        return new_str

    def _conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            import time as _time
            last_err = None
            for attempt in range(4):  # up to 4 attempts (~15s total)
                try:
                    self._local.conn = self._pyodbc.connect(
                        self._connection_string,
                        autocommit=False,
                        timeout=30,
                    )
                    return self._local.conn
                except Exception as exc:
                    last_err = exc
                    err_code = getattr(exc, "args", ("",))[0] if exc.args else ""
                    # 40613 = DB not available (auto-pause waking)
                    # 08S01 = Communication link failure
                    # 08001 = Unable to connect
                    transient = any(c in str(err_code) for c in ("40613", "08S01", "08001"))
                    if not transient or attempt == 3:
                        raise
                    wait = (attempt + 1) * 2  # 2s, 4s, 6s
                    logger.warning(
                        "db_connect_retry",
                        attempt=attempt + 1,
                        wait_s=wait,
                        error=str(exc)[:100],
                    )
                    _time.sleep(wait)
            raise last_err  # unreachable, but satisfies type checker
        return self._local.conn

    def _reset_conn(self) -> None:
        """Drop the cached connection so the next _conn() call reconnects."""
        if hasattr(self._local, "conn") and self._local.conn:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _is_transient(self, exc: Exception) -> bool:
        """Return True if the error looks like a stale / auto-paused connection."""
        msg = str(exc)
        codes = ("40613", "08S01", "08001", "HYT00", "HY000", "01000",
                 "Communication link failure", "connection is broken",
                 "TCP Provider", "Login timeout", "Connection is not available",
                 "Adaptive Server connection failed", "connected party did not",
                 "established connection was aborted", "existing connection was forcibly closed",
                 "server closed the connection", "Operation timed out")
        return any(c.lower() in msg.lower() for c in codes)

    def execute(self, sql: str, params: tuple = ()) -> int:
        for attempt in range(2):
            conn = self._conn()
            cursor = conn.cursor()
            try:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                conn.commit()
                if sql.strip().upper().startswith("INSERT"):
                    cursor.execute("SELECT SCOPE_IDENTITY()")
                    row = cursor.fetchone()
                    return int(row[0]) if row and row[0] else 0
                return cursor.rowcount
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if attempt == 0 and self._is_transient(exc):
                    logger.warning("db_stale_conn_retry", method="execute", error=str(exc)[:120])
                    self._reset_conn()
                    continue
                raise
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
        return 0  # unreachable

    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        for attempt in range(2):
            conn = self._conn()
            cursor = conn.cursor()
            try:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                row = cursor.fetchone()
                if not row:
                    return None
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            except Exception as exc:
                if attempt == 0 and self._is_transient(exc):
                    logger.warning("db_stale_conn_retry", method="fetch_one", error=str(exc)[:120])
                    self._reset_conn()
                    continue
                raise
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
        return None  # unreachable

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        for attempt in range(2):
            conn = self._conn()
            cursor = conn.cursor()
            try:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as exc:
                if attempt == 0 and self._is_transient(exc):
                    logger.warning("db_stale_conn_retry", method="fetch_all", error=str(exc)[:120])
                    self._reset_conn()
                    continue
                raise
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
        return []  # unreachable

    def init_schema(self) -> None:
        conn = self._conn()
        cursor = conn.cursor()
        try:
            # Combine all IF NOT EXISTS / CREATE statements into a single
            # batch separated by semicolons — one round trip to Azure SQL
            # instead of ~35 individual executions.
            batch = ";\n".join(
                s for s in _split_sql_statements(_MSSQL_SCHEMA) if s.strip()
            )
            if batch:
                cursor.execute(batch)
            conn.commit()
            logger.info("db_schema_initialized", backend="azure_sql")
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ═══════════════════════════════════════════════════════════════════════════
# Schema definitions
# ═══════════════════════════════════════════════════════════════════════════

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT          NOT NULL,
    email       TEXT          NOT NULL UNIQUE COLLATE NOCASE,
    password    TEXT          NOT NULL,
    is_paid     INTEGER       NOT NULL DEFAULT 0,
    plan_type   TEXT          NOT NULL DEFAULT 'free',
    trial_ends_at TEXT        NULL,
    stripe_customer_id TEXT   NULL,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT          NOT NULL UNIQUE,
    user_id     INTEGER       REFERENCES users(id),
    filename    TEXT,
    file_type   TEXT,
    char_count  INTEGER       NOT NULL DEFAULT 0,
    text_content TEXT,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT          NOT NULL,
    user_id         INTEGER       REFERENCES users(id),
    plagiarism_score REAL         NOT NULL DEFAULT 0,
    confidence_score REAL         NOT NULL DEFAULT 0,
    risk_level      TEXT          NOT NULL DEFAULT 'LOW',
    sources_count   INTEGER       NOT NULL DEFAULT 0,
    flagged_count   INTEGER       NOT NULL DEFAULT 0,
    report_json     TEXT,
    created_at      TEXT          NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    ip_address  TEXT,
    tool_type   TEXT          NOT NULL,
    word_count  INTEGER       NOT NULL DEFAULT 0,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER       NOT NULL REFERENCES users(id),
    razorpay_order_id   TEXT      NOT NULL UNIQUE,
    razorpay_payment_id TEXT      NULL,
    razorpay_signature  TEXT      NULL,
    plan_name       TEXT          NOT NULL,
    amount          INTEGER       NOT NULL,
    currency        TEXT          NOT NULL DEFAULT 'INR',
    status          TEXT          NOT NULL DEFAULT 'created',
    created_at      TEXT          NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_scans_user_id ON scans(user_id);
CREATE INDEX IF NOT EXISTS idx_scans_document_id ON scans(document_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_ip ON usage_logs(ip_address);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created ON usage_logs(created_at);

CREATE TABLE IF NOT EXISTS document_fingerprints (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT          NOT NULL,
    user_id     INTEGER,
    fingerprints TEXT         NOT NULL,
    chunk_count  INTEGER      NOT NULL DEFAULT 0,
    char_count   INTEGER      NOT NULL DEFAULT 0,
    title       TEXT,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_doc_fps_user ON document_fingerprints(user_id);

CREATE TABLE IF NOT EXISTS user_api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER       NOT NULL REFERENCES users(id),
    key_prefix  TEXT          NOT NULL,
    key_hash    TEXT          NOT NULL,
    name        TEXT          NOT NULL DEFAULT 'Default',
    is_active   INTEGER       NOT NULL DEFAULT 1,
    last_used_at TEXT         NULL,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON user_api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON user_api_keys(key_hash);

CREATE TABLE IF NOT EXISTS shared_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    share_id    TEXT          NOT NULL UNIQUE,
    scan_id     INTEGER       NOT NULL REFERENCES scans(id),
    user_id     INTEGER       REFERENCES users(id),
    expires_at  TEXT          NULL,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_shared_reports_share ON shared_reports(share_id);

CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER       NOT NULL REFERENCES users(id),
    url         TEXT          NOT NULL,
    events      TEXT          NOT NULL DEFAULT 'scan.complete',
    secret      TEXT          NOT NULL,
    is_active   INTEGER       NOT NULL DEFAULT 1,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_webhooks_user ON webhook_subscriptions(user_id);

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT          NOT NULL,
    owner_id    INTEGER       NOT NULL REFERENCES users(id),
    max_seats   INTEGER       NOT NULL DEFAULT 5,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS team_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER       NOT NULL REFERENCES teams(id),
    user_id     INTEGER       NOT NULL REFERENCES users(id),
    role        TEXT          NOT NULL DEFAULT 'member',
    joined_at   TEXT          NOT NULL DEFAULT (datetime('now')),
    UNIQUE(team_id, user_id)
);

CREATE TABLE IF NOT EXISTS team_invites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER       NOT NULL REFERENCES teams(id),
    email       TEXT          NOT NULL,
    token       TEXT          NOT NULL UNIQUE,
    status      TEXT          NOT NULL DEFAULT 'pending',
    invited_by  INTEGER       NOT NULL REFERENCES users(id),
    created_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lti_platforms (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer          TEXT          NOT NULL UNIQUE,
    client_id       TEXT          NOT NULL,
    auth_endpoint   TEXT          NOT NULL,
    token_endpoint  TEXT          NULL,
    jwks_uri        TEXT          NULL,
    created_at      TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lti_states (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    state       TEXT          NOT NULL UNIQUE,
    nonce       TEXT          NOT NULL,
    issuer      TEXT          NOT NULL,
    client_id   TEXT          NOT NULL,
    created_at  TEXT          NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scans_doc_user ON scans(document_id, user_id);

CREATE TABLE IF NOT EXISTS rw_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_hash TEXT          NOT NULL UNIQUE,
    user_id      INTEGER,
    response_json TEXT         NOT NULL,
    created_at   TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rw_embeddings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER       NOT NULL,
    text_hash      TEXT          NOT NULL,
    paragraph_text TEXT          NOT NULL,
    embedding_blob BLOB          NOT NULL,
    created_at     TEXT          NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rw_emb_user ON rw_embeddings(user_id);

CREATE TABLE IF NOT EXISTS rw_versions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT          NOT NULL,
    user_id        INTEGER       NOT NULL,
    version_number INTEGER       NOT NULL DEFAULT 1,
    paragraph_text TEXT          NOT NULL,
    section_type   TEXT,
    level          TEXT,
    image_hash     TEXT,
    created_at     TEXT          NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rw_ver_session ON rw_versions(session_id);

CREATE TABLE IF NOT EXISTS rw_credits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER       NOT NULL,
    credits_remaining   INTEGER       NOT NULL DEFAULT 0,
    credits_purchased   INTEGER       NOT NULL DEFAULT 0,
    razorpay_order_id   TEXT          NULL,
    razorpay_payment_id TEXT          NULL,
    status              TEXT          NOT NULL DEFAULT 'created',
    created_at          TEXT          NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT          NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rw_credits_user ON rw_credits(user_id);
"""

_MSSQL_SCHEMA = """
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'users')
CREATE TABLE users (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    name        NVARCHAR(100)     NOT NULL,
    email       NVARCHAR(255)     NOT NULL UNIQUE,
    password    NVARCHAR(500)     NOT NULL,
    is_paid     BIT               NOT NULL DEFAULT 0,
    plan_type   NVARCHAR(20)      NOT NULL DEFAULT 'free',
    trial_ends_at DATETIME2       NULL,
    created_at  DATETIME2         NOT NULL DEFAULT GETUTCDATE(),
    updated_at  DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'documents')
CREATE TABLE documents (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    document_id NVARCHAR(64)      NOT NULL UNIQUE,
    user_id     INT               NULL REFERENCES users(id),
    filename    NVARCHAR(255)     NULL,
    file_type   NVARCHAR(10)      NULL,
    char_count  INT               NOT NULL DEFAULT 0,
    text_content NVARCHAR(MAX)    NULL,
    created_at  DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'scans')
CREATE TABLE scans (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    document_id     NVARCHAR(64)      NOT NULL,
    user_id         INT               NULL REFERENCES users(id),
    plagiarism_score FLOAT            NOT NULL DEFAULT 0,
    confidence_score FLOAT            NOT NULL DEFAULT 0,
    risk_level      NVARCHAR(10)      NOT NULL DEFAULT 'LOW',
    sources_count   INT               NOT NULL DEFAULT 0,
    flagged_count   INT               NOT NULL DEFAULT 0,
    report_json     NVARCHAR(MAX)     NULL,
    created_at      DATETIME2         NOT NULL DEFAULT GETUTCDATE(),
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'usage_logs')
CREATE TABLE usage_logs (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    user_id     INT               NULL,
    ip_address  NVARCHAR(45)      NULL,
    tool_type   NVARCHAR(30)      NOT NULL,
    word_count  INT               NOT NULL DEFAULT 0,
    created_at  DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_documents_user_id')
CREATE INDEX idx_documents_user_id ON documents(user_id);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_scans_user_id')
CREATE INDEX idx_scans_user_id ON scans(user_id);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_scans_document_id')
CREATE INDEX idx_scans_document_id ON scans(document_id);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_usage_logs_user_id')
CREATE INDEX idx_usage_logs_user_id ON usage_logs(user_id);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_usage_logs_ip')
CREATE INDEX idx_usage_logs_ip ON usage_logs(ip_address);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_usage_logs_created')
CREATE INDEX idx_usage_logs_created ON usage_logs(created_at);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'payments')
CREATE TABLE payments (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    user_id             INT               NOT NULL REFERENCES users(id),
    razorpay_order_id   NVARCHAR(100)     NOT NULL UNIQUE,
    razorpay_payment_id NVARCHAR(100)     NULL,
    razorpay_signature  NVARCHAR(255)     NULL,
    plan_name           NVARCHAR(20)      NOT NULL,
    amount              INT               NOT NULL,
    currency            NVARCHAR(10)      NOT NULL DEFAULT 'INR',
    status              NVARCHAR(20)      NOT NULL DEFAULT 'created',
    created_at          DATETIME2         NOT NULL DEFAULT GETUTCDATE(),
    updated_at          DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'plan_type')
ALTER TABLE users ADD plan_type NVARCHAR(20) NOT NULL DEFAULT 'free';
---
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'trial_ends_at')
ALTER TABLE users ADD trial_ends_at DATETIME2 NULL;
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'document_fingerprints')
CREATE TABLE document_fingerprints (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    document_id  NVARCHAR(64)      NOT NULL,
    user_id      INT               NULL,
    fingerprints NVARCHAR(MAX)     NOT NULL,
    chunk_count  INT               NOT NULL DEFAULT 0,
    char_count   INT               NOT NULL DEFAULT 0,
    title        NVARCHAR(255)     NULL,
    created_at   DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_doc_fps_user')
CREATE INDEX idx_doc_fps_user ON document_fingerprints(user_id);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'user_api_keys')
CREATE TABLE user_api_keys (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    user_id      INT               NOT NULL REFERENCES users(id),
    key_prefix   NVARCHAR(20)      NOT NULL,
    key_hash     NVARCHAR(128)     NOT NULL,
    name         NVARCHAR(100)     NOT NULL DEFAULT 'Default',
    is_active    BIT               NOT NULL DEFAULT 1,
    last_used_at DATETIME2         NULL,
    created_at   DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_api_keys_user')
CREATE INDEX idx_api_keys_user ON user_api_keys(user_id);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_api_keys_hash')
CREATE INDEX idx_api_keys_hash ON user_api_keys(key_hash);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'shared_reports')
CREATE TABLE shared_reports (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    share_id    NVARCHAR(64)      NOT NULL UNIQUE,
    scan_id     INT               NOT NULL REFERENCES scans(id),
    user_id     INT               NULL REFERENCES users(id),
    expires_at  DATETIME2         NULL,
    created_at  DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_shared_reports_share')
CREATE INDEX idx_shared_reports_share ON shared_reports(share_id);
---
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('usage_logs') AND name = 'word_count')
ALTER TABLE usage_logs ADD word_count INT NOT NULL DEFAULT 0;
---
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'stripe_customer_id')
ALTER TABLE users ADD stripe_customer_id NVARCHAR(255) NULL;
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'webhook_subscriptions')
CREATE TABLE webhook_subscriptions (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    user_id     INT               NOT NULL REFERENCES users(id),
    url         NVARCHAR(500)     NOT NULL,
    events      NVARCHAR(255)     NOT NULL DEFAULT 'scan.complete',
    secret      NVARCHAR(255)     NOT NULL,
    is_active   BIT               NOT NULL DEFAULT 1,
    created_at  DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_webhooks_user')
CREATE INDEX idx_webhooks_user ON webhook_subscriptions(user_id);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'teams')
CREATE TABLE teams (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    name        NVARCHAR(100)     NOT NULL,
    owner_id    INT               NOT NULL REFERENCES users(id),
    max_seats   INT               NOT NULL DEFAULT 5,
    created_at  DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'team_members')
CREATE TABLE team_members (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    team_id     INT               NOT NULL REFERENCES teams(id),
    user_id     INT               NOT NULL REFERENCES users(id),
    role        NVARCHAR(20)      NOT NULL DEFAULT 'member',
    joined_at   DATETIME2         NOT NULL DEFAULT GETUTCDATE(),
    UNIQUE(team_id, user_id)
);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'team_invites')
CREATE TABLE team_invites (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    team_id     INT               NOT NULL REFERENCES teams(id),
    email       NVARCHAR(255)     NOT NULL,
    token       NVARCHAR(255)     NOT NULL UNIQUE,
    status      NVARCHAR(20)      NOT NULL DEFAULT 'pending',
    invited_by  INT               NOT NULL REFERENCES users(id),
    created_at  DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'lti_platforms')
CREATE TABLE lti_platforms (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    issuer          NVARCHAR(255)     NOT NULL UNIQUE,
    client_id       NVARCHAR(255)     NOT NULL,
    auth_endpoint   NVARCHAR(500)     NOT NULL,
    token_endpoint  NVARCHAR(500)     NULL,
    jwks_uri        NVARCHAR(500)     NULL,
    created_at      DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'lti_states')
CREATE TABLE lti_states (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    state       NVARCHAR(255)     NOT NULL UNIQUE,
    nonce       NVARCHAR(255)     NOT NULL,
    issuer      NVARCHAR(255)     NOT NULL,
    client_id   NVARCHAR(255)     NOT NULL,
    created_at  DATETIME2         NOT NULL
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_scans_doc_user')
CREATE INDEX idx_scans_doc_user ON scans(document_id, user_id);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'rw_cache')
CREATE TABLE rw_cache (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    request_hash  NVARCHAR(128)     NOT NULL UNIQUE,
    user_id       INT               NULL,
    response_json NVARCHAR(MAX)     NOT NULL,
    created_at    DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'rw_embeddings')
CREATE TABLE rw_embeddings (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    user_id        INT               NOT NULL,
    text_hash      NVARCHAR(128)     NOT NULL,
    paragraph_text NVARCHAR(MAX)     NOT NULL,
    embedding_blob VARBINARY(MAX)    NOT NULL,
    created_at     DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_rw_emb_user')
CREATE INDEX idx_rw_emb_user ON rw_embeddings(user_id);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'rw_versions')
CREATE TABLE rw_versions (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    session_id     NVARCHAR(64)      NOT NULL,
    user_id        INT               NOT NULL,
    version_number INT               NOT NULL DEFAULT 1,
    paragraph_text NVARCHAR(MAX)     NOT NULL,
    section_type   NVARCHAR(20)      NULL,
    level          NVARCHAR(20)      NULL,
    image_hash     NVARCHAR(128)     NULL,
    created_at     DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_rw_ver_session')
CREATE INDEX idx_rw_ver_session ON rw_versions(session_id);
---
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'rw_credits')
CREATE TABLE rw_credits (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    user_id             INT               NOT NULL REFERENCES users(id),
    credits_remaining   INT               NOT NULL DEFAULT 0,
    credits_purchased   INT               NOT NULL DEFAULT 0,
    razorpay_order_id   NVARCHAR(100)     NULL,
    razorpay_payment_id NVARCHAR(100)     NULL,
    status              NVARCHAR(20)      NOT NULL DEFAULT 'created',
    created_at          DATETIME2         NOT NULL DEFAULT GETUTCDATE(),
    updated_at          DATETIME2         NOT NULL DEFAULT GETUTCDATE()
);
---
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_rw_credits_user')
CREATE INDEX idx_rw_credits_user ON rw_credits(user_id);
"""


def _split_sql_statements(sql: str) -> list[str]:
    """Split multi-statement SQL on ``---`` separator lines."""
    return [s.strip() for s in sql.split("---") if s.strip()]


# ═══════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════

_db_instance: Database | None = None
_db_lock = threading.Lock()


def get_db() -> Database:
    """Return the singleton Database instance.

    First call creates the instance and runs ``init_schema()``.
    Uses Azure SQL when ``PG_SQL_CONNECTION_STRING`` is set, otherwise SQLite.
    """
    global _db_instance
    if _db_instance is not None:
        return _db_instance

    with _db_lock:
        if _db_instance is not None:
            return _db_instance

        conn_str = settings.sql_connection_string
        if conn_str:
            db = AzureSQLDatabase(conn_str)
        else:
            # Use /home/data/ on Azure (writable & persistent) or project root locally
            default_dir = "/home/data" if os.path.isdir("/home/site") else str(
                Path(__file__).resolve().parent.parent.parent
            )
            data_dir = Path(os.environ.get("PG_DATA_DIR", default_dir))
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "plagiarismguard.db"
            logger.warning(
                "sql_connection_string_not_set",
                fallback="sqlite",
                path=str(db_path),
            )
            db = SQLiteDatabase(db_path)

        db.init_schema()
        # Run any outstanding migrations
        from app.services.migrations import run_migrations
        run_migrations(db)
        _db_instance = db
        return _db_instance


def reset_db(instance: Database | None = None) -> None:
    """Replace the global DB singleton (for testing)."""
    global _db_instance
    with _db_lock:
        if _db_instance is not None and _db_instance is not instance:
            _db_instance.close()
        _db_instance = instance
