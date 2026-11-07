"""A conversation with the assistant, kept so the work outlives the request.

The same reason batches are kept. Somebody says "read this file", waits four
minutes for 183 answers, comes back after lunch and says "now make the
governance ones shorter" -- and the second sentence only means anything if the
first is still there.

Messages are stored as LangChain serialised them, tool calls included, rather
than as a tidy transcript. The agent has to *resume*, and it can only do that
from what it actually said and saw. A display transcript would lose which tool
returned what, which is precisely the part a follow-up instruction depends on.

The current questionnaire is a column rather than something inferred from the
messages, because "fill it in" has to resolve to a file without re-reading the
whole conversation, and because the interface needs to know which batch's answer
cards to draw beside the chat.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict

from src import store
from src.identity import User

logger = logging.getLogger(__name__)

SUBJECT = "conversation"
"""What `events.record(subject_type=...)` should say about a conversation."""

TITLE_LENGTH = 70

LAST_USED = "MAX(updated_at, used_at)"
"""When a conversation was last used: something said in it, or opened (plan 033)."""


@dataclass
class Conversation:
    """One chat, and the questionnaire it is about."""

    id: str
    team_id: str
    actor_email: str
    title: str
    batch_id: str
    messages: list[BaseMessage] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    product_id: str = ""
    """The product this chat is for, or "" for General (plan 023). Its questionnaire's too."""
    used_at: str = ""
    """When it was last used, `LAST_USED`: what retention counts from (plan 033)."""


def title_from(text: str) -> str:
    """A conversation's name, taken from what was first asked of it.

    Trimmed on a word boundary where one is near enough, because a title cut
    mid-word reads like a bug in the list it appears in.
    """
    flat = " ".join(text.split())
    if len(flat) <= TITLE_LENGTH:
        return flat
    cut = flat[:TITLE_LENGTH]
    space = cut.rfind(" ")
    return (cut[:space] if space > TITLE_LENGTH - 20 else cut).rstrip(" ,.;:") + "…"


def create(user: User, first_message: str = "", product_id: str = "") -> Conversation:
    """Start a conversation, for a product or General (""). Returns it."""
    conversation_id = uuid.uuid4().hex[:12]
    now = store.utcnow()
    conversation = Conversation(
        id=conversation_id,
        team_id=user.team_id,
        actor_email=user.email,
        title=title_from(first_message),
        batch_id="",
        created_at=now,
        updated_at=now,
        product_id=product_id,
        used_at=now,
    )
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO conversations
            (conversation_id, team_id, actor_email, title, batch_id, messages,
             created_at, updated_at, product_id)
        VALUES (?, ?, ?, ?, NULL, '[]', ?, ?, ?)
        """,
        (conversation_id, user.team_id, user.email, conversation.title, now, now, product_id),
    )
    conn.commit()
    return conversation


def _row_to_conversation(row) -> Conversation:
    try:
        messages = messages_from_dict(json.loads(row["messages"]))
    except Exception:
        # A message shape LangChain no longer understands, after an upgrade.
        # An unreadable history is a conversation that starts again, not a
        # request that fails -- everything it produced is in the batch.
        logger.exception("Could not read the history of conversation %s", row["conversation_id"])
        messages = []
    return Conversation(
        id=row["conversation_id"],
        team_id=row["team_id"],
        actor_email=row["actor_email"],
        title=row["title"],
        batch_id=row["batch_id"] or "",
        messages=messages,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        product_id=row["product_id"],
        used_at=row["last_used"],
    )


def load(
    conversation_id: str,
    *,
    team_id: str | None = None,
    actor_email: str | None = None,
) -> Conversation | None:
    """One conversation, or None.

    A conversation belongs to the person who had it. Somebody else's reads as
    absent rather than forbidden: which ids exist is not something a caller has
    business learning. `actor_email=None` skips that check, for the places that
    have already established who is asking -- or that are not a person at all,
    like the storage housekeeping.
    """
    conn = store.connect()
    sql = f"SELECT *, {LAST_USED} AS last_used FROM conversations WHERE conversation_id = ?"
    params: list[object] = [conversation_id]
    if team_id is not None:
        sql += " AND team_id = ?"
        params.append(team_id)
    if actor_email is not None:
        sql += " AND actor_email = ?"
        params.append(actor_email)
    row = conn.execute(sql, params).fetchone()
    return _row_to_conversation(row) if row else None


def save(conversation: Conversation) -> None:
    """Write back the messages, the title and the current questionnaire.

    Not the product: it is fixed when the conversation is created (TD-040), and
    kept when the product is deleted, so that the chat stays listed, read-only,
    as that product's (plan 027). Nothing a turn saves can change it.
    """
    conn = store.connect()
    # A questionnaire the turn opened may have been deleted while it ran (plan 033's review):
    # the turn is saved without it rather than lost to the foreign key.
    if (
        conversation.batch_id
        and not conn.execute("SELECT 1 FROM form_batches WHERE batch_id = ?", (conversation.batch_id,)).fetchone()
    ):
        conversation.batch_id = ""
    conn.execute(
        """
        UPDATE conversations
           SET messages = ?, title = ?, batch_id = ?, updated_at = ?
         WHERE conversation_id = ?
        """,
        (
            json.dumps(messages_to_dict(conversation.messages), ensure_ascii=False),
            conversation.title,
            conversation.batch_id or None,
            store.utcnow(),
            conversation.id,
        ),
    )
    conn.commit()


def recent(team_id: str, *, actor_email: str | None = None, limit: int = 30) -> list[dict]:
    """One person's conversations, most recently used first: said in, or since plan 033 opened.

    Theirs and nobody else's. A conversation is what somebody said while they
    were working -- half-formed instructions, a file another company sent them,
    corrections -- and it was listed for the whole team, so everyone read
    everyone's. `actor_email=None` lists the team's, which only housekeeping
    and the tests ask for.
    """
    conn = store.connect()
    sql = f"""
        SELECT conversation_id, title, batch_id, actor_email, created_at, updated_at, product_id,
               {LAST_USED} AS used_at,
               (SELECT source_name FROM form_batches b
                 WHERE b.batch_id = c.batch_id) AS source_name
          FROM conversations c
         WHERE team_id = ?
    """
    params: list[object] = [team_id]
    if actor_email is not None:
        sql += " AND actor_email = ?"
        params.append(actor_email)
    sql += " ORDER BY used_at DESC, rowid DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": row["conversation_id"],
            "title": row["title"] or "New conversation",
            "batch_id": row["batch_id"] or "",
            "source_name": row["source_name"] or "",
            "actor_email": row["actor_email"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "used_at": row["used_at"],
            "product_id": row["product_id"],
        }
        for row in rows
    ]


def touch(conversation_id: str) -> None:
    """Record that a conversation was opened: opening is using it (plan 033). Nothing else changes."""
    conn = store.connect()
    with conn:
        conn.execute(
            "UPDATE conversations SET used_at = ? WHERE conversation_id = ?", (store.utcnow(), conversation_id)
        )


def delete(conversation_id: str, *, actor_email: str | None = None) -> bool:
    """Forget one conversation. Returns whether there was one to forget.

    `actor_email` is the owner it must belong to, so a delete cannot reach
    somebody else's conversation even with the id in hand.
    """
    conn = store.connect()
    sql = "DELETE FROM conversations WHERE conversation_id = ?"
    params: list[object] = [conversation_id]
    if actor_email is not None:
        sql += " AND actor_email = ?"
        params.append(actor_email)
    deleted = conn.execute(sql, params).rowcount
    conn.commit()
    return bool(deleted)
