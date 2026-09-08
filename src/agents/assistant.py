"""The assistant: one conversation, over everything the system can do.

Every operation it performs already existed and was already tested. `src.tools`
was written for this -- plain functions taking a user and returning data, no
request and no response -- so that when an agent arrived it would be choosing
between operations rather than being the only thing that knows how to perform
them. This module is that choosing, and almost nothing else.

Four rules shape it, and three of them are older than it is.

**It cannot write to a file without being told twice.** `fill` was always meant
to stop and show what would change. So the assistant's fill tool *proposes*: it
reports what it would write, and the actual write happens when a person presses
the button in the answer panel. An agent that could quietly overwrite a
customer's spreadsheet would be a worse tool than the one it replaced.

**It cannot manage the knowledge base.** Indexing and removing policy documents
is deliberately not something to do by conversation -- it is the corpus every
answer is grounded in, and it belongs behind a panel with a list and a delete
button. The assistant can *search* it, which is a different thing.

**It cannot take feedback on an answer.** Feedback belongs on the answer card,
where the thing being judged is visible.

**It answers in the language it was addressed in.** These questionnaires arrive
in Arabic and in English, sometimes in the same file, and a person who writes
in Arabic is asking for an Arabic reply about questions that keep their own
language.

Compound instructions are the point. "Read this file, answer only the
governance questions, and keep every answer to one sentence" is three
operations and a scope, and getting from that sentence to
`answer(scope=Scope(part="governance"))` followed by `revise(...)` is the whole
job.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src import batches, conversations, events, tools
from src.config import settings
from src.conversations import Conversation
from src.identity import User
from src.llm import chat_llm

logger = logging.getLogger(__name__)

MAX_STEPS = 40
"""Graph steps for one turn.

A compound instruction is a handful of operations -- read, answer, revise,
report -- and each is a model turn plus a tool call. Forty leaves room for a
correction or two and stops a confused turn from running all afternoon.
"""

HISTORY_MESSAGES = 60
"""How much of the conversation is resent. Long enough to hold a morning's
work; short enough that a chat somebody has kept open for a week does not cost
more with every sentence."""


@dataclass
class Turn:
    """What one exchange with the assistant did."""

    reply: str = ""
    conversation_id: str = ""
    batch_id: str = ""
    steps: list[str] = field(default_factory=list)
    """Tool calls made, in order, so the interface can say what it did."""

    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    stopped_early: bool = False
    refreshed: bool = False
    """True when something changed that the answer panel should re-read."""


SYSTEM = """You are the assistant for a cybersecurity and privacy questionnaire
system. Companies send this organisation assessment questionnaires -- long
spreadsheets and Word forms asking about policies, access control, encryption,
incident response, data privacy -- and this system answers them from the
organisation's own approved policies.

You do the work by calling tools. You never write an answer yourself: answers
come from `answer_questions`, which retrieves the organisation's policies,
drafts, reviews and cites them. Anything you compose yourself would be
ungrounded, and an ungrounded answer in a questionnaire that goes to a bank is
the one thing this system exists to prevent.

WHAT YOU CAN DO

  open_questionnaire   read an uploaded file and find its questions
  describe_form        what is in the current questionnaire and how far it has got
  list_questions       the questions a scope selects, with their ids. Free
  answer_questions     answer some or all of them, from the policy corpus
  reword_answers       change how existing answers are worded, not what they say
  write_one_answer     replace one answer with words a person dictated
  set_aside            leave questions out, or bring them back in
  propose_fill         report what filling the file would write. It does NOT write
  search_policies      look something up in the organisation's own documents

CHOOSING A SCOPE

Most instructions name a subset rather than the whole file. Every tool that
acts on questions takes the same four narrowing arguments, and they combine:

  part             a sheet name, or the section a question sits under
  matching         ONE literal phrase, matched as a substring of the question
                   or its section, case-insensitively
  unanswered_only  skip questions that already have an answer
  ids              specific questions, when you have their ids

"Answer the governance ones" is `part="governance"`. "Anything about
encryption" is `matching="encryption"`. "Finish the rest" is
`unanswered_only=true`. "The unanswered ones under security operations" is
both. When you are unsure whether a word is a section name or a topic, use
`matching` -- it looks at the section too.

