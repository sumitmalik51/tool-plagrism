"""Authentication routes — signup, login, user profile, and dashboard data."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Header, HTTPException

from app.services.auth_service import (
    AuthError,
    login,
    signup,
    get_user_by_id,
    verify_access_token,
)
from app.services.persistence import get_user_scans, get_user_stats

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


@router.get("/me", response_model=UserResponse)
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

    return user


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
