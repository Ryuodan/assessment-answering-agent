"""A team's products: each will have a knowledge base and an answer memory of its own.

The team keeps one shared knowledge base and answer memory. A product adds its
own beside them: a questionnaire answered for a product draws on the shared
material and on that product's, and one answered for no product ("General")
draws on the shared material alone (plan 018). This module is the products
themselves -- their names, colours and descriptions -- and nothing they hold;
plans 021 to 023 give them a knowledge base, a memory and a place in each
questionnaire and conversation. Deleting one is the exception: what it holds
goes with it, and is counted first, so the page can say what will go; the work
done for it stays, read-only, under its name (plan 027).

Who may change them is `src.roles.manages_products`: the team's leads, and any
administrator. Everyone on the team may list them.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src import answer_memory, batches, events, knowledge, scoped_knowledge, store, uploads
from src.config import settings
from src.errors import Invalid, ProductDeleted, ProductLocked, ProductNameTaken, ProductNotFound
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


@dataclass(frozen=True)
class Deletion:
    """What deleting a product removed, and any of its files that could not be removed."""

    product: Product
    files_removed: int
    answers_forgotten: int
    moved_from_shared: int  # of the answers forgotten, those moved in from the shared memory
    questionnaires: int  # kept, read-only
    conversations: int  # kept, read-only
    files_left: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """The counts without the product: what the route reports as `removed`, and the event records."""
        return {key: value for key, value in asdict(self).items() if key != "product"} | {
            "files_left": list(self.files_left)
        }


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


def deleted(team_id: str) -> dict[str, dict[str, str]]:
    """The team's deleted products, by id: the names their kept, read-only work is labelled with (plan 027)."""
    query = "SELECT product_id AS id, name, color, deleted_at FROM deleted_products WHERE team_id = ? ORDER BY name"
    return {row["id"]: dict(row) for row in store.connect().execute(query, (team_id,))}


def refuse_deleted(team_id: str, product_id: str) -> None:
    """Refuse to change a deleted product's questionnaire or chat: it is kept to read and download (plan 027)."""
    gone = deleted(team_id).get(product_id) if product_id else None
    if gone:
        raise ProductDeleted(
            f"{gone['name']} was deleted, so this is kept read-only: it can be read and its filled file "
            "downloaded, but no longer changed."
        )


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


def _count(table: str, team_id: str, product_id: str) -> int:
    query = f"SELECT COUNT(*) FROM {table} WHERE team_id = ? AND product_id = ?"
    return int(store.connect().execute(query, (team_id, product_id)).fetchone()[0])


def _moved_in(team_id: str, product_id: str) -> int:
    """How many of a product's remembered answers were moved into it, rather than given for it.

    The memory keeps no origin. The event a move records (`moved_to`) is the
    only trace, and it is read here rather than with SQLite's JSON functions,
    so that it does not depend on how the server's SQLite was built.
    """
    conn = store.connect()
    query = "SELECT entry_id FROM memory_entries WHERE team_id = ? AND product_id = ?"
    own = {row["entry_id"] for row in conn.execute(query, (team_id, product_id))}
    moves = conn.execute(
        "SELECT subject_id, payload FROM events WHERE team_id = ? AND kind = ? AND subject_type = 'memory_entry'"
        " AND instr(payload, ?) > 0",
        (team_id, events.MEMORY_EDITED, product_id),
    )
    return len(own & {row["subject_id"] for row in moves if store.loads(row["payload"]).get("moved_to") == product_id})


def _in_team_folder(team_id: str, product_id: str, names: set[str] | None) -> set[str]:
    """The documents of a product's knowledge base (or those of `names`) with a file in the team's folder only."""
    shared, own = settings.team_upload_dir(team_id), settings.product_upload_dir(team_id, product_id)
    sources = {s["name"] for s in scoped_knowledge.knowledge_stats(team_id, product_id=product_id)["sources"]}
    found = sources if names is None else sources & names
    return {n for n in found if n == Path(n).name and (shared / n).is_file() and not (own / n).exists()}


def legacy_files(team_id: str, product_id: str, names: set[str] | None = None) -> list[Path]:
    """A product's files from before it had a folder of its own, in the team's folder (plan 027).

    Its knowledge base names them, and its folder has no copy. One that the shared knowledge base or
    another product's also indexes, or a questionnaire reads, is kept: one name is one document. Found
    before the documents leave the index -- removed, cleared or deleted -- after which nothing says whose.
    """
    found = _in_team_folder(team_id, product_id, names)
    if not found:
        return []  # the usual case, and no other knowledge base is opened for it
    found -= set(knowledge.get_store(team_id).documents_indexed())
    for other in list_products(team_id):
        if other.id != product_id:
            found -= set(knowledge.get_store(team_id, product_id=other.id).documents_indexed())
    return sorted(settings.team_upload_dir(team_id) / name for name in found - set(batches.claimed_sources(team_id)))


