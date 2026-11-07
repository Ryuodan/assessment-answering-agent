"""The assistant's routes: conversations, and one exchange at a time.

Moved out of `src/api.py` (plan 023) and included where they were.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from src import chat_running, conversations, forms, products, reading, retention, service, store
from src.agents import assistant
from src.conversations import Conversation
from src.errors import NotFound, Unavailable
from src.identity import User
from src.routes.auth import current_user

router = APIRouter()


class SayRequest(BaseModel):
    """One message to the assistant, in a conversation or starting one."""

    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str = Field(default="", max_length=64)

    run_id: str = Field(default="", max_length=64)
    """A name the caller picked for this turn, so it can watch it happen.

    Minted by the page rather than here, because a first turn -- the slow one,
    where a file is read and answered -- has no conversation and no batch yet
    to be named after. `/api/assessments/progress/{run_id}` reports on it.
    """

    product: str = Field(default="", max_length=64)
    """The product a new conversation is for: an id, or "" for General (plan 023).

    Read only when this message starts the conversation, and fixed after that
    (TD-040): `POST /api/chat/{id}/product` refuses any other product. The
    multipart upload route reads it the same way."""


class ChooseChatProductRequest(BaseModel):
    """The product a conversation is for: a product's id, or "" for General."""

    product: str = Field(default="", max_length=64)


def _conversation(conversation_id: str, user: User) -> Conversation:
    conversation = conversations.load(
        conversation_id,
        team_id=user.team_id,
        actor_email=user.email,
    )
    if conversation is None:
        raise NotFound("That conversation no longer exists.", code="conversation_not_found")
    return conversation


def _open(conversation: Conversation, user: User) -> Conversation:
    """A conversation that can still be added to: not a deleted product's, which is kept read-only (plan 027)."""
    products.refuse_deleted(user.team_id, conversation.product_id)
    return conversation


def _turn_response(turn: assistant.Turn, conversation: Conversation, user: User) -> dict[str, Any]:
    return {
        "reply": turn.reply,
        "conversation_id": conversation.id,
        "title": conversation.title,
        "batch_id": turn.batch_id,
        "product_id": conversation.product_id,
        "steps": turn.steps,
        "sources": turn.sources,
        # Questions answered in the chat, each drawn as its answer card under the reply (plan 030).
        "direct_answers": turn.direct_answers,
        "refreshed": turn.refreshed,
        "stopped_early": turn.stopped_early,
        "seconds": round(turn.seconds, 1),
        "tokens": turn.input_tokens + turn.output_tokens,
        "at": store.utcnow(),
        "changed": turn.refreshed,
        "answers": assistant.answers_for(user, conversation) if turn.refreshed else None,
    }


@router.get("/api/chat")
def list_conversations(user: User = Depends(current_user), limit: int = 30) -> dict[str, Any]:
    """The caller's own conversations, most recently used first, each with its product.

    And with the turn running in it, or null (plan 031): the page marks the row,
    and finds a new chat's id by the run id it sent the first message with. And
    with the day it is kept until, or null when nothing is deleted (plan 033).
    """
    listed = conversations.recent(user.team_id, actor_email=user.email, limit=limit)
    return {
        "conversations": [
            {**row, "running": chat_running.running(row["id"]), "kept_until": retention.kept_until(row["used_at"])}
            for row in listed
        ]
    }


