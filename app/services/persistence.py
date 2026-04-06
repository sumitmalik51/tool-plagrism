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


def get_user_stats(user_id: int) -> dict[str, Any]:
    """Aggregate statistics for a user's dashboard."""
    db = get_db()

    total_row = db.fetch_one(
        "SELECT COUNT(*) AS total_scans FROM scans WHERE user_id = ?",
        (user_id,),
    )
    total_scans = total_row["total_scans"] if total_row else 0

    doc_row = db.fetch_one(
        "SELECT COUNT(*) AS total_docs FROM documents WHERE user_id = ?",
        (user_id,),
    )
    total_docs = doc_row["total_docs"] if doc_row else 0

    avg_row = db.fetch_one(
        "SELECT AVG(plagiarism_score) AS avg_score FROM scans WHERE user_id = ?",
        (user_id,),
    )
    avg_score = round(avg_row["avg_score"] or 0, 1) if avg_row else 0

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
