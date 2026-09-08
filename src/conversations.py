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


def create(user: User, first_message: str = "") -> Conversation:
    """Start a conversation. Returns it."""
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
    )
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO conversations
            (conversation_id, team_id, actor_email, title, batch_id, messages,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, NULL, '[]', ?, ?)
        """,
        (conversation_id, user.team_id, user.email, conversation.title, now, now),
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
    )


def load(conversation_id: str, *, team_id: str | None = None) -> Conversation | None:
    """One conversation, or None. Scoped to a team, like everything else."""
    conn = store.connect()
    if team_id is None:
        row = conn.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM conversations WHERE conversation_id = ? AND team_id = ?",
            (conversation_id, team_id),
        ).fetchone()
    return _row_to_conversation(row) if row else None


def save(conversation: Conversation) -> None:
    """Write back the messages, the title and the current questionnaire."""
    conn = store.connect()
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


def recent(team_id: str, *, limit: int = 30) -> list[dict]:
    """The team's conversations, most recently used first."""
    conn = store.connect()
    rows = conn.execute(
        """
        SELECT conversation_id, title, batch_id, actor_email, created_at, updated_at,
               (SELECT source_name FROM form_batches b
                 WHERE b.batch_id = c.batch_id) AS source_name
          FROM conversations c
         WHERE team_id = ?
         ORDER BY updated_at DESC, rowid DESC
         LIMIT ?
        """,
        (team_id, limit),
    ).fetchall()
    return [
        {
            "id": row["conversation_id"],
            "title": row["title"] or "New conversation",
            "batch_id": row["batch_id"] or "",
            "source_name": row["source_name"] or "",
            "actor_email": row["actor_email"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def delete(conversation_id: str) -> None:
    conn = store.connect()
    conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
    conn.commit()
