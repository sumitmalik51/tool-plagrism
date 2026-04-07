"""Persistence service — save and retrieve documents and scan results.

Stores document metadata, text content, and full plagiarism scan reports
in the database (Azure SQL in production, SQLite in local dev).
"""

from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.services.database import get_db, SQLiteDatabase
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Document persistence
# ═══════════════════════════════════════════════════════════════════════════

def save_document(
    document_id: str,
    *,
    user_id: int | None = None,
    filename: str | None = None,
    file_type: str | None = None,
    char_count: int = 0,
    text_content: str | None = None,
) -> int:
    """Insert a document record.  Returns the auto-generated row ID."""
    db = get_db()
    row_id = db.execute(
        "INSERT INTO documents (document_id, user_id, filename, file_type, char_count, text_content) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (document_id, user_id, filename, file_type, char_count, text_content),
    )
    logger.info(
        "document_saved",
        document_id=document_id,
        user_id=user_id,
        filename=filename,
    )
    return row_id


def get_document(document_id: str) -> dict[str, Any] | None:
    """Retrieve a document record by its document_id."""
    db = get_db()
    return db.fetch_one(
        "SELECT id, document_id, user_id, filename, file_type, char_count, created_at "
        "FROM documents WHERE document_id = ?",
        (document_id,),
    )


