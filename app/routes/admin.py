"""Admin routes — dashboard stats and user management (restricted to admin emails)."""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field
from fastapi import APIRouter, Header, HTTPException, Query

from app.config import settings
from app.services.auth_service import get_user_by_id, update_user_plan, verify_access_token
from app.services.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_emails() -> set[str]:
    """Return the set of admin email addresses (case-insensitive)."""
    return {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}


def _require_admin(authorization: str) -> int:
    """Validate Authorization header and ensure the user is an admin.

    Returns the admin's user_id on success.
    Raises HTTPException(401/403) on failure.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")

    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user_id = int(payload["sub"])
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user["email"].lower() not in _admin_emails():
        raise HTTPException(status_code=403, detail="Admin access required.")

    return user_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats")
async def admin_stats(authorization: str = Header(default="")):
    """Return high-level stats for the admin dashboard."""
    _require_admin(authorization)
    db = get_db()

    # Total users
    row = db.fetch_one("SELECT COUNT(*) AS cnt FROM users")
    total_users = row["cnt"] if row else 0

    # Users by plan
    plan_rows = db.fetch_all(
        "SELECT plan_type, COUNT(*) AS cnt FROM users GROUP BY plan_type"
    )
    plans = {r["plan_type"]: r["cnt"] for r in plan_rows}

    # Total scans
    scan_row = db.fetch_one("SELECT COUNT(*) AS cnt FROM scans")
    total_scans = scan_row["cnt"] if scan_row else 0

    # Total payments (successful)
    pay_row = db.fetch_one("SELECT COUNT(*) AS cnt FROM payments WHERE status = 'paid'")
    total_payments = pay_row["cnt"] if pay_row else 0

    # Revenue
    rev_row = db.fetch_one("SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE status = 'paid'")
    total_revenue_paise = rev_row["total"] if rev_row else 0

    # Signups over last 7 days (works for both SQLite and MSSQL)
    try:
        recent_rows = db.fetch_all(
            "SELECT CAST(created_at AS DATE) AS day, COUNT(*) AS cnt "
            "FROM users GROUP BY CAST(created_at AS DATE) "
            "ORDER BY day DESC"
        )
    except Exception as exc:
        logger.warning("admin_stats_signups_query_failed", error=str(exc))
        recent_rows = []

    return {
        "total_users": total_users,
        "plans": plans,
        "total_scans": total_scans,
        "total_payments": total_payments,
        "total_revenue_inr": total_revenue_paise / 100,
        "signups_by_day": recent_rows[:30],
    }


@router.get("/analytics")
async def admin_analytics(authorization: str = Header(default="")):
    """Return detailed analytics for the admin dashboard."""
    _require_admin(authorization)
    db = get_db()

    # Scans per day (last 14 days)
    try:
        scans_by_day = db.fetch_all(
            "SELECT CAST(created_at AS DATE) AS day, COUNT(*) AS cnt "
            "FROM scans GROUP BY CAST(created_at AS DATE) "
            "ORDER BY day DESC"
        )
    except Exception as exc:
        logger.warning("admin_analytics_scans_query_failed", error=str(exc))
        scans_by_day = []

    # Tool usage breakdown (from usage_logs)
    try:
        tool_usage = db.fetch_all(
            "SELECT tool_type, COUNT(*) AS cnt "
            "FROM usage_logs GROUP BY tool_type "
            "ORDER BY cnt DESC"
        )
    except Exception as exc:
        logger.warning("admin_analytics_tool_usage_query_failed", error=str(exc))
        tool_usage = []

    # Average plagiarism score
    try:
        avg_row = db.fetch_one(
            "SELECT AVG(plagiarism_score) AS avg_score FROM scans"
        )
        avg_score = round(avg_row["avg_score"] or 0, 1)
    except Exception as exc:
        logger.warning("admin_analytics_avg_score_query_failed", error=str(exc))
        avg_score = 0

    # Risk level distribution
    try:
        risk_rows = db.fetch_all(
            "SELECT risk_level, COUNT(*) AS cnt FROM scans GROUP BY risk_level"
        )
        risk_dist = {r["risk_level"]: r["cnt"] for r in risk_rows}
    except Exception as exc:
        logger.warning("admin_analytics_risk_dist_query_failed", error=str(exc))
        risk_dist = {}

    # Top active users (by scan count)
    try:
        top_users = db.fetch_all(
            "SELECT u.name, u.email, COUNT(s.id) AS scan_count "
            "FROM users u JOIN scans s ON s.user_id = u.id "
            "GROUP BY u.id, u.name, u.email "
            "ORDER BY scan_count DESC"
        )[:10]
    except Exception as exc:
        logger.warning("admin_analytics_top_users_query_failed", error=str(exc))
        top_users = []

    return {
        "scans_by_day": scans_by_day[:14],
        "tool_usage": tool_usage,
        "avg_plagiarism_score": avg_score,
        "risk_distribution": risk_dist,
        "top_users": top_users,
    }


@router.get("/users")
async def admin_users(
    authorization: str = Header(default=""),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    plan_filter: str = Query(default="all", max_length=20),
    search: str = Query(default="", max_length=100),
):
    """Return paginated list of all users with their plan and activity."""
    _require_admin(authorization)
    db = get_db()

    # Build WHERE clause
    conditions: list[str] = []
    params: list = []

    if plan_filter and plan_filter != "all":
        conditions.append("u.plan_type = ?")
        params.append(plan_filter)

    if search:
        conditions.append("(u.name LIKE ? OR u.email LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count total matching
    count_row = db.fetch_one(f"SELECT COUNT(*) AS cnt FROM users u {where}", tuple(params))
    total = count_row["cnt"] if count_row else 0

    # Fetch page
    offset = (page - 1) * per_page
    query = (
        f"SELECT u.id, u.name, u.email, u.plan_type, u.is_paid, u.created_at, "
        f"(SELECT COUNT(*) FROM scans s WHERE s.user_id = u.id) AS scan_count, "
        f"(SELECT COUNT(*) FROM usage_logs ul WHERE ul.user_id = u.id) AS usage_count "
        f"FROM users u {where} "
        f"ORDER BY u.id DESC "
        f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
    )
    params.extend([offset, per_page])

    try:
        users = db.fetch_all(query, tuple(params))
    except Exception as exc:
        # SQLite doesn't support OFFSET...FETCH — fall back to LIMIT/OFFSET
        logger.debug("admin_users_mssql_syntax_fallback", error=str(exc))
        query_lite = (
            f"SELECT u.id, u.name, u.email, u.plan_type, u.is_paid, u.created_at, "
            f"(SELECT COUNT(*) FROM scans s WHERE s.user_id = u.id) AS scan_count, "
            f"(SELECT COUNT(*) FROM usage_logs ul WHERE ul.user_id = u.id) AS usage_count "
            f"FROM users u {where} "
            f"ORDER BY u.id DESC "
            f"LIMIT ? OFFSET ?"
        )
        # Replace the last two params (offset, per_page) with (per_page, offset) for LIMIT syntax
        params_lite = params[:-2] + [per_page, offset]
        users = db.fetch_all(query_lite, tuple(params_lite))

    return {
        "users": users,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if per_page else 1,
    }


# ---------------------------------------------------------------------------
# Admin plan override
# ---------------------------------------------------------------------------

class UpdatePlanRequest(BaseModel):
    user_id: int = Field(..., description="ID of the user to update")
    plan_type: str = Field(..., description="New plan: free, pro, or premium")


@router.post("/update-plan")
async def admin_update_plan(
    body: UpdatePlanRequest,
    authorization: str = Header(default=""),
):
    """Update a user's plan without payment (admin override)."""
    admin_id = _require_admin(authorization)

    target = get_user_by_id(body.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    old_plan = target.get("plan_type", "free")
    try:
        update_user_plan(body.user_id, body.plan_type)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "admin_plan_override",
        admin_id=admin_id,
        target_user_id=body.user_id,
        old_plan=old_plan,
        new_plan=body.plan_type,
    )

    return {
        "success": True,
        "user_id": body.user_id,
        "old_plan": old_plan,
        "new_plan": body.plan_type,
        "message": f"Plan updated from {old_plan} to {body.plan_type} for user {target['email']}.",
    }
