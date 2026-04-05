"""Team / Organization service — create teams, invite members, shared reports."""

from __future__ import annotations

import secrets
from typing import Any

from app.services.database import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TeamError(Exception):
    """Team operation error."""


def create_team(owner_id: int, name: str, max_seats: int = 5) -> dict[str, Any]:
    """Create a new team and add the owner as admin."""
    db = get_db()
    team_id = db.execute(
        "INSERT INTO teams (name, owner_id, max_seats) VALUES (?, ?, ?)",
        (name, owner_id, max_seats),
    )
    db.execute(
        "INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'admin')",
        (team_id, owner_id),
    )
    logger.info("team_created", team_id=team_id, owner_id=owner_id)
    return {"id": team_id, "name": name, "owner_id": owner_id, "max_seats": max_seats}


def invite_member(team_id: int, email: str, invited_by: int) -> dict[str, Any]:
    """Create a team invite token for an email address."""
    db = get_db()
    team = db.fetch_one("SELECT * FROM teams WHERE id = ?", (team_id,))
    if not team:
        raise TeamError("Team not found.")

    # Check seat limit
    members = db.fetch_all("SELECT id FROM team_members WHERE team_id = ?", (team_id,))
    pending = db.fetch_all(
        "SELECT id FROM team_invites WHERE team_id = ? AND status = 'pending'", (team_id,)
    )
    if len(members) + len(pending) >= team["max_seats"]:
        raise TeamError(f"Team has reached its seat limit ({team['max_seats']}).")

    # Check if already a member
    existing = db.fetch_one(
        "SELECT tm.id FROM team_members tm JOIN users u ON tm.user_id = u.id "
        "WHERE tm.team_id = ? AND u.email = ?",
        (team_id, email.strip().lower()),
    )
    if existing:
        raise TeamError("User is already a team member.")

    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO team_invites (team_id, email, token, invited_by) VALUES (?, ?, ?, ?)",
        (team_id, email.strip().lower(), token, invited_by),
    )
    logger.info("team_invite_created", team_id=team_id, email=email)
    return {"token": token, "email": email, "team_name": team["name"]}


def accept_invite(token: str, user_id: int) -> dict[str, Any]:
    """Accept a team invite and add the user as a member."""
    db = get_db()
    invite = db.fetch_one(
        "SELECT * FROM team_invites WHERE token = ? AND status = 'pending'", (token,)
    )
    if not invite:
        raise TeamError("Invalid or expired invite.")

    db.execute(
        "INSERT INTO team_members (team_id, user_id, role, invited_by) VALUES (?, ?, 'member', ?)",
        (invite["team_id"], user_id, invite["invited_by"]),
    )
    db.execute("UPDATE team_invites SET status = 'accepted' WHERE id = ?", (invite["id"],))
    logger.info("team_invite_accepted", team_id=invite["team_id"], user_id=user_id)
    return {"team_id": invite["team_id"], "role": "member"}


def get_team(team_id: int) -> dict[str, Any] | None:
    """Get team details with member list."""
    db = get_db()
    team = db.fetch_one("SELECT * FROM teams WHERE id = ?", (team_id,))
    if not team:
        return None
    members = db.fetch_all(
        "SELECT tm.user_id, tm.role, tm.joined_at, u.name, u.email "
        "FROM team_members tm JOIN users u ON tm.user_id = u.id "
        "WHERE tm.team_id = ? ORDER BY tm.joined_at",
        (team_id,),
    )
    pending = db.fetch_all(
        "SELECT email, created_at FROM team_invites WHERE team_id = ? AND status = 'pending'",
        (team_id,),
    )
    return {**dict(team), "members": [dict(m) for m in members], "pending_invites": [dict(p) for p in pending]}


def get_user_teams(user_id: int) -> list[dict[str, Any]]:
    """Get all teams a user belongs to."""
    db = get_db()
    rows = db.fetch_all(
        "SELECT t.id, t.name, t.owner_id, t.max_seats, tm.role "
        "FROM teams t JOIN team_members tm ON t.id = tm.team_id "
        "WHERE tm.user_id = ?",
        (user_id,),
    )
    return [dict(r) for r in rows]


def get_team_scans(team_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Get scans from all team members."""
    db = get_db()
    rows = db.fetch_all(
        "SELECT s.*, u.name as user_name, d.filename "
        "FROM scans s "
        "JOIN team_members tm ON s.user_id = tm.user_id "
        "LEFT JOIN documents d ON s.document_id = d.document_id "
        "LEFT JOIN users u ON s.user_id = u.id "
        "WHERE tm.team_id = ? ORDER BY s.created_at DESC",
        (team_id,),
    )[:limit]
    for r in rows:
        r.pop("report_json", None)
    return [dict(r) for r in rows]


def remove_member(team_id: int, user_id: int, requester_id: int) -> None:
    """Remove a member from a team (only admin/owner can do this)."""
    db = get_db()
    team = db.fetch_one("SELECT owner_id FROM teams WHERE id = ?", (team_id,))
    if not team:
        raise TeamError("Team not found.")

    requester = db.fetch_one(
        "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
        (team_id, requester_id),
    )
    if not requester or requester["role"] != "admin":
        raise TeamError("Only team admins can remove members.")

    if user_id == team["owner_id"]:
        raise TeamError("Cannot remove the team owner.")

    db.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id))
    logger.info("team_member_removed", team_id=team_id, user_id=user_id)
