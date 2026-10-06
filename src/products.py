"""A team's products: each will have a knowledge base and an answer memory of its own.

The team keeps one shared knowledge base and answer memory. A product adds its
own beside them: a questionnaire answered for a product draws on the shared
material and on that product's, and one answered for no product ("General")
draws on the shared material alone (plan 018). This module is the products
themselves -- their names, colours and descriptions -- and nothing they hold;
plans 021 to 023 give them a knowledge base, a memory and a place in each
questionnaire and conversation.

Who may change them is `src.roles.manages_products`: the team's leads, and any
administrator. Everyone on the team may list them.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from src import events, store
from src.config import settings
from src.errors import Invalid, ProductNameTaken, ProductNotFound
from src.identity import User
from src.logs import get_logger

logger = get_logger(__name__)

NAME_MAX = 40
DESCRIPTION_MAX = 200
CONFIRM_WORD = "confirm"
"""What has to be typed, on the page and in the API, before a product is deleted."""

PALETTE = ("#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626", "#0891b2", "#db2777", "#4b5563")
"""Colours given in turn to products added without one: blue, green, amber, purple, red, cyan, pink, grey."""

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Product:
    """One of a team's products."""

    id: str
    team_id: str
    name: str
    color: str
    description: str
    created_by: str
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _product(row: Any) -> Product:
    return Product(
        id=row["product_id"],
        team_id=row["team_id"],
        name=row["name"],
        color=row["color"],
        description=row["description"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_products(team_id: str) -> list[Product]:
    """The team's products, by name."""
    rows = store.connect().execute("SELECT * FROM products WHERE team_id = ? ORDER BY name COLLATE NOCASE", (team_id,))
    return [_product(row) for row in rows]


def get(team_id: str, product_id: str) -> Product:
    """One of the team's products. Another team's reads as absent."""
    row = (
        store.connect()
        .execute("SELECT * FROM products WHERE team_id = ? AND product_id = ?", (team_id, product_id))
        .fetchone()
    )
    if row is None:
        raise ProductNotFound(f"No product {product_id!r} in this team.")
    return _product(row)


def _name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > NAME_MAX:
        raise Invalid(f"A product's name has 1 to {NAME_MAX} characters.", code="product_name_invalid")
    return cleaned


def _color(color: str, team_id: str) -> str:
    if not color:
        return PALETTE[len(list_products(team_id)) % len(PALETTE)]
    if not _COLOR.match(color):
        raise Invalid("A colour is written #RRGGBB, for example #2563eb.", code="product_color_invalid")
    return color.lower()


def _description(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) > DESCRIPTION_MAX:
        raise Invalid(f"A description has at most {DESCRIPTION_MAX} characters.", code="product_description_too_long")
    return cleaned


def _refuse_taken(team_id: str, name: str, keep: str = "") -> None:
    """A name in use, whatever its case. Checked here as well as by the index,
    which folds only ASCII letters, so that Arabic and other names are caught too."""
    for product in list_products(team_id):
        if product.id != keep and product.name.casefold() == name.casefold():
            raise ProductNameTaken(f"This team already has a product called {product.name!r}.")


def add(actor: User | None, team_id: str, name: str, color: str = "", description: str = "") -> Product:
    """Add a product to a team. `actor` None is the seeding at startup, which records no event."""
    cleaned = _name(name)
    _refuse_taken(team_id, cleaned)
    product = Product(
        id=uuid.uuid4().hex[:12],
        team_id=team_id,
        name=cleaned,
        color=_color(color, team_id),
        description=_description(description),
        created_by=actor.email if actor else "environment",
        created_at=store.utcnow(),
        updated_at=store.utcnow(),
    )
    conn = store.connect()
    try:
        conn.execute(
            "INSERT INTO products (product_id, team_id, name, color, description, created_by, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (*asdict(product).values(),),
        )
    except store.IntegrityError as clash:  # two adds of one name at once
        raise ProductNameTaken(f"This team already has a product called {cleaned!r}.") from clash
    conn.commit()
    if actor:
        events.record(actor, events.PRODUCT_ADDED, subject_type="product", subject_id=product.id, name=cleaned)
    return product


def update(
    actor: User,
    team_id: str,
    product_id: str,
    *,
    name: str | None = None,
    color: str | None = None,
    description: str | None = None,
) -> Product:
    """Rename, recolour or redescribe a product. What is left out stays as it was."""
    current = get(team_id, product_id)
    changed = {
        "name": _name(name) if name is not None else current.name,
        "color": _color(color, team_id) if color else current.color,
        "description": _description(description) if description is not None else current.description,
    }
    if changed["name"] != current.name:
        _refuse_taken(team_id, changed["name"], keep=product_id)
    conn = store.connect()
    conn.execute(
        "UPDATE products SET name = ?, color = ?, description = ?, updated_at = ? WHERE product_id = ?",
        (changed["name"], changed["color"], changed["description"], store.utcnow(), product_id),
    )
    conn.commit()
    events.record(actor, events.PRODUCT_UPDATED, subject_type="product", subject_id=product_id, **changed)
    return get(team_id, product_id)


def delete(actor: User, team_id: str, product_id: str, confirm: str) -> Product:
    """Delete a product, once "confirm" has been typed.

    The page warns that the product's documents and remembered answers go with
    it; the word is checked here too, so no other caller can delete one without
    the same confirmation. What a product holds is deleted by the plans that
    give it something to hold (021, 022).
    """
    if confirm.strip().casefold() != CONFIRM_WORD:
        raise Invalid(f'Type "{CONFIRM_WORD}" to delete a product.', code="confirmation_required")
    product = get(team_id, product_id)
    conn = store.connect()
    conn.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
    conn.commit()
    events.record(actor, events.PRODUCT_DELETED, subject_type="product", subject_id=product_id, name=product.name)
    return product


def seed() -> list[Product]:
    """Add `SEED_PRODUCTS` to the default team, the first time only.

    Recorded in `seeds`, so a product deleted on the page is not added back by
    the next restart, and neither is the whole list if every one of them goes.
    """
    conn = store.connect()
    if conn.execute("SELECT 1 FROM seeds WHERE name = 'products'").fetchone():
        return []
    added = []
    for name in (part.strip() for part in settings.seed_products.split(",")):
        if name and not any(p.name.casefold() == name.casefold() for p in list_products(settings.default_team)):
            added.append(add(None, settings.default_team, name))
    conn.execute("INSERT INTO seeds (name, applied_at) VALUES ('products', ?)", (store.utcnow(),))
    conn.commit()
    if added:
        logger.info("products.seeded", team=settings.default_team, products=len(added))
    return added
