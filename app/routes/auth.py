"""Authentication routes — signup, login, user profile, pricing, and Razorpay payments."""

from __future__ import annotations

import hashlib
import hmac
import structlog

from pydantic import BaseModel, Field

from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.services.auth_service import (
    AuthError,
    login,
    signup,
    get_user_by_id,
    update_user_plan,
    verify_access_token,
    create_password_reset_token,
    reset_password,
    verify_email,
    is_email_verified,
    resend_verification_token,
)
from app.services.email_service import send_password_reset_email, send_verification_email
from app.services.persistence import get_scan, get_user_scans, get_user_stats
from app.services.rate_limiter import PLAN_TO_TIER, UserTier, limiter

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


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
async def route_signup(body: SignupRequest):
    """Register a new account and send a verification email."""
    try:
        result = signup(name=body.name, email=body.email, password=body.password)
        # Send verification email via ACS
        v_token = result.pop("verification_token", None)
        if v_token:
            send_verification_email(body.email, v_token)
        return result
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login", response_model=AuthResponse)
async def route_login(body: LoginRequest):
    """Authenticate with email + password and receive a JWT."""
    try:
        result = login(email=body.email, password=body.password)
        return result
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.post("/forgot-password")
async def route_forgot_password(body: ForgotPasswordRequest):
    """Request a password reset token.

    Always returns 200 to avoid email enumeration.
    Sends a reset link via Azure Communication Services Email.
    """
    token = create_password_reset_token(body.email)
    email_sent = False
    if token:
        email_sent = send_password_reset_email(body.email, token)
        logger.info("password_reset_requested", email=body.email, has_user=True, email_sent=email_sent)
    else:
        logger.info("password_reset_requested", email=body.email, has_user=False)

    return {
        "message": "If an account with this email exists, a password reset link has been sent.",
        "email_sent": email_sent,
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
    risk_level: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search: str | None = None,
):
    """Return the authenticated user's scan history with filtering and sorting."""
    user_id = _get_user_id(authorization)
    scans = get_user_scans(
        user_id,
        limit=limit,
        risk_level=risk_level,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
    )
    # Strip large report_json from list view
    for s in scans:
        s.pop("report_json", None)
    return {"scans": scans}


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


@router.get("/stats")
async def route_user_stats(authorization: str = Header(default="")):
    """Return aggregate stats for the authenticated user's dashboard."""
    user_id = _get_user_id(authorization)
    return get_user_stats(user_id)


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

    return {
        "plan_type": plan,
        "used_today": used,
        "remaining": remaining if remaining >= 0 else "unlimited",
        "limit": limit,
    }


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
            "Priority processing",
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
            "API access",
            "Batch file analysis",
            "Custom integrations",
            "Priority support",
        ],
        "cta": "Upgrade to Premium",
    },
]

# Map plan → amount in paise (Razorpay uses smallest currency unit)
PLAN_AMOUNTS = {
    "pro": 299_00,       # ₹299
    "premium": 599_00,   # ₹599
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
        "key_id": settings.razorpay_key_id,
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