@router.post("/api/chat")
async def say_to_assistant(request: SayRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    """One exchange with the assistant.

    Long: a message can mean "answer 183 questions", which is minutes of work.
    The conversation is saved by the assistant itself before this returns, so a
    request that times out at a proxy has still recorded what it did. Meanwhile
    it is held (`chat_running`): 409 `conversation_busy` for another message.
    """
    if not assistant.configured():
        raise Unavailable("No model is configured for the assistant.", code="assistant_unconfigured")
    conversation = (
        _open(_conversation(request.conversation_id, user), user)
        if request.conversation_id
        else assistant.start(user, request.message, request.product)
    )
    run_id = chat_running.run_id_for(request.run_id)  # never "": its progress and its hold are named by it
    with chat_running.hold(conversation.id, run_id=run_id, message=assistant.spoken(request.message)):
        turn = await assistant.say(
            user,
            conversation,
            request.message,
            run_id=run_id,
        )
    return _turn_response(turn, conversation, user)


@router.post("/api/chat/upload")
async def say_with_a_file(
    message: str = Form(""),
    conversation_id: str = Form(""),
    run_id: str = Form(""),
    file: UploadFile = File(...),
    product: str = Form(""),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """A message with a questionnaire attached.

    Separate from the plain message route because it is multipart, not because
    it does anything different: the file is saved, the assistant is told it is
    there, and it decides to open it like any other operation. `product` is a new
    conversation's, as on the plain message route.
    """
    if not assistant.configured():
        raise Unavailable("No model is configured for the assistant.", code="assistant_unconfigured")
    name = file.filename or "questionnaire"
    if Path(name).suffix.lower() not in forms.SUPPORTED:
        raise forms.UnsupportedForm(
            f"{Path(name).suffix or 'That file'} is not a questionnaire this can read. "
            f"Supported: {', '.join(forms.SUPPORTED)}."
        )
    # Checked before the file is kept: the conversation's, or a new one's product.
    existing = _open(_conversation(conversation_id, user), user) if conversation_id else None
    if existing is None:
        products.chosen(user.team_id, product)
    said = message or f"Read {name} and tell me what is in it."
    run_id = chat_running.run_id_for(run_id)
    # Held with what the transcript will show once the turn is saved: the words, and the file as it was kept.
    with ExitStack() as held:
        if existing is not None:
            # Before the file is kept (plan 031): a message from another tab meanwhile is the one refused,
            # not this upload once its file is in the folder. A new chat's id is nobody else's yet.
            held.enter_context(chat_running.hold(existing.id, run_id=run_id, message=assistant.spoken(said), file=name))
        path = service.save_upload(name, await file.read(), user.team_id, owner=user.email)
        held.enter_context(reading.holding(path))  # until the turn has opened it, or ended (TD-078)
        conversation = existing or assistant.start(user, message or f"Read {name}", product)
        if existing is None:
            held.enter_context(
                chat_running.hold(conversation.id, run_id=run_id, message=assistant.spoken(said), file=path.name)
            )
        else:
            chat_running.kept_as(conversation.id, run_id, path.name)
        turn = await assistant.say(user, conversation, said, upload=path, run_id=run_id)
    return _turn_response(turn, conversation, user)


@router.get("/api/chat/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """One conversation, as a transcript plus whatever answers it has produced.

    The stored messages are LangChain's, tool calls included, because the agent
    resumes from them. What comes back here is the readable half of that -- who
    said what -- because a person scrolling their own conversation has no use
    for a serialised tool call.

    `running` is read before the conversation is loaded (plan 031): a turn
    that ends in between comes back saved and still reported, which the
    page's next check corrects. Read after, a slow `answers_for` let a turn
    end unseen, and the page drew a transcript without it, and no turn.

    Opening it is using it: its `kept_until` starts again from now (plan 033).
    A conversation whose questionnaire was deleted opens with `answers` null.
    """
    running = chat_running.running(conversation_id)
    conversation = _conversation(conversation_id, user)
    conversations.touch(conversation.id)
    transcript = []
    for message in conversation.messages:
        kind = getattr(message, "type", "")
        if kind == "human":
            # Their own words, without the note that told the agent a file had
            # arrived -- that is not something anybody said. The file itself is
            # shown, beside the words, because it is what they were about.
            kept = message.additional_kwargs or {}
            transcript.append(
                {
                    "role": "you",
                    "text": assistant.spoken(str(message.content)),
                    "file": assistant.uploaded_name(message),
                    "at": kept.get("at", ""),
                }
            )
        elif kind == "ai" and not getattr(message, "tool_calls", None):
            text = message.content
            if isinstance(text, list):
                text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
            if str(text).strip():
                # What the turn did, stored on the reply itself when it was made.
                drawn = (message.additional_kwargs or {}).get(assistant.UI_KEY) or {}
                steps = drawn.get("steps", [])
                transcript.append(
                    {
                        "role": "assistant",
                        "text": str(text).strip(),
                        "steps": steps,
                        "sources": drawn.get("sources", []),
                        # Its answer cards (plan 030); a reply stored before then has none.
                        "direct_answers": drawn.get("direct_answers", []),
                        "at": drawn.get("at", ""),
                        # Recorded since replies learned to offer the answers; read
                        # off the steps for the ones stored before that.
                        "changed": drawn.get(
                            "changed", any(step.split("(", 1)[0] in assistant.CHANGES_ANSWERS for step in steps)
                        ),
                    }
                )
    return {
        "id": conversation.id,
        "title": conversation.title,
        "batch_id": conversation.batch_id,
        "product_id": conversation.product_id,
        # A deleted product's: kept to be read, and refused anything new (plan 027).
        "read_only": conversation.product_id in products.deleted(user.team_id),
        "messages": transcript,
        "answers": assistant.answers_for(user, conversation),
        # The turn still running in it, or null: its message is not in the transcript until it ends (plan 031).
        "running": running,
        "kept_until": retention.kept_until(store.utcnow()),  # opened just now (plan 033)
    }


@router.post("/api/chat/{conversation_id}/product")
def choose_chat_product(
    conversation_id: str, request: ChooseChatProductRequest, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Refused unless it is the conversation's own product: a chat's product is fixed once it starts.

    Another product is 409 `product_locked` (TD-040); another team's is 404 `product_not_found` first.
    A deleted product's chat is 409 `product_deleted` (plan 027). Kept so a page opened before the
    change, or a script, is told why rather than finding no route.
    """
    conversation = _open(_conversation(conversation_id, user), user)
    assistant.choose_product(user, conversation, request.product)
    return {"id": conversation.id, "product_id": conversation.product_id, "batch_id": conversation.batch_id}


@router.delete("/api/chat/{conversation_id}")
def forget_conversation(conversation_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """Delete one of the caller's conversations, a deleted product's too. Its questionnaire and answers stay.

    Not while a turn is running in it: 409 `conversation_busy` (plan 031).
    """
    _conversation(conversation_id, user)
    chat_running.refuse(conversation_id)
    conversations.delete(conversation_id, actor_email=user.email)
    return {"deleted": conversation_id}