`matching` is **not a query language**. "training OR awareness" is matched
literally, as those nineteen characters, and selects nothing. Two topics are
two calls: `matching="training"`, then `matching="awareness"`. Prefer the
shortest word that distinguishes them -- "encrypt" catches "encryption" and
"encrypted" where "encryption" does not.

HOW TO WORK

* Compound instructions are normal. "Read this, answer the privacy questions,
  keep them short" is three calls. Make them all, in order, then report once.
* Call `describe_form` when you need to know what is in the file -- its sheets,
  its sections, how many are answered -- before choosing a scope. Do not guess
  at a sheet name.
* Call `list_questions` when you need a question id, or when you are not sure a
  scope selects what you meant. It is free and instant, and answering the wrong
  set is neither. Anything that needs an id -- `set_aside`, `write_one_answer`
  -- starts here: ids are the file's own, like `Human Resources!4`, and cannot
  be guessed.
* Answering is slow and costs money. Never answer a question twice: use
  `unanswered_only` when somebody says "the rest" or "finish it".
* Rewording is not answering again. "Make them shorter", "more formal", "in
  Arabic" are `reword_answers`. Only use `answer_questions` for questions with
  no answer yet.
* A wording instruction given at the same time as an answering one is two
  calls, in that order. "Answer the privacy questions and keep each to one
  sentence" is `answer_questions(part="privacy")` and then
  `reword_answers("keep each to one sentence", part="privacy")` over the same
  scope.
  `answer_questions` **ignores wording completely**. It takes no wording
  argument and there is no way to give it one: answering has a single fixed
  prompt on purpose, because a drafter told to be brief cites fewer sources
  and drops the caveats the evidence required. So an instruction about length,
  tone or language is still outstanding after `answer_questions` returns, no
  matter how the answers happen to have come out. It is done when
  `reword_answers` has run, and not before.
* You cannot fill a file. `propose_fill` reports what would be written and the
  person presses the button. Say so plainly rather than claiming you have done
  it.
* You cannot add, remove or re-index policy documents, and you cannot record
  feedback on an answer. Both are done in the interface. If asked, say where.
* If a tool refuses, say what it said. Do not try the same call again.

HOW TO REPLY

Briefly, and about what happened. "Answered 14 of the 23 governance questions;
9 already had answers. 3 are flagged for review." Not a description of your
plan, not a list of the tools you called, and never a table of the answers --
the answers are on screen beside you in their own cards, with their sources.

Report only what a tool actually reported. Never say something was done
because you meant to do it or because it looks as though it worked out: if you
did not call `reword_answers`, you did not reword anything, whatever the
answers happen to read like. A person acting on a claim that is not true is
worse off than one told the work is unfinished.

