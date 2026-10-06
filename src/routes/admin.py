"""The Access panel's routes: people, teams and access codes. Administrators only.

Moved out of `src/api.py` unchanged (plan 019). Included by the application at
the place these routes used to be defined, so the API contract keeps its order.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src import events, identity
from src.config import settings
from src.errors import Invalid, NotFound
from src.identity import User
from src.routes.auth import current_admin, user_payload

router = APIRouter()


# ---------------------------------------------------------------------------
# Administration
#
# Every route here changes who can reach the system, so every one records an
# event naming the administrator who did it. Being able to see that someone was
# added, and by whom, is the point of having a page rather than a config file.
# ---------------------------------------------------------------------------


TEAM_ID = r"^[a-z0-9][a-z0-9._-]*$"
"""What a team id may be. It names a directory and a knowledge base, so it is checked here."""


class AddUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    team: str | None = Field(default=None, max_length=64, pattern=TEAM_ID)
    role: str = identity.MEMBER


class UpdateUserRequest(BaseModel):
    team: str | None = Field(default=None, max_length=64, pattern=TEAM_ID)
    role: str | None = None
    disabled: bool | None = None


class PasswordRequest(BaseModel):
    password: str | None = Field(default=None, max_length=200)


class TeamRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(default="", max_length=120)


@router.get("/api/admin/overview")
def admin_overview(admin: User = Depends(current_admin)) -> dict[str, Any]:
    return {
        "users": identity.list_users(),
        "teams": identity.list_teams(),
        "you": user_payload(admin),
        "break_glass": identity.normalise(settings.admin_email) if settings.admin_email else None,
    }


@router.post("/api/admin/users")
def admin_add_user(body: AddUserRequest, admin: User = Depends(current_admin)) -> dict[str, Any]:
    user = identity.add_user(body.email, team_id=body.team, role=body.role, added_by=admin.email)
    events.record(
        admin,
        events.USER_ADDED,
        subject_type="user",
        subject_id=user.email,
        team=user.team_id,
        role=user.role,
    )
    return {"user": user.email, "team": user.team_id, "role": user.role}


@router.patch("/api/admin/users/{email}")
def admin_update_user(email: str, body: UpdateUserRequest, admin: User = Depends(current_admin)) -> dict[str, Any]:
    address = identity.normalise(email)
    if (body.role is not None and body.role != identity.ADMIN) or body.disabled:
        _refuse_last_admin(address)
    user = identity.update_user(address, team_id=body.team, role=body.role, disabled=body.disabled)
    events.record(
        admin,
        events.USER_UPDATED,
        subject_type="user",
        subject_id=address,
        team=body.team,
        role=body.role,
        disabled=body.disabled,
    )
    return {"user": user.email, "team": user.team_id, "role": user.role}


@router.delete("/api/admin/users/{email}")
def admin_remove_user(email: str, admin: User = Depends(current_admin)) -> dict[str, Any]:
    address = identity.normalise(email)
    _refuse_last_admin(address)
    identity.remove_user(address)
    events.record(admin, events.USER_REMOVED, subject_type="user", subject_id=address)
    return {"removed": address}


def _refuse_last_admin(email: str) -> None:
    """Stop the only administrator locking everybody out.

    Recoverable via ADMIN_EMAIL / ADMIN_PASSWORD and a restart — but that needs
    whoever runs the host, which is exactly the dependency this page exists to
    remove.
    """
    user = identity.find_user_any(email)
    if user and user.is_admin and identity.admin_count() <= 1:
        raise Invalid("This is the only administrator. Promote someone else first.", code="last_administrator")


@router.post("/api/admin/users/{email}/password")
def admin_set_password(email: str, body: PasswordRequest, admin: User = Depends(current_admin)) -> dict[str, Any]:
    """Give an admin their own password, or clear it back to the team code."""
    address = identity.normalise(email)
    if identity.find_user_any(address) is None:
        raise NotFound(f"No user {address}.", code="user_not_found")
    if address == identity.normalise(settings.admin_email):
        raise Invalid(
            "This account's password comes from the environment and would be "
            "restored on the next restart. Create a second administrator instead.",
            code="password_from_environment",
        )
    identity.set_password(address, body.password or None)
    events.record(
        admin,
        events.PASSWORD_SET,
        subject_type="user",
        subject_id=address,
        cleared=not body.password,
    )
    return {"user": address, "has_password": bool(body.password)}


@router.post("/api/admin/teams")
def admin_add_team(body: TeamRequest, admin: User = Depends(current_admin)) -> dict[str, Any]:
    identity.ensure_team(body.id, name=body.name)
    events.record(admin, events.TEAM_ADDED, subject_type="team", subject_id=body.id, name=body.name)
    return {"team": body.id}


@router.delete("/api/admin/teams/{team_id}")
def admin_remove_team(team_id: str, admin: User = Depends(current_admin)) -> dict[str, Any]:
    identity.delete_team(team_id)
    events.record(admin, events.TEAM_REMOVED, subject_type="team", subject_id=team_id)
    return {"removed": team_id}


@router.post("/api/admin/teams/{team_id}/access-code")
def admin_rotate_code(team_id: str, admin: User = Depends(current_admin)) -> dict[str, Any]:
    """Issue a new access code. The plaintext is returned exactly once.

    Everyone on the team has to be given the new one — rotating is what you do
    when somebody leaves, so the old code ceasing to work is the feature.
    """
    if not any(team["id"] == team_id for team in identity.list_teams()):
        raise NotFound(f"No team {team_id!r}.", code="team_not_found")
    code = identity.set_access_code(team_id)
    events.record(admin, events.CODE_ROTATED, subject_type="team", subject_id=team_id)
    return {"team": team_id, "access_code": code}
