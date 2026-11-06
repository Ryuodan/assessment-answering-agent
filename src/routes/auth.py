"""Who is making a request, and whether they may: the dependencies every route uses.

Moved out of `src/api.py` unchanged (plan 019), so that routers in this package
can use them without importing the application module.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from src import identity
from src.config import settings
from src.errors import Forbidden, SignInRequired
from src.identity import User


def current_user(request: Request) -> User:
    """Who is making this request.

    Falls back to the local stand-in when no allow-list is configured, so a
    developer running the app on their own machine is not asked to sign in to a
    single-user service. Setting `ALLOWED_EMAILS` is what turns gating on —
    there is no second switch that could disagree with it.
    """
    user = identity.resolve(request.cookies.get(identity.SESSION_COOKIE))
    if user is not None:
        return user
    if not identity.sign_in_required():
        return identity.local_user()
    raise SignInRequired("Sign in to continue.")


def user_payload(user: User) -> dict[str, Any]:
    """Who is signed in, as the pages read it, and whether this deployment asks anyone to sign in.

    With the review threshold, which the answer cards compare a score with
    (plan 030): the pages read it here, on load, rather than hard-coding 0.6.
    Nothing is drawn signed out, so the signed-out shape leaves it out.
    """
    return {
        "email": user.email,
        "team": user.team_id,
        "role": user.role,
        "is_admin": user.is_admin,
        "sign_in_required": identity.sign_in_required(),
        "review_threshold": settings.review_confidence_threshold,
    }


def current_admin(user: User = Depends(current_user)) -> User:
    """Refuse anyone who is not an administrator."""
    if not user.is_admin:
        raise Forbidden("Administrator access is required.", code="admin_required")
    return user
