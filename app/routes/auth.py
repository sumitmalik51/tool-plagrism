"""Authentication routes — signup, login, user profile, pricing, and Razorpay payments."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
import structlog

from pydantic import BaseModel, Field

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.config import settings
from app.services.auth_service import (
    AuthError,
    login,
    signup,
    get_user_by_id,
    update_user_plan,
    verify_access_token,
    create_access_token,
    verify_refresh_token,
    create_password_reset_token,
    reset_password,
    verify_email,
    is_email_verified,
    resend_verification_token,
    get_referral_info,
    get_rw_credits,
    deduct_rw_credit,
    add_rw_credits,
)
from app.services.api_key_service import (
    create_api_key,
    delete_api_key,
    list_api_keys,
    regenerate_api_key,
    revoke_api_key,
)
from app.services.email_service import send_password_reset_email, send_verification_email, send_welcome_email
from app.services.persistence import delete_scan, get_scan, get_user_scans, get_user_stats
from app.services.rate_limiter import PLAN_TO_TIER, UserTier, limiter

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Auth endpoint rate limiting (brute-force protection)
# ---------------------------------------------------------------------------

class _AuthRateLimiter:
    """In-memory sliding-window rate limiter for auth endpoints.

    Limits: 10 attempts per IP per 5-minute window.
    Thread-safe via a simple lock.
    """

    _MAX_ATTEMPTS = 10
    _WINDOW_SECONDS = 300  # 5 minutes

    def __init__(self) -> None:
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, ip: str) -> None:
        """Raise HTTPException(429) if the IP has exceeded the limit."""
        now = time.time()
        cutoff = now - self._WINDOW_SECONDS
        with self._lock:
            # Lazy cleanup every 100 checks
            if len(self._attempts) > 100:
                self._cleanup_locked(cutoff)
            timestamps = self._attempts.get(ip, [])
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._MAX_ATTEMPTS:
                raise HTTPException(
                    status_code=429,
                    detail="Too many attempts. Please try again in a few minutes.",
                )
            timestamps.append(now)
            self._attempts[ip] = timestamps

    def _cleanup_locked(self, cutoff: float) -> None:
        """Remove stale entries (must be called while holding self._lock)."""
        stale = [k for k, v in self._attempts.items() if all(t <= cutoff for t in v)]
        for k in stale:
            del self._attempts[k]

    def cleanup(self) -> None:
        """Periodic cleanup of stale entries (called lazily)."""
        now = time.time()
        cutoff = now - self._WINDOW_SECONDS
        with self._lock:
            self._cleanup_locked(cutoff)


_auth_limiter = _AuthRateLimiter()


def _client_ip(request: Request) -> str:
    """Best-effort client IP (handles X-Forwarded-For behind proxies)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Use rightmost IP (appended by trusted Azure App Service proxy)
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        return parts[-1] if parts else (request.client.host if request.client else "unknown")
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    referral_code: str | None = Field(default=None, max_length=50)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    plan_type: str = "free"


