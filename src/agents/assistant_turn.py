"""What one assistant turn may do (plan 027, TD-043).

Beside `src/agents/assistant.py`, which re-exports `tidy_reply`, `without_repetition`,
`CORRECTION`, `UI_KEY` and `CARRY_ON` from here. Whether a reply's quotations hold
is `src/agents/assistant_quotes.py`; what a turn that stopped says is
`src/agents/assistant_stopped.py`. Each rule is a turn that went wrong:

* A turn looks in the documents at most three times, a search or a direct
  answer counting once each, and reads each clause whole. Shown 400 characters
  of each, the model never saw the sentence that answered it, and searched
  nineteen times in quoted phrases until the turn ran out of steps. A step
  asking for more than that has the rest refused, and is answered; a model
  that asks again after it has seen a refusal ends the turn.
* Its sources are listed once: those searches listed 114 clauses, 14 distinct.
* A knowledge-base document is not opened as a questionnaire, and the model is
  told why, rather than to have the person attach it.
* A call to a tool that does not exist is carried on from, not fatal.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src import service
from src.identity import User
from src.logs import get_logger

logger = get_logger(__name__)

SEARCHES_PER_TURN = 3
"""Searches one turn may make, a direct answer counting as one. One usually settles a question; the third is the last."""

CLAUSE_CHARS = 1500
"""How much of each clause a search shows the model: all of one, at the chunk size of 1,200."""

FOR_THIS_PRODUCT = "FOR THIS PRODUCT"
"""The mark on a product's own clauses, as the drafter's sources carry it (TD-040)."""

CORRECTION = "correction"
"""Marks a note to the model about its last step. It is sent, never stored or shown."""

UI_KEY = "ui"
"""Where a turn's steps and sources ride on its reply message.

`additional_kwargs` is serialised with the message, so what the interface draws
under a reply is stored with the reply rather than beside it, and the two
cannot drift apart.
"""


def is_correction(message: BaseMessage) -> bool:
    return bool((getattr(message, "additional_kwargs", None) or {}).get(CORRECTION))


# --- looking in the documents ---------------------------------------------------------


def _normalised(query: str) -> str:
    return " ".join(re.sub(r"[\"'\u201c\u201d\u2018\u2019\u00ab\u00bb\u201e]", " ", query or "").casefold().split())


_AGAIN = {
    "found": "Already searched for that this turn; its clauses are above. Reply from them.",
    "nothing": "Already searched for that this turn, and it found nothing. Do not search for it again: say that "
    "the documents found do not state it.",
    "failed": "Already searched for that this turn, and the search failed. Do not try it again: tell the person "
    "the search failed.",
    "answer": "Already answered that this turn; the answer is above. It is on the person's screen as a card: do "
    "not restate it.",
}
_SPENT = {
    "search": "Not searched: this turn has already searched {n} times, which is the limit. Do not search again: "
    "asking again ends the turn. Reply now from the clauses those searches returned: quote the sentence that "
    "answers the question word for word and name its document. If none says it, say plainly that the documents "
    "found do not state it, and name the closest clause.",
    # Not "reply from the clauses": the model never writes an answer itself.
    "answer": "Not answered: this turn has already looked in the documents {n} times, which is the limit, so "
    "this question was not answered. Do not answer it yourself, and do not call answer_directly or "
    "search_policies again: asking again ends the turn. Tell the person it was not answered this turn, and that "
    "they can ask it again in their next message.",
}
_REFUSED = ("Already searched for that this turn", "Already answered that this turn", "Not searched:", "Not answered:")
"""How a refused search or direct answer begins, so that `spent` can count them."""


def refused(state: dict[str, Any], asked: str, *, kind: str = "search") -> str:
    """Why this search or direct answer is not run, or "" when it may be, counting it.

    Before anything is awaited, so calls asked for at once cannot all pass the
    limit together. `kind` is "search" or "answer": both search the documents,
    so they share the turn's budget. A failed search stays counted, so a search
    that keeps failing cannot be asked for until the turn runs out of steps.
    """
    made: list[dict[str, str]] = state.setdefault("searches", [])
    key = _normalised(asked)
    earlier = next((entry for entry in made if entry["kind"] == kind and entry["key"] == key), None)
    if earlier is not None:
        return _AGAIN["answer" if kind == "answer" else earlier["outcome"]]
    if len(made) >= SEARCHES_PER_TURN:
        return _SPENT[kind].format(n=len(made))
    made.append({"kind": kind, "key": key, "outcome": "found"})
    return ""


def searched(state: dict[str, Any], query: str, hits: list[dict[str, Any]] | None = None, failed: Any = None) -> str:
    """What one search returns to the model. Its outcome is kept, for a repeat and for a turn that stops.

    Neither a search that matched nothing nor one that failed says the query
    back: the model's own words in a tool result would pass for a document's.
    """
    key = _normalised(query)
    made: list[dict[str, str]] = state.get("searches") or []
    entry = next((e for e in made if e["kind"] == "search" and e["key"] == key), {})
    entry["outcome"] = "failed" if failed is not None else "found" if hits else "nothing"
    if failed is not None:
        return f"The search failed: {failed}"
    if not hits:
        return "Nothing in the indexed policies matched that search."
    add_sources(state, hits)
    return clauses(hits)


def spent(messages: Iterable[BaseMessage]) -> bool:
    """Whether this turn asked for a search or a direct answer again after it saw one refused.

    Refusals are counted by the model step that asked for them. One step that
    asks for more than the turn allows has the rest refused and is answered:
    the model reads what the others found, and can reply from it. A refusal in
    a later step is asking again after being told, and every step re-sends each
    clause found: the turn ends with what it did instead (`assistant_stopped`).
    """
    later_steps, refused_in = 0, set[int]()
    for message in reversed(list(messages)):
        if isinstance(message, HumanMessage) and not is_correction(message):
            break
        if isinstance(message, AIMessage) and message.tool_calls:
            later_steps += 1  # a step's results come after it, so they are met before it here
        elif isinstance(message, ToolMessage) and str(message.content).startswith(_REFUSED):
            refused_in.add(later_steps)
    return len(refused_in) >= 2


def ends_when_spent() -> Any:
    """The agent's middleware that ends a `spent` turn before the model is asked again."""
    from langchain.agents.middleware import before_model

    @before_model(can_jump_to=["end"])
    def refused_twice(agent_state: Any, runtime: Any) -> dict[str, Any] | None:
        if not spent(agent_state["messages"]):
            return None
        logger.info("assistant.turn_spent")
        return {"jump_to": "end"}

    return refused_twice


