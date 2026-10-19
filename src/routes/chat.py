"""The assistant's routes: conversations, and one exchange at a time.

Moved out of `src/api.py` (plan 023) and included where they were.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from src import conversations, forms, products, service, store
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


def _turn_response(turn: assistant.Turn, conversation: Conversation, user: User) -> dict[str, Any]:
    return {
        "reply": turn.reply,
        "conversation_id": conversation.id,
        "title": conversation.title,
        "batch_id": turn.batch_id,
        "product_id": conversation.product_id,
        "steps": turn.steps,
        "sources": turn.sources,
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
    """The caller's own conversations, most recently used first, each with its product."""
    return {
        "conversations": conversations.recent(
            user.team_id,
            actor_email=user.email,
            limit=limit,
        )
    }


@router.post("/api/chat")
async def say_to_assistant(request: SayRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    """One exchange with the assistant.

    Long: a message can mean "answer 183 questions", which is minutes of work.
    The conversation is saved by the assistant itself before this returns, so a
    request that times out at a proxy has still recorded what it did.
    """
    if not assistant.configured():
        raise Unavailable("No model is configured for the assistant.", code="assistant_unconfigured")
    conversation = (
        _conversation(request.conversation_id, user)
        if request.conversation_id
        else assistant.start(user, request.message, request.product)
    )
    turn = await assistant.say(
        user,
        conversation,
        request.message,
        run_id=request.run_id,
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
    if not conversation_id:
        products.chosen(user.team_id, product)  # a new conversation's, checked before the file is kept
    path = service.save_upload(name, await file.read(), user.team_id, owner=user.email)
    conversation = (
        _conversation(conversation_id, user)
        if conversation_id
        else assistant.start(user, message or f"Read {name}", product)
    )
    turn = await assistant.say(
        user,
        conversation,
        message or f"Read {name} and tell me what is in it.",
        upload=path,
        run_id=run_id,
    )
    return _turn_response(turn, conversation, user)


@router.get("/api/chat/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """One conversation, as a transcript plus whatever answers it has produced.

    The stored messages are LangChain's, tool calls included, because the agent
    resumes from them. What comes back here is the readable half of that -- who
    said what -- because a person scrolling their own conversation has no use
    for a serialised tool call.
    """
    conversation = _conversation(conversation_id, user)
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
        "messages": transcript,
        "answers": assistant.answers_for(user, conversation),
    }


@router.post("/api/chat/{conversation_id}/product")
def choose_chat_product(
    conversation_id: str, request: ChooseChatProductRequest, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Refused unless it is the conversation's own product: a chat's product is fixed once it starts.

    Another product is 409 `product_locked` (TD-040); another team's is 404 `product_not_found` first.
    Kept so a page opened before the change, or a script, is told why rather than finding no route.
    """
    conversation = _conversation(conversation_id, user)
    assistant.choose_product(user, conversation, request.product)
    return {"id": conversation.id, "product_id": conversation.product_id, "batch_id": conversation.batch_id}


@router.delete("/api/chat/{conversation_id}")
def forget_conversation(conversation_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """Delete one of the caller's conversations. Its questionnaire and the answers in it stay."""
    _conversation(conversation_id, user)
    conversations.delete(conversation_id, actor_email=user.email)
    return {"deleted": conversation_id}