def remove_documents(team_id: str, product_id: str, name: str = "") -> list[str]:
    """Remove one document of a product's knowledge base, or with no `name` all of them, with their files.

    Its files from before it had a folder go by `legacy_files`' rule, found
    first. Returns the files that could not be removed.
    """
    legacy = legacy_files(team_id, product_id, {name} if name else None)
    if name:
        return scoped_knowledge.delete_source(name, team_id, product_id=product_id, also=legacy)
    return scoped_knowledge.clear_knowledge(team_id, product_id=product_id, also=legacy)


def _files(team_id: str, product_id: str) -> list[Path]:
    """Every file deleting a product removes: its folder's, and its own from before it had one."""
    folder = settings.product_upload_dir(team_id, product_id)
    return uploads.document_files(folder) + legacy_files(team_id, product_id)


def deletion_preview(team_id: str, product_id: str) -> dict[str, Any]:
    """What deleting a product would remove, and what of the team's work would stay. Changes nothing.

    Counted across the whole team, because everyone's work is affected; the
    page shows it in its warning before anyone types the word. `kept` are its
    documents whose file stays, because something else uses it too.
    """
    product = get(team_id, product_id)
    files = _files(team_id, product_id)
    stats = scoped_knowledge.knowledge_stats(team_id, product_id=product_id)
    kept = _in_team_folder(team_id, product_id, None) - {path.name for path in files}
    return {
        "product": product.as_dict(),
        "confirm_word": CONFIRM_WORD,
        "documents": {
            "files": len(files),
            "names": sorted(path.name for path in files)[:20],
            "indexed": len(stats["sources"]),
            "chunks": stats["guideline_chunks"],
            "kept": len(kept),
        },
        "answers": {
            "remembered": _count("memory_entries", team_id, product_id),
            "moved_from_shared": _moved_in(team_id, product_id),
        },
        "questionnaires": _count("form_batches", team_id, product_id),
        "conversations": _count("conversations", team_id, product_id),
    }


def delete(actor: User, team_id: str, product_id: str, confirm: str) -> Deletion:
    """Delete a product, once "confirm" has been typed, and say what went with it.

    The page warns, with `deletion_preview`'s counts, that the product's
    documents and their files go with it, and its remembered answers, those
    moved in from Shared included; the word is checked here too, so no other
    caller can delete one without the same confirmation. Its knowledge base
    goes first (plan 021), so a failure there leaves the product whole rather
    than half-deleted. Its files go last, after the commit: a file that cannot
    be removed then is in a folder nothing lists or opens, and is reported.

    Questionnaires and chats that were for it keep its id and stay listed, read-only, under the name
    `deleted_products` keeps (plan 027, the user's decision): read and downloaded, never changed again.
    Made General, a later approval would file the product's wording as a shared answer.
    """
    if confirm.strip().casefold() != CONFIRM_WORD:
        raise Invalid(f'Type "{CONFIRM_WORD}" to delete a product.', code="confirmation_required")
    product = get(team_id, product_id)
    files = _files(team_id, product_id)  # while its knowledge base can still say which are its own
    moved = _moved_in(team_id, product_id)
    kept = {table: _count(table, team_id, product_id) for table in ("form_batches", "conversations")}
    scoped_knowledge.drop_product(team_id, product_id)
    forgotten = answer_memory.forget_product(team_id, product_id)  # its remembered answers (plan 022)
    conn = store.connect()
    conn.execute(
        "INSERT INTO deleted_products (product_id, team_id, name, color, deleted_at)"
        " SELECT product_id, team_id, name, color, ? FROM products WHERE product_id = ?",
        (store.utcnow(), product_id),
    )
    conn.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
    conn.commit()
    left = uploads.remove(files, folder=settings.product_upload_dir(team_id, product_id))
    deletion = Deletion(
        product,
        files_removed=sum(not path.exists() for path in files),
        answers_forgotten=forgotten,
        moved_from_shared=moved,
        questionnaires=kept["form_batches"],
        conversations=kept["conversations"],
        files_left=tuple(left),
    )
    if left:
        logger.warning("products.files_remove_failed", product=product_id, files=left[:50], fix="remove them by hand")
    removed = deletion.as_dict()
    events.record(
        actor, events.PRODUCT_DELETED, subject_type="product", subject_id=product_id, name=product.name, **removed
    )
    logger.info("products.deleted", team=team_id, product=product_id, **(removed | {"files_left": len(left)}))
    return deletion


def chosen(team_id: str, product_id: str) -> str:
    """The product a caller asked for, checked: "" for General, or one of this team's products.

    Another team's product, or one that was deleted, is `product_not_found`.
    """
    return get(team_id, product_id).id if product_id else ""


def refuse_change(team_id: str, fixed: str, asked: str, message: str) -> None:
    """Refuse any product but `fixed`: a questionnaire's or a chat's is fixed once chosen (TD-040).

    The product asked for is checked first, so another team's, or one that was
    deleted, is still `product_not_found`. Asking for the one it already has is
    accepted, and changes nothing. `message` says what to do instead.
    """
    if chosen(team_id, asked) != fixed:
        raise ProductLocked(message)


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
