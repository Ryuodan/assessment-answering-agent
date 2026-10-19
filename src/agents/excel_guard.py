"""Holding the Excel agent to its job: a reading for every sheet it was asked about.

The agent's loop ends the moment the model replies without calling a tool. So
a model that looks at a sheet and then describes it in prose, instead of
calling `record`, ends its round with the sheet unread -- no error, no "stopped
early", just a sheet that comes back empty. That happened twice in three opens
of the same two-question workbook (TD-043), and the second round, started
fresh, failed the same way both times.

Before every model call the guard asks which sheets still have no reading --
afresh, because `record` writes the reading outside the conversation:

* none: the round ends there, without asking the model, which also saves the
  call that would only have said "done";
* some: the model is asked with `tool_choice="any"` (Groq's "required"), and
  its reply is checked as well, because Groq does not hold every model to
  that. For gpt-oss a prose reply is reported to come back as if nothing were
  wrong; for others it is a 400 `tool_use_failed`. Either one is asked again,
  once, naming the sheets still to record. If that too calls no tool, the
  round ends as an ordinary ending, not as "stopped early", so the agent's
  second round is still asked about whatever is missing.

All of it happens inside the model call. A `before_model` hook would be a graph
node of its own: a third step in every model-and-tool cycle, against a step
budget sized for two, and an eighteen-sheet workbook recorded 13 sheets of 18
before it ran out.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import AIMessage, HumanMessage

from src.llm import tool_use_failed
from src.logs import get_logger

logger = get_logger(__name__)

FINISHED = "Every sheet is recorded."
"""What a round ends on once nothing is missing, in place of a model call."""

NO_TOOL_CALLED = "No tool was called, twice; this round ends here."
"""What a round ends on when the provider refused the reminder's reply too."""


def until_recorded(missing: Callable[[], set[str]]) -> list[AgentMiddleware[Any, Any]]:
    """Middleware holding the agent to recording every sheet `missing()` names."""

    @wrap_model_call
    def must_record(
        request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        left = missing()
        if not left:
            return ModelResponse(result=[AIMessage(content=FINISHED)])

        forced = request.override(tool_choice="any")
        first = _ask(handler, forced)
        if first is not None and _calls_a_tool(first):
            return first

        # Kept in the conversation, the prose reply and the reminder both: the
        # model sees what it was asked again and why, and the run counts what
        # the prose reply cost.
        said: list[Any] = [*(first.result if first is not None else []), HumanMessage(content=_reminder(left))]
        logger.info("excel_agent.reminded", sheets=len(left), refused=first is None)
        second = _ask(handler, forced.override(messages=[*forced.messages, *said]))
        if second is None or not _calls_a_tool(second):
            logger.warning("excel_agent.round_ended_unrecorded", sheets=len(left), refused=second is None)
        if second is None:
            return ModelResponse(result=[*said, AIMessage(content=NO_TOOL_CALLED)])
        return ModelResponse(result=[*said, *second.result], structured_response=second.structured_response)

    return [must_record]


def _ask(
    handler: Callable[[ModelRequest[Any]], ModelResponse[Any]], request: ModelRequest[Any]
) -> ModelResponse[Any] | None:
    """The model's reply, or None when the provider refused it for calling no tool."""
    try:
        return handler(request)
    except Exception as failed:
        if tool_use_failed(failed):
            return None
        raise


def _calls_a_tool(response: ModelResponse[Any]) -> bool:
    return any(isinstance(message, AIMessage) and message.tool_calls for message in response.result)


def _reminder(left: set[str]) -> str:
    named = ", ".join(sorted(repr(name) for name in left))
    return (
        f"Your reply called no tool, and these sheets still have no reading: {named}. "
        "Call `record` for each of them -- `look_at` a sheet first if you have not yet."
    )
