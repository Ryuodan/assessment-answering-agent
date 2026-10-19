"""Holding the Excel agent to its job: a reading for every sheet it was asked about.

The agent's loop ends the moment the model replies without calling a tool. So
a model that looks at a sheet and then describes it in prose, instead of
calling `record`, ends its round with the sheet unread -- no error, no "stopped
early", just a sheet that comes back empty. That happened twice in three opens
of the same two-question workbook (TD-043), and the second round, started
fresh, failed the same way both times.

Two rules hold while a round runs:

* while a sheet it was asked about has no reading, the model must call a tool
  (`tool_choice="any"`, which Groq calls "required");
* once every one has a reading, the loop ends before the model is asked again,
  which also saves the call that would only have said "done".

Whether a sheet is still missing is asked afresh before every model call,
because `record` writes the reading outside the conversation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    Runtime,
    before_model,
    wrap_model_call,
)


def until_recorded(missing: Callable[[], set[str]]) -> list[AgentMiddleware[Any, Any]]:
    """Middleware keeping the agent calling tools while `missing()` names a sheet."""

    @wrap_model_call
    def must_call_a_tool(
        request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(request.override(tool_choice="any") if missing() else request)

    @before_model(can_jump_to=["end"])
    def stop_once_recorded(state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        return None if missing() else {"jump_to": "end"}

    return [must_call_a_tool, stop_once_recorded]
