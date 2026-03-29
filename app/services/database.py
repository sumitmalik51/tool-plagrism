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
        return cursor.lastrowid or cursor.rowcount  # type: ignore[return-value]

    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        row = self._conn().execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        rows = self._conn().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def init_schema(self) -> None:
        conn = self._conn()
        conn.executescript(_SQLITE_SCHEMA)
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
                cursor.execute(sql, params)
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
                cursor.execute(sql, params)
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
                cursor.execute(sql, params)
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
            for statement in _split_sql_statements(_MSSQL_SCHEMA):
                if statement.strip():
                    cursor.execute(statement)
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
