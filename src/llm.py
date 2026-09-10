"""Groq chat-model factory.

Every LLM call in the app goes through `chat_llm()` or `structured_llm()`, so
model, temperature and credentials are configured exactly once.

`structured_llm()` carries three layers of defence around Groq's structured
output, covering provider and model-specific structured-output edge cases:

1. The provider's own tool-calling structured output.
2. `with_retry` on schema/parser failures and Groq's `tool_use_failed`.
3. A recovery wrapper for the specific case where the model emitted *valid*
   arguments under the *wrong* tool name — Groq rejects the call before it
   returns, but the usable payload is sitting in `error.failed_generation`.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from langchain_groq import ChatGroq
from pydantic import BaseModel, SecretStr, ValidationError

from src.config import settings

try:  # pragma: no cover - depends on the installed groq client version
    from groq import APIConnectionError as GroqConnectionError
    from groq import BadRequestError as GroqBadRequestError
    from groq import InternalServerError as GroqServerError
    from groq import RateLimitError as GroqRateLimitError
except ImportError:  # pragma: no cover
    GroqBadRequestError = GroqRateLimitError = GroqConnectionError = GroqServerError = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Everything worth trying again. Rate limits matter most: questions fan out
# concurrently, so a 429 is the expected response to a large assessment, not an
# exceptional one — and without it here the question fails and comes back with
# an empty answer rather than waiting its turn.
_RETRYABLE: tuple[type[BaseException], ...] = (ValidationError, OutputParserException)
_RETRYABLE += tuple(
    error
    for error in (GroqBadRequestError, GroqRateLimitError, GroqConnectionError, GroqServerError)
    if error is not None
)

_MAX_ATTEMPTS = 5


@lru_cache(maxsize=8)
def chat_llm(temperature: float | None = None, model: str | None = None) -> BaseChatModel:
    """Return a configured `ChatGroq`. Cached per (temperature, model) pair."""
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not set — copy .env.example to .env and fill it in.")

    kwargs: dict[str, Any] = {
        "model": model or settings.groq_chat_model,
        "temperature": settings.llm_temperature if temperature is None else temperature,
        "api_key": SecretStr(settings.groq_api_key),
    }
    if settings.groq_base_url:
        kwargs["base_url"] = settings.groq_base_url

    logger.debug("Creating ChatGroq model=%s temperature=%s", kwargs["model"], kwargs["temperature"])
    return ChatGroq(**kwargs)


def structured_llm(
    schema: type[SchemaT],
    temperature: float | None = None,
    model: str | None = None,
) -> Runnable[Any, SchemaT]:
    """Return a runnable that answers with a validated instance of `schema`."""
    base = chat_llm(temperature=temperature, model=model)
    structured = base.with_structured_output(schema)
    with_retry = structured.with_retry(
        retry_if_exception_type=_RETRYABLE,
        stop_after_attempt=_MAX_ATTEMPTS,
        wait_exponential_jitter=True,
    )
    return _with_tool_use_recovery(with_retry, schema)


# ---------------------------------------------------------------------------
# Groq `tool_use_failed` recovery
# ---------------------------------------------------------------------------


def _recover_from_tool_use_failed(error: BaseException, schema: type[SchemaT]) -> SchemaT | None:
    """Pull a valid `schema` instance out of a Groq `tool_use_failed` error.

    Returns None when the error is not a recoverable `tool_use_failed`, in which
    case the caller must re-raise.
    """
    if GroqBadRequestError is None or not isinstance(error, GroqBadRequestError):
        return None

    body = getattr(error, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    if not isinstance(err, dict) or err.get("code") != "tool_use_failed":
        return None

    failed_generation = err.get("failed_generation")
    if not isinstance(failed_generation, str):
        return None

    try:
        arguments = json.loads(failed_generation).get("arguments")
        return schema.model_validate(arguments)
    except (ValueError, TypeError, AttributeError, ValidationError):
        return None


def tool_use_failed(error: BaseException) -> bool:
    """Whether this is Groq refusing a turn because the model wrote prose, not a call.

    Public because one caller wants to know rather than to recover: the
    answer-memory sweep asks a yes/no question whose empty answer is the common
    one, and a model that replies with a bare `[]` instead of calling the tool
    has said "none of them" in the one way the API will not accept.
    """
    if GroqBadRequestError is None or not isinstance(error, GroqBadRequestError):
        return False
    body = getattr(error, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    return isinstance(err, dict) and err.get("code") == "tool_use_failed"


def _with_tool_use_recovery(inner: Runnable, schema: type[SchemaT]) -> Runnable[Any, SchemaT]:
    """Wrap `inner` so a recoverable Groq tool-naming failure yields a result."""

    def _handle(error: BaseException) -> SchemaT:
        recovered = _recover_from_tool_use_failed(error, schema)
        if recovered is None:
            raise error
        logger.warning("Recovered %s from a Groq tool_use_failed response", schema.__name__)
        return recovered

    def _invoke(payload: Any, config: RunnableConfig | None = None) -> SchemaT:
        try:
            return inner.invoke(payload, config=config)
        except Exception as exc:  # noqa: BLE001 - re-raised by _handle when unrecoverable
            return _handle(exc)

    async def _ainvoke(payload: Any, config: RunnableConfig | None = None) -> SchemaT:
        try:
            return await inner.ainvoke(payload, config=config)
        except Exception as exc:  # noqa: BLE001 - re-raised by _handle when unrecoverable
            return _handle(exc)

    return RunnableLambda(_invoke, afunc=_ainvoke, name=f"Structured[{schema.__name__}]")
