"""Authentication routes — signup, login, user profile, pricing, and dashboard data."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Header, HTTPException

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
        "price": 9,
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
        "price": 19,
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


@router.get("/plans")
async def route_plans():
    """Return the list of available subscription plans."""
    return {"plans": PLANS}


# ---------------------------------------------------------------------------
# Checkout / plan upgrade (Stripe placeholder)
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str = Field(..., description="Plan to upgrade to: pro or premium")


@router.post("/create-checkout-session")
async def route_create_checkout(
    body: CheckoutRequest,
    authorization: str = Header(default=""),
):
    """Create a Stripe checkout session (placeholder — returns mock URL)."""
    user_id = _get_user_id(authorization)

    if body.plan not in ("pro", "premium"):
        raise HTTPException(status_code=400, detail="Invalid plan. Choose 'pro' or 'premium'.")

    # In production, create a real Stripe session here.
    # For now, return a mock URL.
    return {
        "checkout_url": f"/api/v1/auth/mock-upgrade?plan={body.plan}",
        "plan": body.plan,
        "message": "Stripe integration pending. Use the mock upgrade endpoint for testing.",
    }


@router.get("/mock-upgrade")
async def route_mock_upgrade(
    plan: str = "pro",
    authorization: str = Header(default=""),
):
    """Mock upgrade endpoint — immediately sets the user's plan (for testing)."""
    user_id = _get_user_id(authorization)

    try:
        update_user_plan(user_id, plan)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"success": True, "plan_type": plan, "message": f"Plan upgraded to {plan}."}
