"""Products: everyone on a team may list them; its leads and administrators change them (plan 020).

Each route works on the caller's own team. An administrator may name another
team with `team`; anyone else naming a team other than their own is refused.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src import identity, products, roles
from src.errors import Forbidden, NotFound
from src.identity import User
from src.routes.auth import current_user
from src.routes.pages import page

router = APIRouter()


# Lengths are checked by `src.products`, which says what the limit is; these
# bounds only stop a body large enough to be a mistake.
class ProductRequest(BaseModel):
    """A new product: its name, and optionally a colour and a description."""

    name: str = Field(max_length=200)
    color: str = Field(default="", max_length=20)
    description: str = Field(default="", max_length=1000)


class ProductChange(BaseModel):
    """What to change about a product. Each field left out stays as it is."""

    name: str | None = Field(default=None, max_length=200)
    color: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=1000)


def _team(user: User, team: str | None) -> str:
    """The team asked about: the caller's own or, for an administrator, any team that exists."""
    if not team or team == user.team_id:
        return user.team_id
    if not user.is_admin:
        raise Forbidden("Only an administrator can work on another team's products.", code="other_team")
    if not any(known["id"] == team for known in identity.list_teams()):
        raise NotFound(f"No team {team!r}.", code="team_not_found")
    return team


def _manager(user: User, team: str) -> None:
    if not roles.manages_products(user.role, user.team_id, team):
        raise Forbidden(
            "Only the team's leads and administrators can change its products.", code="product_manager_required"
        )


@router.get("/api/products")
def list_products(team: str | None = None, user: User = Depends(current_user)) -> dict[str, Any]:
    """The team's products, and whether the caller may change them."""
    which = _team(user, team)
    return {
        "team": which,
        "products": [product.as_dict() for product in products.list_products(which)],
        "can_manage": roles.manages_products(user.role, user.team_id, which),
        "palette": list(products.PALETTE),
    }


@router.post("/api/products")
def add_product(body: ProductRequest, team: str | None = None, user: User = Depends(current_user)) -> dict[str, Any]:
    """Add a product to the team. Its leads and administrators only."""
    which = _team(user, team)
    _manager(user, which)
    return {"product": products.add(user, which, body.name, body.color, body.description).as_dict()}


@router.patch("/api/products/{product_id}")
def edit_product(
    product_id: str, body: ProductChange, team: str | None = None, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Rename, recolour or redescribe a product. Its team's leads and administrators only."""
    which = _team(user, team)
    _manager(user, which)
    changed = products.update(user, which, product_id, name=body.name, color=body.color, description=body.description)
    return {"product": changed.as_dict()}


@router.delete("/api/products/{product_id}")
def delete_product(
    product_id: str, confirm: str = "", team: str | None = None, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Delete a product, with its documents and remembered answers. Needs `confirm=confirm`."""
    which = _team(user, team)
    _manager(user, which)
    return {"deleted": products.delete(user, which, product_id, confirm).as_dict()}


@router.get("/products", include_in_schema=False)
def products_page() -> HTMLResponse:
    """The Products page."""
    return page("products.html")