class AuthResponse(BaseModel):
    user: UserResponse
    token: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def route_signup(body: SignupRequest, request: Request):
    """Register a new account and send a verification email."""
    _auth_limiter.check(_client_ip(request))
    try:
        result = signup(name=body.name, email=body.email, password=body.password, referral_code=body.referral_code)
        # Send verification email via ACS
        v_token = result.pop("verification_token", None)
        if v_token:
            send_verification_email(body.email, v_token)
        # Send welcome onboarding email
        send_welcome_email(body.email, body.name)
        return result
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("signup_db_error", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again in a few seconds.")


@router.post("/login", response_model=AuthResponse)
async def route_login(body: LoginRequest, request: Request, bg: BackgroundTasks):
    """Authenticate with email + password and receive a JWT."""
    _auth_limiter.check(_client_ip(request))
    try:
        result = login(email=body.email, password=body.password)
        # Check if trial emails need to be sent (fire-and-forget)
        user = result.get("user", {})
        if user.get("plan_type") == "free":
            bg.add_task(_check_trial_emails, user)
        return result
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("login_db_error", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again in a few seconds.")


@router.post("/refresh")
async def route_refresh_token(body: RefreshTokenRequest):
    """Exchange a valid refresh token for a new access token."""
    payload = verify_refresh_token(body.refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")
    user_id = int(payload["sub"])
    email = payload.get("email", "")
    plan_type = payload.get("plan_type", "free")
    new_token = create_access_token(user_id, email, plan_type=plan_type)
    return {"token": new_token}


@router.post("/forgot-password")
async def route_forgot_password(body: ForgotPasswordRequest, request: Request):
    """Request a password reset token.

    Always returns 200 to avoid email enumeration.
    Sends a reset link via Azure Communication Services Email.
    """
    _auth_limiter.check(_client_ip(request))
    token = create_password_reset_token(body.email)
    if token:
        send_password_reset_email(body.email, token)
        logger.info("password_reset_requested", has_user=True)
    else:
        logger.info("password_reset_requested", has_user=False)

    return {
        "message": "If an account with this email exists, a password reset link has been sent.",
    }


@router.post("/reset-password")
async def route_reset_password(body: ResetPasswordRequest):
    """Reset password using a valid token."""
    try:
        reset_password(body.token, body.new_password)
        return {"message": "Password has been reset successfully. You can now sign in."}
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=1)


@router.post("/verify-email")
async def route_verify_email(body: VerifyEmailRequest):
    """Verify a user's email address with the provided token."""
    try:
        verify_email(body.token)
        return {"message": "Email verified successfully!"}
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/email-status")
async def route_email_status(authorization: str = Header(default="")):
    """Check if the current user's email is verified."""
    user_id = _get_user_id(authorization)
    verified = is_email_verified(user_id)
    return {"email_verified": verified}


@router.post("/resend-verification")
async def route_resend_verification(authorization: str = Header(default="")):
    """Resend the email verification token via ACS email."""
    user_id = _get_user_id(authorization)
    if is_email_verified(user_id):
        return {"message": "Email is already verified.", "email_sent": False}
    token = resend_verification_token(user_id)
    # Look up user email
    user = get_user_by_id(user_id)
    email_sent = False
    if user and token:
        email_sent = send_verification_email(user["email"], token)
    return {
        "message": "Verification email has been sent." if email_sent else "Verification link generated (email delivery unavailable).",
        "email_sent": email_sent,
    }


@router.get("/me")
async def route_me(authorization: str = Header(default="")):
    """Return the currently authenticated user's profile."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")

    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "plan_type": user.get("plan_type", "free"),
        "trial_ends_at": user.get("trial_ends_at"),
    }


# ---------------------------------------------------------------------------
# Helpers — extract user_id from Bearer token
# ---------------------------------------------------------------------------

def _get_user_id(authorization: str) -> int:
    """Extract and validate user_id from the Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return int(payload["sub"])


# ---------------------------------------------------------------------------
# Dashboard / scan history
# ---------------------------------------------------------------------------

@router.get("/scans")
async def route_user_scans(
    authorization: str = Header(default=""),
    limit: int = 50,
    offset: int = 0,
    risk_level: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search: str | None = None,
):
    """Return the authenticated user's scan history with filtering and sorting."""
    user_id = _get_user_id(authorization)
    # Clamp limit to prevent abuse
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    scans = get_user_scans(
        user_id,
        limit=limit,
        offset=offset,
        risk_level=risk_level,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
    )
    # Strip large report_json from list view
    for s in scans:
        s.pop("report_json", None)
    return {"scans": scans}


@router.get("/scans/export-csv")
async def route_export_scans_csv(authorization: str = Header(default="")):
    """Export all user scans as a CSV file download."""
    from fastapi.responses import StreamingResponse
    import csv
    import io

    user_id = _get_user_id(authorization)
    scans = get_user_scans(user_id, limit=10000, offset=0)

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(["Document ID", "Filename", "Plagiarism Score", "Confidence",
                     "Risk Level", "Sources", "Flagged Passages", "Date"])
    for s in scans:
        writer.writerow([
            s.get("document_id", ""),
            s.get("filename", ""),
            s.get("plagiarism_score", 0),
            s.get("confidence_score", 0),
            s.get("risk_level", ""),
            s.get("sources_count", 0),
            s.get("flagged_count", 0),
            s.get("created_at", ""),
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=plagiarismguard-scans.csv"},
    )


@router.get("/scans/chart-data")
async def route_scans_chart_data(authorization: str = Header(default="")):
    """Return aggregated scan data for charts (score trends, risk distribution, daily counts)."""
    user_id = _get_user_id(authorization)
    from app.services.database import get_db
    db = get_db()

    # Score trend (last 30 scans)
    _is_mssql_db = hasattr(db, "_connection_string")
    if _is_mssql_db:
        trend_rows = db.fetch_all(
            "SELECT TOP 30 plagiarism_score, confidence_score, risk_level, created_at "
            "FROM scans WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
    else:
        trend_rows = db.fetch_all(
            "SELECT plagiarism_score, confidence_score, risk_level, created_at "
            "FROM scans WHERE user_id = ? ORDER BY created_at DESC LIMIT 30",
            (user_id,),
        )
    trend_rows = list(reversed(trend_rows))

    # Risk distribution
    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for row in db.fetch_all("SELECT risk_level, COUNT(*) as cnt FROM scans WHERE user_id = ? GROUP BY risk_level", (user_id,)):
        risk_counts[row["risk_level"]] = row["cnt"]

    # Daily scan counts (last 30 days)
    if _is_mssql_db:
        daily = db.fetch_all(
            "SELECT TOP 30 CAST(created_at AS DATE) as scan_date, COUNT(*) as cnt "
            "FROM scans WHERE user_id = ? GROUP BY CAST(created_at AS DATE) "
            "ORDER BY scan_date DESC",
            (user_id,),
        )
    else:
        daily = db.fetch_all(
            "SELECT DATE(created_at) as scan_date, COUNT(*) as cnt "
            "FROM scans WHERE user_id = ? GROUP BY DATE(created_at) "
            "ORDER BY scan_date DESC LIMIT 30",
            (user_id,),
        )

    return {
        "score_trend": [{"score": r["plagiarism_score"], "confidence": r["confidence_score"],
                         "risk": r["risk_level"], "date": str(r["created_at"])} for r in trend_rows],
        "risk_distribution": risk_counts,
        "daily_counts": [{"date": str(d["scan_date"]), "count": d["cnt"]} for d in reversed(list(daily))],
    }


@router.delete("/scans/{document_id}")
async def route_delete_scan(
    document_id: str,
    authorization: str = Header(default=""),
):
    """Delete a scan owned by the authenticated user."""
    user_id = _get_user_id(authorization)
    deleted = delete_scan(document_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scan not found.")
    return {"ok": True, "message": "Scan deleted"}


@router.get("/scans/{document_id}")
async def route_scan_detail(
    document_id: str,
    authorization: str = Header(default=""),
):
    """Return the full report for a single scan (owned by the user)."""
    user_id = _get_user_id(authorization)
    scan = get_scan(document_id)
    if not scan or scan.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Scan not found.")
    return scan


@router.get("/scans/{document_id}/revisions")
async def route_scan_revisions(
    document_id: str,
    authorization: str = Header(default=""),
):
    """Return all scans for a document to show score progression."""
    from app.services.persistence import get_document_revisions
    user_id = _get_user_id(authorization)
    revisions = get_document_revisions(document_id, user_id)
    if not revisions:
        raise HTTPException(status_code=404, detail="No revisions found.")
    return {"revisions": revisions}


@router.get("/stats")
async def route_user_stats(authorization: str = Header(default="")):
    """Return aggregate stats for the authenticated user's dashboard."""
    user_id = _get_user_id(authorization)
    return get_user_stats(user_id)


@router.get("/referral")
async def route_referral_info(authorization: str = Header(default="")):
    """Return referral code, bonus scans, and referral count for the user."""
    user_id = _get_user_id(authorization)
    return get_referral_info(user_id)


# ---------------------------------------------------------------------------
# Usage / Rate-limit info
# ---------------------------------------------------------------------------

@router.get("/usage")
async def route_usage(authorization: str = Header(default="")):
    """Return the authenticated user's daily usage count and remaining quota."""
    user_id = _get_user_id(authorization)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    plan = user.get("plan_type", "free")
    tier = PLAN_TO_TIER.get(plan, UserTier.FREE)
    identifier = f"user:{user_id}"

    used = limiter.get_count(identifier)
    remaining = limiter.get_remaining(identifier, tier)

    from app.config import settings as _s
    limit = "unlimited" if tier in (UserTier.PRO, UserTier.PREMIUM) else _s.scan_limit_free

    # Word quota (monthly)
    word_quota = limiter.check_word_quota(user_id, tier)

    return {
        "plan_type": plan,
        "used_today": used,
        "remaining": remaining if remaining >= 0 else "unlimited",
        "limit": limit,
        "word_quota": {
            "used": word_quota["used"],
            "limit": word_quota["limit"] or "unlimited",
            "remaining": word_quota["remaining"] if word_quota["remaining"] >= 0 else "unlimited",
        },
    }


# ---------------------------------------------------------------------------
# Trial email sequence (fire-and-forget background task)
# ---------------------------------------------------------------------------

def _check_trial_emails(user: dict) -> None:
    """Send day-2 or day-5 trial emails if the user qualifies."""
    from datetime import datetime, timezone
    from app.services.email_service import send_trial_usage_email, send_trial_ending_email

    try:
        created_raw = user.get("created_at")
        if not created_raw:
            return
        if isinstance(created_raw, str):
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        else:
            created = created_raw
        now = datetime.now(timezone.utc)
        if created.tzinfo is None:
            from datetime import timezone as tz
            created = created.replace(tzinfo=tz.utc)
        days_since = (now - created).days

        email = user.get("email", "")
        name = user.get("name", "User")
        user_id = user.get("id")
        if not email or not user_id:
            return

        from app.services.database import get_db
        db = get_db()

        # Ensure tracking table exists
        _is_mssql = hasattr(db, "_connection_string")
        try:
            if _is_mssql:
                db.execute(
                    "IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'trial_emails') "
                    "CREATE TABLE trial_emails ("
                    "  user_id INT NOT NULL, email_type NVARCHAR(50) NOT NULL, "
                    "  sent_at DATETIME2 DEFAULT GETUTCDATE(), "
                    "  PRIMARY KEY (user_id, email_type))"
                )
            else:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS trial_emails ("
                    "  user_id INTEGER NOT NULL, email_type TEXT NOT NULL, sent_at TEXT DEFAULT CURRENT_TIMESTAMP, "
                    "  PRIMARY KEY (user_id, email_type))"
                )
        except Exception:
            pass  # Table may already exist

        def _already_sent(email_type: str) -> bool:
            row = db.fetch_one(
                "SELECT 1 FROM trial_emails WHERE user_id = ? AND email_type = ?",
                (user_id, email_type),
            )
            return row is not None

        def _mark_sent(email_type: str) -> None:
            try:
                db.execute(
                    "INSERT INTO trial_emails (user_id, email_type) VALUES (?, ?)",
                    (user_id, email_type),
                )
            except Exception:
                pass

        # Day 2+: usage summary
        if days_since >= 2 and not _already_sent("trial_usage"):
            stats = get_user_stats(user_id)
            scans_used = stats.get("total_scans", 0) if stats else 0
            if send_trial_usage_email(email, name, scans_used):
                _mark_sent("trial_usage")

        # Day 5+: trial ending nudge
        if days_since >= 5 and not _already_sent("trial_ending"):
            if send_trial_ending_email(email, name):
                _mark_sent("trial_ending")

    except Exception as exc:
        logger.error("trial_email_check_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Pricing plans
# ---------------------------------------------------------------------------

PLANS = [
    {
        "id": "free",
        "name": "Free",
        "price": 0,
        "currency": "INR",
        "period": "forever",
        "features": [
            "3 tool uses per day",
            "Plagiarism detection",
            "AI rewriter",
            "Readability analyzer",
            "Grammar checker",
            "50 MB file upload limit",
            "Watermarked DOCX export",
        ],
        "cta": "Current Plan",
    },
    {
        "id": "pro",
        "name": "Pro",
        "price": 299,
        "currency": "INR",
        "period": "month",
        "popular": True,
        "features": [
            "Unlimited tool uses",
            "Everything in Free",
            "50 MB file upload limit",
            "Batch analysis (up to 5 files)",
            "Up to 5 API keys",
            "Clean DOCX export (no watermark)",
            "Detailed source reports",
            "Scan history & analytics",
        ],
        "cta": "Upgrade to Pro",
    },
    {
        "id": "pro_annual",
        "name": "Pro",
        "price": 2999,
        "currency": "INR",
        "period": "year",
        "monthly_equivalent": 250,
        "popular": True,
        "save_percent": 16,
        "features": [
            "Unlimited tool uses",
            "Everything in Free",
            "50 MB file upload limit",
            "Batch analysis (up to 5 files)",
            "Up to 5 API keys",
            "Clean DOCX export (no watermark)",
            "Detailed source reports",
            "Scan history & analytics",
        ],
        "cta": "Upgrade to Pro",
    },
    {
        "id": "premium",
        "name": "Premium",
        "price": 599,
        "currency": "INR",
        "period": "month",
        "features": [
            "Everything in Pro",
            "100 MB file upload limit",
            "Batch analysis (up to 10 files)",
            "Up to 20 API keys",
            "Enhanced search depth (15+ queries)",
            "Priority support",
        ],
        "cta": "Upgrade to Premium",
    },
    {
        "id": "premium_annual",
        "name": "Premium",
        "price": 5999,
        "currency": "INR",
        "period": "year",
        "monthly_equivalent": 500,
        "save_percent": 16,
        "features": [
            "Everything in Pro",
            "100 MB file upload limit",
            "Batch analysis (up to 10 files)",
            "Up to 20 API keys",
            "Enhanced search depth (15+ queries)",
            "Priority support",
        ],
        "cta": "Upgrade to Premium",
    },
]

# Map plan → amount in paise (Razorpay uses smallest currency unit)
PLAN_AMOUNTS = {
    "pro": 299_00,              # ₹299/month
    "premium": 599_00,          # ₹599/month
    "pro_annual": 2999_00,      # ₹2,999/year
    "premium_annual": 5999_00,  # ₹5,999/year
}


@router.get("/plans")
async def route_plans():
    """Return the list of available subscription plans."""
    return {"plans": PLANS}


# ---------------------------------------------------------------------------
# Razorpay payment flow
# ---------------------------------------------------------------------------

def _get_razorpay_client():
    """Create and return a Razorpay client instance."""
    try:
        import razorpay
    except ImportError:
        logger.error("razorpay_import_failed", hint="pip install razorpay setuptools")
        raise HTTPException(status_code=503, detail="Payment gateway unavailable.")
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Payment gateway not configured.")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


class CreateOrderRequest(BaseModel):
    plan: str = Field(..., description="Plan to upgrade to: pro or premium")


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    plan: str


@router.post("/create-order")
async def route_create_order(
    body: CreateOrderRequest,
    authorization: str = Header(default=""),
):
    """Create a Razorpay order for the selected plan."""
    user_id = _get_user_id(authorization)

    if body.plan not in PLAN_AMOUNTS:
        raise HTTPException(status_code=400, detail="Invalid plan. Choose 'pro' or 'premium'.")

    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    amount = PLAN_AMOUNTS[body.plan]

    try:
        client = _get_razorpay_client()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("razorpay_client_init_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Payment gateway unavailable.")

    try:
        order = client.order.create({
            "amount": amount,
            "currency": "INR",
            "receipt": f"user_{user_id}_{body.plan}",
            "notes": {
                "user_id": str(user_id),
                "plan": body.plan,
                "user_email": user.get("email", ""),
            },
        })
    except Exception as exc:
        logger.error("razorpay_order_create_failed", error=str(exc), user_id=user_id)
        raise HTTPException(status_code=502, detail="Failed to create payment order.")

    # Record the order in our DB
    from app.services.database import get_db
    db = get_db()
    try:
        db.execute(
            "INSERT INTO payments (user_id, razorpay_order_id, plan_name, amount, currency, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, order["id"], body.plan, amount, "INR", "created"),
        )
    except Exception as exc:
        logger.error("payment_record_insert_failed", error=str(exc), order_id=order["id"])
        # Order was created at Razorpay — still return it so user can pay

    logger.info("razorpay_order_created", order_id=order["id"], user_id=user_id, plan=body.plan)

    return {
        "order_id": order["id"],
        "amount": amount,
        "currency": "INR",
        "plan": body.plan,
        "user_name": user.get("name", ""),
        "user_email": user.get("email", ""),
    }


@router.post("/verify-payment")
async def route_verify_payment(
    body: VerifyPaymentRequest,
    authorization: str = Header(default=""),
):
    """Verify Razorpay payment signature and upgrade the user's plan."""
    user_id = _get_user_id(authorization)

    if body.plan not in PLAN_AMOUNTS:
        raise HTTPException(status_code=400, detail="Invalid plan.")

    # Verify signature using HMAC SHA256
    message = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
    expected_signature = hmac.new(
        settings.razorpay_key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    from app.services.database import get_db
    db = get_db()

    if not hmac.compare_digest(expected_signature, body.razorpay_signature):
        logger.warning(
            "razorpay_signature_mismatch",
            order_id=body.razorpay_order_id,
            user_id=user_id,
        )
        try:
            db.execute(
                "UPDATE payments SET status = ? WHERE razorpay_order_id = ?",
                ("failed", body.razorpay_order_id),
            )
        except Exception as exc:
            logger.error("payment_status_update_failed", error=str(exc))
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")

    # Signature valid — update payment record and upgrade plan
    try:
        db.execute(
            "UPDATE payments SET razorpay_payment_id = ?, razorpay_signature = ?, "
            "status = ? WHERE razorpay_order_id = ?",
            (body.razorpay_payment_id, body.razorpay_signature, "paid", body.razorpay_order_id),
        )
    except Exception as exc:
        logger.error("payment_record_update_failed", error=str(exc), order_id=body.razorpay_order_id)

    # Upgrade the user's plan
    try:
        update_user_plan(user_id, body.plan)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("plan_upgrade_failed_after_payment", error=str(exc), user_id=user_id)
        raise HTTPException(status_code=500, detail="Payment recorded but plan upgrade failed. Contact support.")

    logger.info(
        "payment_verified_plan_upgraded",
        order_id=body.razorpay_order_id,
        payment_id=body.razorpay_payment_id,
        user_id=user_id,
        plan=body.plan,
    )

    return {
        "success": True,
        "plan_type": body.plan,
        "message": f"Payment successful! Plan upgraded to {body.plan}.",
    }


# ---------------------------------------------------------------------------
# Razorpay server-side webhook (catches payments even if client disconnects)
# ---------------------------------------------------------------------------

@router.post("/razorpay-webhook")
async def route_razorpay_webhook(request: Request):
    """Handle Razorpay webhook events (payment.captured, payment.failed).

    Razorpay sends a POST with a JSON body and signs it with the webhook
    secret (``PG_RAZORPAY_WEBHOOK_SECRET``).  We verify the signature,
    then update the payment record and upgrade/flag the user's plan.

    Configure the webhook URL in the Razorpay Dashboard →
      ``https://<your-domain>/api/v1/auth/razorpay-webhook``
    and set the same secret as ``PG_RAZORPAY_WEBHOOK_SECRET``.
    """
    # --- 1. Read raw body (needed for signature verification) ---------------
    raw_body = await request.body()

    # --- 2. Verify signature ------------------------------------------------
    webhook_secret = settings.razorpay_webhook_secret or settings.razorpay_key_secret or ""
    webhook_secret = webhook_secret.strip()
    if not webhook_secret:
        logger.error("razorpay_webhook_secret_missing")
        raise HTTPException(status_code=503, detail="Webhook not configured.")

    sig_header = request.headers.get("X-Razorpay-Signature", "")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing signature header.")

    expected_sig = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, sig_header):
        logger.warning("razorpay_webhook_signature_invalid")
        raise HTTPException(status_code=400, detail="Invalid signature.")

    # --- 3. Parse payload ---------------------------------------------------
    import json
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    event = payload.get("event", "")
    payment_entity = (payload.get("payload", {}).get("payment", {}).get("entity", {}))

    order_id = payment_entity.get("order_id", "")
    payment_id = payment_entity.get("id", "")
    notes = payment_entity.get("notes", {})
    user_id_str = notes.get("user_id", "")
    plan = notes.get("plan", "")
    addon = notes.get("addon", "")

    logger.info(
        "razorpay_webhook_received",
        webhook_event=event,
        order_id=order_id,
        payment_id=payment_id,
        user_id=user_id_str,
    )

    if not order_id:
        # Not a payment event we care about — acknowledge anyway
        return {"status": "ok"}

    from app.services.database import get_db
    db = get_db()

    # --- 4. Handle events ---------------------------------------------------
    if event == "payment.captured":
        # Handle add-on credit pack purchases
        if addon == "rw_credit_pack" and user_id_str:
            try:
                db.execute(
                    "UPDATE rw_credits SET razorpay_payment_id = ?, "
                    "credits_remaining = credits_purchased, status = 'paid', "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE razorpay_order_id = ? AND status != 'paid'",
                    (payment_id, order_id),
                )
                logger.info("webhook_addon_credits_activated", user_id=user_id_str, order_id=order_id)
            except Exception as exc:
                logger.error("webhook_addon_activate_failed", error=str(exc), order_id=order_id)
        else:
            # Regular plan upgrade — update payments table
            try:
                db.execute(
                    "UPDATE payments SET razorpay_payment_id = ?, status = ? "
                    "WHERE razorpay_order_id = ? AND status != ?",
                    (payment_id, "paid", order_id, "paid"),
                )
            except Exception as exc:
                logger.error("webhook_payment_update_failed", error=str(exc), order_id=order_id)

            # Upgrade the user's plan (only if we have the info from order notes)
            if user_id_str and plan:
                try:
                    uid = int(user_id_str)
                    update_user_plan(uid, plan)
                    logger.info("webhook_plan_upgraded", user_id=uid, plan=plan, order_id=order_id)
                except (ValueError, AuthError) as exc:
                    logger.error("webhook_plan_upgrade_failed", error=str(exc), user_id=user_id_str)

    elif event == "payment.failed":
        try:
            db.execute(
                "UPDATE payments SET razorpay_payment_id = ?, status = ? "
                "WHERE razorpay_order_id = ?",
                (payment_id, "failed", order_id),
            )
        except Exception as exc:
            logger.error("webhook_payment_fail_update_failed", error=str(exc), order_id=order_id)
        logger.warning("razorpay_payment_failed", order_id=order_id, payment_id=payment_id)

    # Always return 200 so Razorpay doesn't retry endlessly
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Research Writer Credit Pack add-on (one-time purchase)
# ---------------------------------------------------------------------------

ADDON_AMOUNTS = {
    "rw_credit_pack": settings.rw_credit_pack_amount,  # ₹149
}


@router.post("/create-addon-order")
async def route_create_addon_order(
    authorization: str = Header(default=""),
):
    """Create a Razorpay order for the Research Writer Credit Pack add-on."""
    user_id = _get_user_id(authorization)

    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    amount = ADDON_AMOUNTS["rw_credit_pack"]

    try:
        client = _get_razorpay_client()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("razorpay_client_init_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Payment gateway unavailable.")

    try:
        order = client.order.create({
            "amount": amount,
            "currency": "INR",
            "receipt": f"user_{user_id}_rw_credits",
            "notes": {
                "user_id": str(user_id),
                "addon": "rw_credit_pack",
                "credits": str(settings.rw_credit_pack_size),
                "user_email": user.get("email", ""),
            },
        })
    except Exception as exc:
        logger.error("razorpay_addon_order_failed", error=str(exc), user_id=user_id)
        raise HTTPException(status_code=502, detail="Failed to create payment order.")

    from app.services.database import get_db
    db = get_db()
    try:
        db.execute(
            "INSERT INTO rw_credits "
            "(user_id, credits_remaining, credits_purchased, razorpay_order_id, status) "
            "VALUES (?, 0, ?, ?, 'created')",
            (user_id, settings.rw_credit_pack_size, order["id"]),
        )
    except Exception as exc:
        logger.error("addon_record_insert_failed", error=str(exc), order_id=order["id"])

    logger.info("addon_order_created", order_id=order["id"], user_id=user_id, credits=settings.rw_credit_pack_size)

    return {
        "order_id": order["id"],
        "amount": amount,
        "currency": "INR",
        "razorpay_key": settings.razorpay_key_id,
        "addon": "rw_credit_pack",
        "credits": settings.rw_credit_pack_size,
        "user_name": user.get("name", ""),
        "user_email": user.get("email", ""),
    }


class VerifyAddonPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/verify-addon-payment")
async def route_verify_addon_payment(
    body: VerifyAddonPaymentRequest,
    authorization: str = Header(default=""),
):
    """Verify Razorpay payment for the Research Writer Credit Pack add-on."""
    user_id = _get_user_id(authorization)

    message = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
    expected_signature = hmac.new(
        settings.razorpay_key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    from app.services.database import get_db
    db = get_db()

    if not hmac.compare_digest(expected_signature, body.razorpay_signature):
        logger.warning("addon_signature_mismatch", order_id=body.razorpay_order_id, user_id=user_id)
        try:
            db.execute(
                "UPDATE rw_credits SET status = 'failed' WHERE razorpay_order_id = ?",
                (body.razorpay_order_id,),
            )
        except Exception as exc:
            logger.error("addon_status_update_failed", error=str(exc))
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")

    # Signature valid — activate credits
    try:
        db.execute(
            "UPDATE rw_credits SET razorpay_payment_id = ?, "
            "credits_remaining = credits_purchased, status = 'paid', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE razorpay_order_id = ? AND status != 'paid'",
            (body.razorpay_payment_id, body.razorpay_order_id),
        )
    except Exception as exc:
        logger.error("addon_credit_activate_failed", error=str(exc), order_id=body.razorpay_order_id)
        raise HTTPException(status_code=500, detail="Payment recorded but credit activation failed. Contact support.")

    total = get_rw_credits(user_id)
    logger.info(
        "addon_payment_verified",
        order_id=body.razorpay_order_id,
        user_id=user_id,
        total_credits=total,
    )

    return {
        "success": True,
        "addon": "rw_credit_pack",
        "credits_added": settings.rw_credit_pack_size,
        "total_credits": total,
        "message": f"{settings.rw_credit_pack_size} Research Writer credits added!",
    }


@router.get("/rw-credits")
async def route_get_rw_credits(
    authorization: str = Header(default=""),
):
    """Return the user's remaining Research Writer credits."""
    user_id = _get_user_id(authorization)
    total = get_rw_credits(user_id)
    return {"credits": total}


# Keep legacy endpoints for backwards compatibility

class CheckoutRequest(BaseModel):
    plan: str = Field(..., description="Plan to upgrade to: pro or premium")


@router.post("/create-checkout-session")
async def route_create_checkout(
    body: CheckoutRequest,
    authorization: str = Header(default=""),
):
    """Legacy endpoint — redirects to Razorpay create-order."""
    user_id = _get_user_id(authorization)
    if body.plan not in ("pro", "premium"):
        raise HTTPException(status_code=400, detail="Invalid plan. Choose 'pro' or 'premium'.")
    return {
        "message": "Use /api/v1/auth/create-order for Razorpay payments.",
        "plan": body.plan,
    }


if settings.debug:
    @router.get("/mock-upgrade")
    async def route_mock_upgrade(
        plan: str = "pro",
        authorization: str = Header(default=""),
    ):
        """Mock upgrade endpoint — immediately sets the user's plan (for testing only)."""
        user_id = _get_user_id(authorization)
        try:
            update_user_plan(user_id, plan)
        except AuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "plan_type": plan, "message": f"Plan upgraded to {plan}."}


class ChangePlanRequest(BaseModel):
    plan: str = Field(..., description="Target plan: free, pro, or premium")


@router.post("/change-plan")
async def route_change_plan(
    body: ChangePlanRequest,
    authorization: str = Header(default=""),
):
    """Switch the user to a different plan (upgrade or downgrade).

    For downgrades, the change takes effect immediately.
    For upgrades to a paid plan, use /create-order instead.
    """
    user_id = _get_user_id(authorization)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    current = user.get("plan_type", "free")
    target = body.plan

    PLAN_RANK = {"free": 0, "pro": 1, "premium": 2}
    if target not in PLAN_RANK:
        raise HTTPException(status_code=400, detail="Invalid plan. Choose 'free', 'pro', or 'premium'.")

    if target == current:
        raise HTTPException(status_code=400, detail="You are already on this plan.")

    # Upgrades to paid plans require payment — redirect to payment flow
    if PLAN_RANK.get(target, 0) > PLAN_RANK.get(current, 0) and target != "free":
        raise HTTPException(
            status_code=400,
            detail="To upgrade to a paid plan, use the payment flow via /api/v1/auth/create-order.",
        )

    try:
        update_user_plan(user_id, target)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info("user_plan_changed", user_id=user_id, from_plan=current, to_plan=target)
    return {
        "success": True,
        "plan_type": target,
        "previous_plan": current,
        "message": f"Plan changed from {current} to {target}.",
    }


# ---------------------------------------------------------------------------
# API Key Management (Pro/Premium only)
# ---------------------------------------------------------------------------

class CreateApiKeyRequest(BaseModel):
    name: str = Field(default="Default", max_length=100, description="Friendly name for the key")


@router.post("/api-keys")
async def route_create_api_key(
    body: CreateApiKeyRequest,
    authorization: str = Header(default=""),
):
    """Generate a new API key. Pro/Premium plans only. Max keys depend on plan."""
    user_id = _get_user_id(authorization)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    plan = user.get("plan_type", "free")
    if plan == "free":
        raise HTTPException(status_code=403, detail="API keys require a Pro or Premium plan. Upgrade to get started.")

    try:
        result = create_api_key(user_id, body.name, plan_type=plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "id": result["id"],
        "key": result["key"],
        "prefix": result["prefix"],
        "name": result["name"],
        "message": "Store this key securely — it won't be shown again.",
    }


@router.get("/api-keys")
async def route_list_api_keys(
    authorization: str = Header(default=""),
):
    """List all API keys for the authenticated user."""
    user_id = _get_user_id(authorization)
    keys = list_api_keys(user_id)
    return {"keys": keys}


@router.post("/api-keys/revoke")
async def route_revoke_api_key(
    body: dict,
    authorization: str = Header(default=""),
):
    """Revoke an API key by its ID."""
    user_id = _get_user_id(authorization)
    key_id = body.get("key_id")
    if not key_id:
        raise HTTPException(status_code=400, detail="key_id is required.")

    revoked = revoke_api_key(user_id, int(key_id))
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found or already revoked.")

    return {"success": True, "message": "API key revoked."}


@router.post("/api-keys/regenerate")
async def route_regenerate_api_key(
    body: dict,
    authorization: str = Header(default=""),
):
    """Regenerate an API key — issues a new secret while keeping the same name/ID."""
    user_id = _get_user_id(authorization)
    key_id = body.get("key_id")
    if not key_id:
        raise HTTPException(status_code=400, detail="key_id is required.")

    result = regenerate_api_key(user_id, int(key_id))
    if not result:
        raise HTTPException(status_code=404, detail="API key not found or inactive.")

    return {
        "id": result["id"],
        "key": result["key"],
        "prefix": result["prefix"],
        "name": result["name"],
        "message": "Key regenerated. Store the new key securely — it won't be shown again.",
    }


@router.delete("/api-keys/{key_id}")
async def route_delete_api_key(
    key_id: int,
    authorization: str = Header(default=""),
):
    """Permanently delete an API key."""
    user_id = _get_user_id(authorization)

    deleted = delete_api_key(user_id, key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="API key not found.")

    return {"success": True, "message": "API key permanently deleted."}
