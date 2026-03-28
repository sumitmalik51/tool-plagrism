"""Institutional document repository — stores and compares document fingerprints.

Enables detection of overlap between submissions within the same institution
or user account. When a document is scanned, its fingerprints are stored.
Future scans compare against all stored fingerprints to detect self-plagiarism
or student-to-student copying.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.database import get_db
from app.tools.fingerprint_tool import generate_fingerprints, compare_fingerprints
from app.utils.logger import get_logger

logger = get_logger(__name__)


def store_document_fingerprints(
    document_id: str,
    text: str,
    *,
    user_id: int | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Generate and store fingerprints for a document.

    Args:
        document_id: Unique document identifier.
        text: Full document text.
        user_id: Optional user who submitted the document.
        title: Optional document title/filename.

    Returns:
        Dict with ``fingerprint_count`` and ``stored`` status.
    """
    fp_result = generate_fingerprints(text)
    fp_set = fp_result["fingerprints"]

    if not fp_set:
        return {"fingerprint_count": 0, "stored": False}

    # Serialize fingerprints as JSON array of ints
    fp_json = json.dumps(sorted(fp_set))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO document_fingerprints "
            "(document_id, user_id, fingerprints, chunk_count, char_count, title) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (document_id, user_id, fp_json, fp_result["count"], fp_result["normalized_length"], title),
        )
        logger.info(
            "document_fingerprints_stored",
            document_id=document_id,
            fingerprint_count=fp_result["count"],
        )
        return {"fingerprint_count": fp_result["count"], "stored": True}
    except Exception as exc:
        logger.warning("fingerprint_store_failed", document_id=document_id, error=str(exc))
        return {"fingerprint_count": fp_result["count"], "stored": False}


def find_similar_documents(
    text: str,
    *,
    user_id: int | None = None,
    exclude_document_id: str | None = None,
    threshold: float = 0.03,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Compare a document against all stored fingerprints.

    Args:
        text: Full document text to check.
        user_id: If provided, only compare against this user's documents.
        exclude_document_id: Skip this document (to avoid self-match).
        threshold: Minimum Jaccard similarity to report.
        limit: Maximum number of matches to return.

    Returns:
        List of matching documents with similarity scores, sorted by score desc.
    """
    doc_fp = generate_fingerprints(text)
    doc_set = doc_fp["fingerprints"]

    if not doc_set:
        return []

    db = get_db()

    # Fetch stored fingerprints
    if user_id is not None:
        rows = db.fetch_all(
            "SELECT document_id, fingerprints, title, char_count, created_at "
            "FROM document_fingerprints WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
    else:
        rows = db.fetch_all(
            "SELECT document_id, fingerprints, title, char_count, created_at "
            "FROM document_fingerprints ORDER BY created_at DESC",
            (),
        )

    matches: list[dict[str, Any]] = []

    for row in rows:
        if exclude_document_id and row["document_id"] == exclude_document_id:
            continue

        try:
            stored_fps = set(json.loads(row["fingerprints"]))
        except (json.JSONDecodeError, TypeError):
            continue

        comparison = compare_fingerprints(doc_set, stored_fps)
        if comparison["jaccard"] >= threshold:
            matches.append({
                "document_id": row["document_id"],
                "title": row.get("title") or row["document_id"],
                "jaccard": comparison["jaccard"],
                "overlap_count": comparison["overlap_count"],
                "char_count": row.get("char_count", 0),
                "created_at": row.get("created_at", ""),
            })

    # Sort by similarity descending
    matches.sort(key=lambda m: m["jaccard"], reverse=True)
    matches = matches[:limit]

    logger.info(
        "repository_comparison_complete",
        doc_fingerprints=len(doc_set),
        stored_documents_checked=len(rows),
        matches_found=len(matches),
    )

    return matches
