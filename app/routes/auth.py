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
)
from app.services.persistence import get_user_scans, get_user_stats
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
    """Register a new account — no email verification required."""
    try:
        result = signup(name=body.name, email=body.email, password=body.password)
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
):
    """Return the authenticated user's scan history."""
    user_id = _get_user_id(authorization)
    scans = get_user_scans(user_id, limit=limit)
    # Strip large report_json from list view
    for s in scans:
        s.pop("report_json", None)
    return {"scans": scans}


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
        "price": 499,
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
        "price": 999,
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
    "pro": 499_00,       # ₹499
    "premium": 999_00,   # ₹999
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
    import razorpay
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
    client = _get_razorpay_client()

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
    db.execute(
        "INSERT INTO payments (user_id, razorpay_order_id, plan_name, amount, currency, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, order["id"], body.plan, amount, "INR", "created"),
    )

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

    if not hmac.compare_digest(expected_signature, body.razorpay_signature):
        logger.warning(
            "razorpay_signature_mismatch",
            order_id=body.razorpay_order_id,
            user_id=user_id,
        )
        # Update payment status to failed
        from app.services.database import get_db
        db = get_db()
        db.execute(
            "UPDATE payments SET status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE razorpay_order_id = ?",
            ("failed", body.razorpay_order_id),
        )
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")

    # Signature valid — update payment record and upgrade plan
    from app.services.database import get_db
    db = get_db()
    db.execute(
        "UPDATE payments SET razorpay_payment_id = ?, razorpay_signature = ?, "
        "status = ?, updated_at = CURRENT_TIMESTAMP WHERE razorpay_order_id = ?",
        (body.razorpay_payment_id, body.razorpay_signature, "paid", body.razorpay_order_id),
    )

    # Upgrade the user's plan
    try:
        update_user_plan(user_id, body.plan)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

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