Reply in the language you were addressed in. If somebody writes to you in
Arabic, answer in Arabic. The questions in a file keep their own language
whatever you are writing in, and that is handled for you."""


def _tools(user: User, state: dict) -> list:
    """Everything the assistant can do, bound to one person and one conversation.

    `state` carries the current questionnaire between calls within a turn and
    records what changed, so the interface knows whether to re-read the answers.
    """

    def _log(step: str) -> None:
        state["steps"].append(step)

    def _batch_id() -> str:
        return state.get("batch_id") or ""

    def _scope(part: str, matching: str, unanswered_only: bool, ids: str) -> tools.Scope:
        chosen = tuple(
            piece.strip() for piece in (ids or "").replace(";", ",").split(",") if piece.strip()
        )
        return tools.Scope(
            ids=chosen,
            part=(part or "").strip(),
            matching=(matching or "").strip(),
            unanswered_only=bool(unanswered_only),
        )

    def open_questionnaire(file_name: str = "") -> str:
        """Read the questionnaire that was just uploaded, and report what is in it.

        Args:
            file_name: the file to open. Leave empty for the one most recently
                uploaded to this conversation, which is almost always right.
        """
        _log(f"open_questionnaire({file_name!r})")
        path = state.get("pending_upload")
        if not path:
            return ("No file has been uploaded to this conversation. Ask the person to "
                    "attach the questionnaire to their message.")
        try:
            batch = tools.open_form(user, Path(path))
        except Exception as failed:
            return f"That file could not be read: {failed}"

        state["batch_id"] = batch.id
        state["pending_upload"] = ""
        state["refreshed"] = True
        return _describe(batch.id)

    def describe_form() -> str:
        """What is in the current questionnaire: its sheets, sections and progress.

        Call this before choosing a scope, rather than guessing a sheet name.
        """
        _log("describe_form")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        return _describe(_batch_id())

    def _describe(batch_id: str) -> str:
        report = tools.inspect(user, batch_id)
        counts = report["counts"]
        # "still blank" is spelled out rather than left as a subtraction. Asked
        # in Arabic how many were left, the assistant read "1 answered" off a
        # four-question file and replied "one remaining" -- the arithmetic was
        # the only thing between it and a right answer, so it should not have
        # had to do it.
        blank = counts["questions"] - counts["answered"]
        lines = [
            f"{report['source_name']}: {counts['questions']} question(s) in total — "
            f"{counts['answered']} answered, {blank} still blank, "
            f"{counts['needs_review']} flagged for review."
        ]
        parts = [p for p in report["parts"] if p["used"]]
        if parts:
            lines.append("Sheets: " + ", ".join(f"{p['name']} ({p['questions']})" for p in parts))
        skipped = [p for p in report["parts"] if not p["used"]]
        if skipped:
            lines.append("Not used: " + ", ".join(f"{p['name']} ({p['kind']})" for p in skipped))

        # Sections are how people actually name a subset -- "the governance
        # ones" -- so they matter more here than any other part of the report.
        sections: dict[str, int] = {}
        for question in report["questions"]:
            name = (question.get("section") or "").strip()
            if name:
                sections[name] = sections.get(name, 0) + 1
        if sections:
            lines.append("Sections: " + ", ".join(f"{k} ({v})" for k, v in sections.items()))
        unsure = [
            f["because"] for p in report["parts"] for f in p["findings"] if not f["confident"]
        ]
        if unsure:
            lines.append(f"{len(unsure)} reading(s) marked worth checking.")
        return "\n".join(lines)

    def list_questions(
        part: str = "", matching: str = "", unanswered_only: bool = False, limit: int = 40
    ) -> str:
        """List the questions a scope selects, with their ids. Free and instant.

        Use it before answering when you are unsure a scope selects what you
        mean, and whenever you need a question id.

        Args:
            part: a sheet name, or the section the questions sit under.
            matching: one literal phrase, matched as a substring.
            unanswered_only: only questions with no answer yet.
            limit: how many to show.
        """
        scope = _scope(part, matching, unanswered_only, "")
        _log(f"list_questions({scope.describe()})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."

        # `inspect` returns every question with the selected ones flagged --
        # the interface needs the whole list to draw. Reading `selected` rather
        # than assuming a filtered list is what makes this agree with
        # `answer_questions`, which is the entire point of being able to look
        # before spending money.
        report = tools.inspect(user, _batch_id(), scope)
        chosen = [question for question in report["questions"] if question["selected"]]
        if not chosen:
            return (f"Nothing matched {scope.describe()}. `matching` is a literal substring, "
                    "not a query -- try one plain word, or call describe_form for the "
                    "sheets and sections this file actually has.")
        shown = chosen[: max(1, min(int(limit or 40), 100))]
        lines = [f"{len(chosen)} question(s) matched {scope.describe()}:"]
        for question in shown:
            mark = "answered" if question.get("answer") else "blank   "
            if question.get("skip"):
                mark = "set aside"
            lines.append(f"  {question['id']}  [{mark}]  {question['text'][:110]}")
        if len(chosen) > len(shown):
            lines.append(f"  ... and {len(chosen) - len(shown)} more")
        return "\n".join(lines)

    async def answer_questions(
        part: str = "", matching: str = "", unanswered_only: bool = False, ids: str = ""
    ) -> str:
        """Answer questions from the organisation's policies. Slow and not free.

        Args:
            part: a sheet name, or the section the questions sit under.
            matching: free text matched against the question and its section.
            unanswered_only: skip questions that already have an answer.
            ids: specific question ids, comma separated.
        """
        scope = _scope(part, matching, unanswered_only, ids)
        _log(f"answer_questions({scope.describe()})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        try:
            outcome = await tools.answer(user, _batch_id(), scope)
        except tools.ToolError as refused:
            return str(refused)
        state["refreshed"] = True
        if outcome.nothing_matched:
            return (f"Nothing matched {scope.describe()}. Call describe_form to see what "
                    "sheets and sections this file actually has.")
        return (f"Answered {outcome.answered} of {outcome.attempted} ({scope.describe()}). "
                f"{outcome.failed} failed, {outcome.needs_review} flagged for review.")

    async def reword_answers(
        instruction: str, part: str = "", matching: str = "",
        unanswered_only: bool = False, ids: str = "",
    ) -> str:
        """Change how existing answers are worded, keeping what they say.

        Args:
            instruction: how they should change -- "keep each to one sentence",
                "more formal", "in Arabic".
            part: a sheet name, or the section the questions sit under.
            matching: free text matched against the question and its section.
            unanswered_only: ignored here; rewording needs an existing answer.
            ids: specific question ids, comma separated.
        """
        scope = _scope(part, matching, False, ids)
        _log(f"reword_answers({instruction!r}, {scope.describe()})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        try:
            outcome = await tools.revise(user, _batch_id(), instruction, scope)
        except tools.ToolError as refused:
            return str(refused)
        state["refreshed"] = True
        if outcome.nothing_matched:
            return (f"No answered questions matched {scope.describe()}, so there was "
                    "nothing to reword. Rewording a blank question is answering it.")
        return f"Reworded {outcome.answered} of {outcome.attempted} ({scope.describe()})."

    def write_one_answer(question_id: str, text: str) -> str:
        """Replace one answer with words a person dictated.

        Args:
            question_id: the id from describe_form or an answer card.
            text: exactly what they said to put there.
        """
        _log(f"write_one_answer({question_id!r})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        try:
            tools.set_answer(user, _batch_id(), question_id, text)
        except tools.ToolError as refused:
            return str(refused)
        state["refreshed"] = True
        return f"Replaced the answer to {question_id} with the words given."

    def set_aside(question_ids: str, include: bool = False) -> str:
        """Leave questions out of the file, or bring them back in.

        Args:
            question_ids: ids to set aside, comma separated.
            include: true to bring them back rather than set them aside.
        """
        _log(f"set_aside({question_ids!r}, include={include})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        chosen = [piece.strip() for piece in question_ids.replace(";", ",").split(",") if piece.strip()]
        if not chosen:
            return "Name the questions to set aside."
        try:
            tools.set_questions(
                user, _batch_id(), [{"id": qid, "skip": not include} for qid in chosen]
            )
        except tools.ToolError as refused:
            return str(refused)
        state["refreshed"] = True
        verb = "brought back" if include else "set aside"
        return f"{len(chosen)} question(s) {verb}. Set-aside questions are never written to the file."

    def propose_fill() -> str:
        """Report what filling the questionnaire would write. Writes nothing.

        The person presses the button to actually write the file.
        """
        _log("propose_fill")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        report = tools.inspect(user, _batch_id())
        counts = report["counts"]
        writable = sum(
            1 for question in report["questions"]
            for target in question.get("targets", [])
            if target.get("role") in ("answer", "status")
        )
        if not counts["answered"]:
            return "Nothing is answered yet, so filling the file would write nothing."
        state["offer_fill"] = True
        return (
            f"Ready to fill {report['source_name']}: {counts['answered']} answered question(s) "
            f"across about {writable} cell(s). Evidence columns are left blank unless asked for, "
            f"and set-aside questions are not written. I have not written anything -- the "
            f"'Fill the original file' button beside the answers does that."
        )

    async def search_policies(query: str) -> str:
        """Look something up in the organisation's own policy documents.

        Args:
            query: what to look for.
        """
        _log(f"search_policies({query!r})")
        try:
            found = await tools.search(query)
        except Exception as failed:
            return f"The search failed: {failed}"
        hits = found.get("results", [])[:5]
        if not hits:
            return f"Nothing in the indexed policies matched {query!r}."
        return "\n\n".join(
            f"[{hit.get('locator') or hit.get('source_name')}] {(hit.get('snippet') or '')[:400]}"
            for hit in hits
        )

    return [
        open_questionnaire, describe_form, list_questions, answer_questions,
        reword_answers, write_one_answer, set_aside, propose_fill, search_policies,
    ]


def _agent(tool_list: list):
    from langchain.agents import create_agent
    from langchain.agents.middleware import ClearToolUsesEdit, ContextEditingMiddleware

    return create_agent(
        chat_llm(temperature=0.0),
        tools=tool_list,
        system_prompt=SYSTEM,
        middleware=[ContextEditingMiddleware(
            edits=[ClearToolUsesEdit(trigger=40_000, keep=6)],
        )],
    )


def _account(state: dict, turn: Turn) -> None:
    for message in (state or {}).get("messages", []):
        usage = getattr(message, "usage_metadata", None) or {}
        if usage:
            turn.input_tokens += usage.get("input_tokens", 0) or 0
            turn.output_tokens += usage.get("output_tokens", 0) or 0


def _reply_from(state: dict) -> str:
    """The last thing the assistant actually said, as opposed to did."""
    for message in reversed((state or {}).get("messages", [])):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, list):  # some providers return content blocks
                content = "".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                )
            if str(content).strip():
                return str(content).strip()
    return ""


async def say(
    user: User,
    conversation: Conversation,
    message: str,
    *,
    upload: Path | None = None,
) -> Turn:
    """One exchange. Runs the tools, saves the conversation, returns what happened.

    The conversation is saved even when the turn fails part way through: the
    tools it did call have already changed the batch, and a history that does
    not mention them would leave the assistant contradicting the answer panel
    beside it.
    """
    started = time.monotonic()
    turn = Turn(conversation_id=conversation.id, batch_id=conversation.batch_id)

    state: dict = {
        "batch_id": conversation.batch_id,
        "pending_upload": str(upload) if upload else "",
        "steps": turn.steps,
        "refreshed": False,
        "offer_fill": False,
    }
    if upload:
        message = (
            f"{message}\n\n[A file has been uploaded to this conversation: {upload.name}. "
            "Call open_questionnaire to read it.]"
        ).strip()

    history = list(conversation.messages)[-HISTORY_MESSAGES:] + [HumanMessage(message)]
    final: dict = {}
    try:
        async for chunk in _agent(_tools(user, state)).astream(
            {"messages": history}, {"recursion_limit": MAX_STEPS}, stream_mode="values",
        ):
            final = chunk
    except Exception as failed:
        logger.warning("The assistant stopped early: %s", failed)
        turn.stopped_early = True

    _account(final, turn)
    turn.reply = _reply_from(final) or (
        "I ran out of room part way through that. What I did finish is in the answers beside this."
        if turn.stopped_early
        else "I could not work out what to do with that. Could you say it another way?"
    )
    turn.batch_id = state.get("batch_id", "")
    turn.refreshed = bool(state.get("refreshed"))

    conversation.messages = _keep(final, history, turn.reply)
    conversation.batch_id = turn.batch_id
    if not conversation.title:
        conversation.title = conversations.title_from(message)
    conversations.save(conversation)

    events.record(
        user, events.ASSISTANT_TURN, subject_type=conversations.SUBJECT,
        subject_id=conversation.id, steps=len(turn.steps), batch_id=turn.batch_id,
        tokens=turn.input_tokens + turn.output_tokens,
    )
    turn.seconds = time.monotonic() - started
    return turn


def _keep(final: dict, history: list[BaseMessage], reply: str) -> list[BaseMessage]:
    """The conversation to store after a turn.

    Taken from the agent's own final state where there is one, so tool calls
    and their results are kept and a follow-up can refer to them. A turn that
    failed before the graph produced anything falls back to the history plus
    whatever was said, so the person's message is never silently dropped.
    """
    messages = list((final or {}).get("messages", []))
    if messages:
        return messages
    return history + [AIMessage(reply)]


def start(user: User, message: str = "") -> Conversation:
    """A new conversation, titled from what was first asked of it."""
    conversation = conversations.create(user, message)
    events.record(
        user, events.ASSISTANT_STARTED, subject_type=conversations.SUBJECT,
        subject_id=conversation.id,
    )
    return conversation


def answers_for(user: User, conversation: Conversation) -> dict | None:
    """The answer cards to draw beside the chat, or None if no file is open.

    The same payload the other interface renders, deliberately: the cards, the
    sources and the reviewer's reasoning are the thing worth looking at, and
    two renderings of it would drift.
    """
    if not conversation.batch_id:
        return None
    batch = batches.load(conversation.batch_id, team_id=user.team_id)
    if batch is None:
        return None
    return tools.inspect(user, conversation.batch_id)


def configured() -> bool:
    """Whether the assistant can run at all."""
    return bool(settings.groq_api_key)
