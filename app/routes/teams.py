"""Team/Organization routes — create teams, manage members, shared reports."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.auth_service import verify_access_token
from app.services.team_service import (
    TeamError,
    accept_invite,
    create_team,
    get_team,
    get_team_scans,
    get_user_teams,
    invite_member,
    remove_member,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/teams", tags=["teams"])


def _get_user_id(authorization: str) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    payload = verify_access_token(authorization[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return int(payload["sub"])


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    max_seats: int = Field(default=5, ge=2, le=100)


class InviteMemberRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class AcceptInviteRequest(BaseModel):
    token: str = Field(..., min_length=1)


@router.post("")
async def route_create_team(body: CreateTeamRequest, authorization: str = Header(default="")):
    """Create a new team (requires pro or premium plan)."""
    user_id = _get_user_id(authorization)
    try:
        return create_team(user_id, body.name, body.max_seats)
    except TeamError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def route_list_teams(authorization: str = Header(default="")):
    """List all teams the user belongs to."""
    user_id = _get_user_id(authorization)
    return {"teams": get_user_teams(user_id)}


@router.get("/{team_id}")
async def route_get_team(team_id: int, authorization: str = Header(default="")):
    """Get team details including members and pending invites."""
    user_id = _get_user_id(authorization)
    team = get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
    # Verify user is a member
    if not any(m["user_id"] == user_id for m in team.get("members", [])):
        raise HTTPException(status_code=403, detail="Not a member of this team.")
    return team


@router.post("/{team_id}/invite")
async def route_invite_member(team_id: int, body: InviteMemberRequest, authorization: str = Header(default="")):
    """Invite a new member to the team via email."""
    user_id = _get_user_id(authorization)
    try:
        return invite_member(team_id, body.email, user_id)
    except TeamError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/accept-invite")
async def route_accept_invite(body: AcceptInviteRequest, authorization: str = Header(default="")):
    """Accept a team invite."""
    user_id = _get_user_id(authorization)
    try:
        return accept_invite(body.token, user_id)
    except TeamError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{team_id}/scans")
async def route_team_scans(team_id: int, authorization: str = Header(default=""), limit: int = 50):
    """Get all scans from team members (shared view)."""
    user_id = _get_user_id(authorization)
    team = get_team(team_id)
    if not team or not any(m["user_id"] == user_id for m in team.get("members", [])):
        raise HTTPException(status_code=403, detail="Not a member of this team.")
    return {"scans": get_team_scans(team_id, limit=min(limit, 200))}


@router.delete("/{team_id}/members/{member_user_id}")
async def route_remove_member(team_id: int, member_user_id: int, authorization: str = Header(default="")):
    """Remove a member from the team (admin only)."""
    user_id = _get_user_id(authorization)
    try:
        remove_member(team_id, member_user_id, user_id)
        return {"status": "removed"}
    except TeamError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