def clauses(hits: list[dict[str, Any]]) -> str:
    """Search hits as the model reads them: each clause whole, the product's own marked."""
    shown = []
    for hit in hits:
        where = str(hit.get("locator") or hit.get("source_name") or "")
        text = str(hit.get("snippet") or "").strip()
        if len(text) > CLAUSE_CHARS:
            text = text[:CLAUSE_CHARS].rsplit(" ", 1)[0] + " ..."
        shown.append(f"[{where}, {FOR_THIS_PRODUCT}] {text}" if hit.get("product_id") else f"[{where}] {text}")
    return "\n\n".join(shown)


def source_key(item: dict[str, Any]) -> tuple[str, ...]:
    """One clause, whichever search found it: its knowledge base, kind, document, chunk and entry.

    Not the locator, which three chunks of a fact sheet with no clause numbers share.
    """
    fields = ("product_id", "source_type", "source_name", "chunk", "entry_id")
    return tuple(str(getattr(item.get(name), "value", item.get(name, ""))) for name in fields)


def add_sources(state: dict[str, Any], items: Iterable[dict[str, Any]]) -> None:
    """Put clauses under the reply, each once however often it was found."""
    sources: list[dict[str, Any]] = state.setdefault("sources", [])
    seen = {source_key(source) for source in sources}
    for item in items:
        if source_key(item) not in seen:
            seen.add(source_key(item))
            sources.append(item)


# --- a knowledge-base document is not a questionnaire ---------------------------------


def nothing_attached(user: User, state: dict[str, Any], file_name: str) -> str:
    """What `open_questionnaire` says when no file came with the message.

    Told to "ask the person to attach the questionnaire" when it had tried to open a knowledge-base document,
    the model asked them to attach a document the knowledge base already held.
    """
    name = (file_name or "").strip()
    if name and _a_knowledge_base_document(user, state, name):
        return (
            f"Nothing was opened. {name!r} is a document in the knowledge base, not a questionnaire attached "
            "to this message, and open_questionnaire cannot read it. To tell the person what it says, quote "
            "the sentences search_policies returned from it, word for word, and name it. If they do not "
            "cover the question, say so. Do not ask them to attach it."
        )
    return (
        "Nothing was opened: no file is attached to this message. open_questionnaire reads only a "
        "questionnaire the person attaches. It cannot open a knowledge-base document or a file named in "
        "conversation. If they asked what a document says, answer from search_policies. If they meant to "
        "send a questionnaire, ask them to attach it."
    )


