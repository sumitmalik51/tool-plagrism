"""Tests for team/organization routes."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

TEAMS_PREFIX = "/api/v1/teams"

# Fake JWT payload for authenticated requests
_FAKE_USER_PAYLOAD = {"sub": "42", "email": "test@example.com"}


def _auth_header(token: str = "fake-jwt") -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth checks
# ---------------------------------------------------------------------------

class TestTeamsAuth:
    def test_create_team_requires_auth(self) -> None:
        resp = client.post(TEAMS_PREFIX, json={"name": "Test Team"})
        assert resp.status_code == 401

    def test_list_teams_requires_auth(self) -> None:
        resp = client.get(TEAMS_PREFIX)
        assert resp.status_code == 401

    def test_get_team_requires_auth(self) -> None:
        resp = client.get(f"{TEAMS_PREFIX}/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Create team
# ---------------------------------------------------------------------------

class TestCreateTeam:
    @patch("app.routes.teams.create_team")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_create_team_success(self, mock_verify, mock_create) -> None:
        mock_create.return_value = {"id": 1, "name": "My Team", "max_seats": 5}

        resp = client.post(
            TEAMS_PREFIX,
            json={"name": "My Team", "max_seats": 5},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Team"
        mock_create.assert_called_once_with(42, "My Team", 5)

    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_create_team_empty_name_rejected(self, mock_verify) -> None:
        resp = client.post(
            TEAMS_PREFIX,
            json={"name": ""},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    @patch("app.routes.teams.create_team")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_create_team_error_returns_400(self, mock_verify, mock_create) -> None:
        from app.services.team_service import TeamError
        mock_create.side_effect = TeamError("Plan does not support teams")

        resp = client.post(
            TEAMS_PREFIX,
            json={"name": "My Team"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "Plan does not support teams" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# List / get teams
# ---------------------------------------------------------------------------

class TestListTeams:
    @patch("app.routes.teams.get_user_teams")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_list_teams_returns_array(self, mock_verify, mock_get) -> None:
        mock_get.return_value = [{"id": 1, "name": "Team A"}]

        resp = client.get(TEAMS_PREFIX, headers=_auth_header())
        assert resp.status_code == 200
        assert len(resp.json()["teams"]) == 1


class TestGetTeam:
    @patch("app.routes.teams.get_team")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_get_team_not_found(self, mock_verify, mock_get) -> None:
        mock_get.return_value = None
        resp = client.get(f"{TEAMS_PREFIX}/999", headers=_auth_header())
        assert resp.status_code == 404

    @patch("app.routes.teams.get_team")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_get_team_not_a_member(self, mock_verify, mock_get) -> None:
        mock_get.return_value = {"id": 1, "members": [{"user_id": 99}]}
        resp = client.get(f"{TEAMS_PREFIX}/1", headers=_auth_header())
        assert resp.status_code == 403

    @patch("app.routes.teams.get_team")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_get_team_success(self, mock_verify, mock_get) -> None:
        mock_get.return_value = {
            "id": 1,
            "name": "Team A",
            "members": [{"user_id": 42, "role": "owner"}],
        }
        resp = client.get(f"{TEAMS_PREFIX}/1", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["name"] == "Team A"


# ---------------------------------------------------------------------------
# Invite / accept / remove
# ---------------------------------------------------------------------------

class TestTeamInvite:
    @patch("app.routes.teams.invite_member")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_invite_member_success(self, mock_verify, mock_invite) -> None:
        mock_invite.return_value = {"status": "invited", "email": "new@example.com"}

        resp = client.post(
            f"{TEAMS_PREFIX}/1/invite",
            json={"email": "new@example.com"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200

    @patch("app.routes.teams.invite_member")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_invite_team_error(self, mock_verify, mock_invite) -> None:
        from app.services.team_service import TeamError
        mock_invite.side_effect = TeamError("Team is full")

        resp = client.post(
            f"{TEAMS_PREFIX}/1/invite",
            json={"email": "new@example.com"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400


class TestAcceptInvite:
    @patch("app.routes.teams.accept_invite")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_accept_invite_success(self, mock_verify, mock_accept) -> None:
        mock_accept.return_value = {"status": "joined", "team_id": 1}

        resp = client.post(
            f"{TEAMS_PREFIX}/accept-invite",
            json={"token": "invite-token-abc"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200


class TestRemoveMember:
    @patch("app.routes.teams.remove_member")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_remove_member_success(self, mock_verify, mock_remove) -> None:
        mock_remove.return_value = None

        resp = client.delete(
            f"{TEAMS_PREFIX}/1/members/99",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    @patch("app.routes.teams.remove_member")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_remove_member_not_admin(self, mock_verify, mock_remove) -> None:
        from app.services.team_service import TeamError
        mock_remove.side_effect = TeamError("Only team admin can remove members")

        resp = client.delete(
            f"{TEAMS_PREFIX}/1/members/99",
            headers=_auth_header(),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Team scans
# ---------------------------------------------------------------------------

class TestTeamScans:
    @patch("app.routes.teams.get_team_scans")
    @patch("app.routes.teams.get_team")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_scans_requires_membership(self, mock_verify, mock_team, mock_scans) -> None:
        mock_team.return_value = {"id": 1, "members": [{"user_id": 99}]}
        resp = client.get(f"{TEAMS_PREFIX}/1/scans", headers=_auth_header())
        assert resp.status_code == 403

    @patch("app.routes.teams.get_team_scans")
    @patch("app.routes.teams.get_team")
    @patch("app.routes.teams.verify_access_token", return_value=_FAKE_USER_PAYLOAD)
    def test_scans_success(self, mock_verify, mock_team, mock_scans) -> None:
        mock_team.return_value = {"id": 1, "members": [{"user_id": 42}]}
        mock_scans.return_value = [{"id": 1, "score": 15.0}]

        resp = client.get(f"{TEAMS_PREFIX}/1/scans", headers=_auth_header())
        assert resp.status_code == 200
        assert len(resp.json()["scans"]) == 1