def get_user_documents(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """List documents for a specific user, most recent first."""
    db = get_db()
    return db.fetch_all(
        "SELECT id, document_id, filename, file_type, char_count, created_at "
        "FROM documents WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )[:limit]


# ═══════════════════════════════════════════════════════════════════════════
# Scan / report persistence
# ═══════════════════════════════════════════════════════════════════════════

def save_scan(
    document_id: str,
    *,
    user_id: int | None = None,
    plagiarism_score: float = 0.0,
    confidence_score: float = 0.0,
    risk_level: str = "LOW",
    sources_count: int = 0,
    flagged_count: int = 0,
    report_json: str | None = None,
) -> int:
    """Insert a scan result.  Returns the auto-generated row ID."""
    db = get_db()
    row_id = db.execute(
        "INSERT INTO scans "
        "(document_id, user_id, plagiarism_score, confidence_score, risk_level, "
        "sources_count, flagged_count, report_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            document_id,
            user_id,
            plagiarism_score,
            confidence_score,
            risk_level,
            sources_count,
            flagged_count,
            report_json,
        ),
    )
    logger.info(
        "scan_saved",
        document_id=document_id,
        plagiarism_score=plagiarism_score,
        risk_level=risk_level,
    )
    return row_id


def get_scan(document_id: str) -> dict[str, Any] | None:
    """Retrieve the latest scan for a document."""
    db = get_db()
    return db.fetch_one(
        "SELECT id, document_id, user_id, plagiarism_score, confidence_score, "
        "risk_level, sources_count, flagged_count, report_json, created_at "
        "FROM scans WHERE document_id = ? ORDER BY created_at DESC",
        (document_id,),
    )


def get_document_revisions(document_id: str, user_id: int) -> list[dict[str, Any]]:
    """Return all scans for a document owned by the user, oldest first."""
    db = get_db()
    return db.fetch_all(
        "SELECT id, document_id, plagiarism_score, confidence_score, "
        "risk_level, sources_count, flagged_count, created_at "
        "FROM scans WHERE document_id = ? AND user_id = ? ORDER BY created_at ASC",
        (document_id, user_id),
    )


def get_user_scans(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    risk_level: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search: str | None = None,
) -> list[dict[str, Any]]:
    """List scans for a specific user with optional filtering and sorting."""
    db = get_db()

    # Validate sort parameters
    allowed_sort_cols = {"created_at", "plagiarism_score", "risk_level", "sources_count"}
    if sort_by not in allowed_sort_cols:
        sort_by = "created_at"
    if sort_order.lower() not in ("asc", "desc"):
        sort_order = "desc"

    # Build dynamic query
    conditions = ["s.user_id = ?"]
    params: list = [user_id]

    if risk_level and risk_level.upper() in ("LOW", "MEDIUM", "HIGH"):
        conditions.append("s.risk_level = ?")
        params.append(risk_level.upper())

    if search and search.strip():
        conditions.append("(d.filename LIKE ? OR s.document_id LIKE ?)")
        search_pat = f"%{search.strip()}%"
        params.extend([search_pat, search_pat])

    where_clause = " AND ".join(conditions)

    query = (
        f"SELECT s.id, s.document_id, s.plagiarism_score, s.confidence_score, "
        f"s.risk_level, s.sources_count, s.flagged_count, s.created_at, "
        f"d.filename, d.file_type "
        f"FROM scans s LEFT JOIN documents d ON s.document_id = d.document_id "
        f"WHERE {where_clause} ORDER BY s.{sort_by} {sort_order}"
    )

    # Apply OFFSET/LIMIT via SQL for proper pagination
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    if isinstance(db, SQLiteDatabase):
        # SQLite syntax
        query += f" LIMIT {limit} OFFSET {offset}"
    else:
        # MSSQL syntax
        query += f" OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"

    return db.fetch_all(query, tuple(params))


def delete_scan(document_id: str, user_id: int) -> bool:
    """Delete a scan and its associated document if owned by the user.

    Returns True if the scan was deleted, False if not found / not owned.
    """
    db = get_db()
    scan = db.fetch_one(
        "SELECT id FROM scans WHERE document_id = ? AND user_id = ?",
        (document_id, user_id),
    )
    if not scan:
        return False
    db.execute("DELETE FROM scans WHERE document_id = ? AND user_id = ?", (document_id, user_id))
    db.execute("DELETE FROM documents WHERE document_id = ? AND user_id = ?", (document_id, user_id))
    logger.info("scan_deleted", document_id=document_id, user_id=user_id)
    return True


def get_user_stats(user_id: int) -> dict[str, Any]:
    """Aggregate statistics for a user's dashboard."""
    db = get_db()

    # Single combined query instead of 4 separate round trips
    summary = db.fetch_one(
        "SELECT "
        "(SELECT COUNT(*) FROM scans WHERE user_id = ?) AS total_scans, "
        "(SELECT COUNT(*) FROM documents WHERE user_id = ?) AS total_docs, "
        "(SELECT AVG(plagiarism_score) FROM scans WHERE user_id = ?) AS avg_score",
        (user_id, user_id, user_id),
    )
    total_scans = summary["total_scans"] if summary else 0
    total_docs = summary["total_docs"] if summary else 0
    avg_score = round(summary["avg_score"] or 0, 1) if summary and summary["avg_score"] else 0

    risk_rows = db.fetch_all(
        "SELECT risk_level, COUNT(*) AS cnt FROM scans WHERE user_id = ? GROUP BY risk_level",
        (user_id,),
    )
    risk_breakdown = {r["risk_level"]: r["cnt"] for r in risk_rows}

    return {
        "total_scans": total_scans,
        "total_documents": total_docs,
        "average_score": avg_score,
        "risk_breakdown": risk_breakdown,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Research Writer — cache, embeddings, versions
# ═══════════════════════════════════════════════════════════════════════════

def rw_cache_get(request_hash: str, max_age_hours: int = 24) -> dict[str, Any] | None:
    """Return cached research-writer response if it exists and is fresh."""
    db = get_db()
    row = db.fetch_one(
        "SELECT response_json, created_at FROM rw_cache WHERE request_hash = ?",
        (request_hash,),
    )
    if not row:
        return None
    # Check freshness
    from datetime import datetime, timedelta, timezone
    try:
        created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created > timedelta(hours=max_age_hours):
            return None
    except Exception:
        pass  # If timestamp parsing fails, return the cached data anyway
    return json.loads(row["response_json"])


def rw_cache_set(request_hash: str, user_id: int, response_json: str) -> None:
    """Store a research-writer response in the cache."""
    db = get_db()
    # Upsert: delete old + insert
    db.execute("DELETE FROM rw_cache WHERE request_hash = ?", (request_hash,))
    db.execute(
        "INSERT INTO rw_cache (request_hash, user_id, response_json) VALUES (?, ?, ?)",
        (request_hash, user_id, response_json),
    )


def rw_store_embedding(user_id: int, text_hash: str, paragraph_text: str, embedding_blob: bytes) -> None:
    """Store a paragraph embedding for internal similarity comparison."""
    db = get_db()
    db.execute(
        "INSERT INTO rw_embeddings (user_id, text_hash, paragraph_text, embedding_blob) VALUES (?, ?, ?, ?)",
        (user_id, text_hash, paragraph_text, embedding_blob),
    )


def rw_get_user_embeddings(user_id: int, limit: int = 200) -> list[dict[str, Any]]:
    """Return stored embeddings for a user (for internal similarity check)."""
    db = get_db()
    rows = db.fetch_all(
        "SELECT text_hash, paragraph_text, embedding_blob FROM rw_embeddings "
        "WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )
    return rows[:limit]


def rw_store_version(
    session_id: str,
    user_id: int,
    version_number: int,
    paragraph_text: str,
    section_type: str,
    level: str,
    image_hash: str,
) -> None:
    """Store a version of a generated paragraph."""
    db = get_db()
    db.execute(
        "INSERT INTO rw_versions "
        "(session_id, user_id, version_number, paragraph_text, section_type, level, image_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, user_id, version_number, paragraph_text, section_type, level, image_hash),
    )


def rw_get_versions(session_id: str, user_id: int) -> list[dict[str, Any]]:
    """Return all versions for a session, ordered by version number."""
    db = get_db()
    return db.fetch_all(
        "SELECT id, session_id, version_number, paragraph_text, section_type, level, created_at "
        "FROM rw_versions WHERE session_id = ? AND user_id = ? ORDER BY version_number ASC",
        (session_id, user_id),
    )


def rw_get_next_version_number(session_id: str, user_id: int) -> int:
    """Return the next version number for a session."""
    db = get_db()
    row = db.fetch_one(
        "SELECT MAX(version_number) AS max_ver FROM rw_versions WHERE session_id = ? AND user_id = ?",
        (session_id, user_id),
    )
    return (row["max_ver"] or 0) + 1 if row else 1