def _a_knowledge_base_document(user: User, state: dict[str, Any], name: str) -> bool:
    wanted = name.casefold()
    if any(str(source.get("source_name") or "").casefold() == wanted for source in state.get("sources") or []):
        return True
    try:  # the shared knowledge base, and the chat's product's
        listed = [service.knowledge_stats(user.team_id, product_id=p) for p in {"", state.get("product_id") or ""}]
    except Exception as failed:  # noqa: BLE001 - unknown, so the plain refusal; never a failed turn
        logger.warning("assistant.knowledge_unreadable", error=str(failed) or repr(failed))
        return False
    return any(str(source.get("name") or "").casefold() == wanted for stats in listed for source in stats["sources"])


# --- a call to a tool that is not there -----------------------------------------------

CARRY_ON = 2
"""How many times a turn carries on: after the model calls a tool that does not
exist, or, once, after its reply quoted what no source says."""


def invented_a_tool(failed: Exception) -> bool:
    """Whether the provider refused a call to a tool that was never offered.

    The model on Groq now and then calls `repo_browser.open_file` -- a tool from
    its own training, not from this request -- and Groq rejects the whole
    request. In the assistant evaluation that ended two turns, one of them a
    turn that had already answered four questions, and the next turn then
    reported the broken one instead of doing what was asked.
    """
    text = str(failed)
    return "tool_use_failed" in text or "not in request.tools" in text


def tool_correction(failed: Exception) -> HumanMessage:
    """A note that the last step called something that is not there.

    Carrying on with the same messages is not enough: the model runs at
    temperature 0, and in the evaluation it made the identical call again every
    time. Something in front of it has to be different.
    """
    named = re.search(r"call tool '([^']{1,80})'", str(failed))
    tool = f"`{named.group(1)}`" if named else "a tool"
    return HumanMessage(
        f"[Not from the person: your last step called {tool}, which does not exist here. "
        "Carry on with what they asked, using only the tools you have.]",
        additional_kwargs={CORRECTION: True},
    )


# --- the reply as a person should read it ---------------------------------------------

_JOINED = re.compile(r"(?<=[.!?\u061f])(?=[A-Z\u0600-\u06FF*\"'])")
_WORD = re.compile(r"[\w\u0600-\u06FF]+")


def without_repetition(text: str) -> str:
    """A reply once, when the model wrote it twice back to back.

    Seen on the real model three times in twenty turns of one conversation:
    "The background-check question has been set aside and will not be written
    to the file.The background-check question has been set aside and will be
    excluded from the final submission." -- one message, two phrasings of the
    same sentence, joined with no space, which is what two of the model's output
    channels concatenated look like. Only a join like that is considered, and
    only when the two halves are mostly the same words, so two different
    sentences that happen to lack a space are left alone. The later half is kept.

    Four in ten words shared is the bar: "…has been restored to the
    questionnaire.The background-check question (question 4) is now back in the
    questionnaire." shares 43%, and two unrelated sentences share almost none.
    """
    text = (text or "").strip()
    for match in _JOINED.finditer(text):
        head, tail = text[: match.start()].strip(), text[match.start() :].strip()
        first, second = set(_WORD.findall(head.casefold())), set(_WORD.findall(tail.casefold()))
        if len(first) < 4 or len(second) < 4:
            continue
        if len(first & second) / len(first | second) >= 0.4:
            return tail
    return text


_CITATION_MARK = re.compile(r"\s*\u3010[^\u3011]{0,120}\u3011")


def tidy_reply(text: str, earlier: list[str] | tuple[str, ...] = ()) -> str:
    """The reply as a person should read it.

    Three things the model adds that nobody should see, each found reading a
    long conversation turn by turn:

    * a copy of a previous reply appended to this one -- "The background-check
      question has been set aside…" followed, with no space, by the last turn's
      "No answers are currently flagged…";
    * the same reply written twice in two phrasings (see `without_repetition`);
    * a citation marker in the model's own format, "【search_policies result #2】",
      which points at nothing a person can open.
    """
    text = _CITATION_MARK.sub("", text or "").strip()
    for before in earlier:
        before = (before or "").strip()
        if len(before) >= 20 and before in text and text != before:
            text = text.replace(before, "", 1).strip()
    return without_repetition(text)
