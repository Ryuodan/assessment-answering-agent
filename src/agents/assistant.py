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
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src import batches, conversations, events, preferences, products, progress, rewrite, service, store, tools
from src.config import settings
from src.conversations import Conversation
from src.extraction import detect_question_language
from src.formatting import without_reasoning
from src.identity import User
from src.llm import chat_llm
from src.models import Question
from src.agents import assistant_turn
from src.agents.assistant_prompt import FOR_PRODUCT, IN_ARABIC as IN_ARABIC, SYSTEM as SYSTEM
from src.agents.assistant_turn import CORRECTION as CORRECTION, UI_KEY as UI_KEY, is_correction as _is_correction
from src.agents.assistant_turn import tidy_reply as tidy_reply, without_repetition as without_repetition

logger = logging.getLogger(__name__)

MAX_STEPS = 40
"""Graph steps for one turn.

A compound instruction is a handful of operations -- read, answer, revise,
report -- and each is a model turn plus a tool call. Forty leaves room for a
correction or two and stops a confused turn from running all afternoon.
"""

SOURCES_SHOWN = 6
"""Search hits kept per query -- shown to the model, and drawn under the reply."""

SOURCE_CHARS = 700
"""How much of each cited clause is read back when somebody asks what an answer
was based on. Enough to quote the sentence that matters; a whole chunk for every
source of five answers would crowd out the conversation."""

DOING = {
    "open_questionnaire": "Reading the file…",
    "describe_form": "Looking at what is in it…",
    "list_questions": "Working out which questions that means…",
    "read_existing": "Reading what the file already says…",
    "answer_questions": "Answering…",
    "reword_answers": "Rewording…",
    "write_one_answer": "Writing that answer in…",
    "set_aside": "Setting those aside…",
    "propose_fill": "Working out what would be written…",
    "search_policies": "Searching the policies…",
    "answer_directly": "Drafting an answer…",
    "list_skills": "Looking at your skills…",
    "read_answers": "Reading the answers…",
    "put_back_drafts": "Putting the drafts back…",
    "apply_skill": "Rewording with your skill…",
}
"""What to show a person while each tool runs.

Written for someone waiting, not for a log: what is happening now, in words
they would use. `answer_questions` and `reword_answers` say the least here
because they immediately replace themselves with a counted bar, which says
more.
"""

DIRECT_QUESTIONS = 5
"""How many questions `answer_directly` will take at once.

Answering is the expensive operation, and this path has no file behind it: no
cells, no fill, no answer cards, nothing to come back to. A handful asked in
passing is what it is for. Anything longer is a questionnaire, and a
questionnaire should be uploaded so the answers are kept."""

UPLOAD_NOTE = "[A file has been uploaded to this conversation:"
"""Told to the agent, never to the person.

It goes into the stored message because that history is what the agent
re-reads, and it has to know a file arrived. But it is not something anybody
said, so `spoken` takes it back out wherever a person reads their own words --
the conversation's title and the transcript both showed it otherwise, and a
history of "Read this file. [A file has been uploaded to this conversation:
HR…" is a list of plumbing rather than a list of what was asked.
"""


def spoken(text: str) -> str:
    """What the person actually typed, with the plumbing taken back out."""
    return text.split(UPLOAD_NOTE, 1)[0].strip()


def uploaded_name(message: BaseMessage) -> str:
    """The file a person's message came with, or "".

    Recorded on the message since timestamps were; read back out of the note
    for the messages stored before that.
    """
    stated = (getattr(message, "additional_kwargs", None) or {}).get("file")
    if stated:
        return str(stated)
    text = str(getattr(message, "content", "") or "")
    if UPLOAD_NOTE not in text:
        return ""
    rest = text.split(UPLOAD_NOTE, 1)[1].strip()
    return rest.split(". Call open_questionnaire", 1)[0].strip()


CHANGES_ANSWERS = frozenset(
    {
        "answer_questions",
        "reword_answers",
        "apply_skill",
        "write_one_answer",
        "set_aside",
    }
)
"""The tools whose use means the answer panel has something new to show."""


TURNS_REMEMBERED = 20
"""How many of a conversation's turns the model is shown.

Turns, not messages. The limit used to be sixty messages, and a turn is a
person's message, a handful of tool calls, their results and a reply -- so it
was eight or ten turns, and worse, a count of messages can cut a turn in half:
a tool result arriving without the call that produced it is a request the model
API refuses, and from then on every turn in that conversation failed.
"""

TURNS_IN_FULL = 3
"""The most recent turns shown with their tool calls and results. Older ones are
shown as what was asked and what was said: the ids in a three-hour-old question
list are stale anyway and cost more than listing again, and the thread of the
conversation -- which file, what was decided -- is all in the words."""


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

    sources: list = field(default_factory=list)
    """Policy clauses looked up during the turn, for the interface to draw
    under the reply. A claim about what the policies say is worth what the
    clause behind it is worth."""


def _tools(user: User, state: dict) -> list:
    """Everything the assistant can do, bound to one person and one conversation.

    `state` carries the current questionnaire between calls within a turn and
    records what changed, so the interface knows whether to re-read the answers.
    """

    def _log(step: str) -> None:
        state["steps"].append(step)
        # And say it out loud, for whoever is watching the turn happen. The
        # steps are the record afterwards; this is the only thing a person has
        # while it runs, and "Working" for ninety seconds is indistinguishable
        # from a page that has frozen.
        progress.note(state.get("run_id"), DOING.get(step.split("(", 1)[0], "Working…"))

    def _batch_id() -> str:
        return state.get("batch_id") or ""

    def _scope(
        part: str,
        matching: str,
        unanswered_only: bool,
        ids: str,
        position: str = "",
    ) -> tools.Scope:
        chosen = tuple(piece.strip() for piece in (ids or "").replace(";", ",").split(",") if piece.strip())
        if (position or "").strip():
            # "Question 3" is the third question in the file. The 3 inside an id
            # like `Human Resources!3` is a spreadsheet row, and taking one for
            # the other reworded the training question when asked for the one
            # after it. A place that is not in the file selects nothing rather
            # than everything: an empty id list means "no restriction".
            batch = batches.load(_batch_id(), team_id=user.team_id, actor_email=user.email) if _batch_id() else None
            order = [q.id for q in batch.form.questions] if batch else []
            placed = tuple(order[place - 1] for place in _positions(position, len(order)))
            chosen = tuple(dict.fromkeys(chosen + placed)) or ("(no question at that place)",)
        return tools.Scope(
            ids=chosen,
            part=(part or "").strip(),
            matching=(matching or "").strip(),
            unanswered_only=bool(unanswered_only),
        )

    def open_questionnaire(file_name: str = "") -> str:
        """Read the questionnaire attached to this message, and report what is in it.

        Only a file the person attached. It cannot open a knowledge-base
        document: what one of those says comes from `search_policies`.

        Args:
            file_name: the file to open. Leave empty for the one most recently
                uploaded to this conversation, which is almost always right.
        """
        _log(f"open_questionnaire({file_name!r})")
        path = state.get("pending_upload")
        if not path:
            return assistant_turn.nothing_attached(user, state, file_name)
        try:
            batch = tools.open_form(user, Path(path), product_id=state.get("product_id", ""))
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
        blank = counts["still_blank"]
        lines = [
            f"{report['source_name']}: {counts['questions']} question(s) in total — "
            f"{counts['answered']} answered here, {blank} still blank, "
            f"{counts['needs_review']} flagged for review."
        ]
        if counts.get("set_aside"):
            lines.append(f"{counts['set_aside']} question(s) are set aside and will not be written.")
        # A file that arrives already filled in is a normal thing to be handed:
        # last year's submission, or a colleague's half-finished draft. Saying
        # it has no answers because we did not write them is simply wrong.
        if counts.get("already_in_file"):
            lines.append(
                f"{counts['already_in_file']} question(s) arrived with an answer already "
                "written in the file, by the team that owns this questionnaire. Those "
                "are finished work and take precedence over anything drafted here; "
                "`read_existing` shows what they say. They will not be answered again."
            )
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
        unsure = [f["because"] for p in report["parts"] for f in p["findings"] if not f["confident"]]
        if unsure:
            lines.append(f"{len(unsure)} reading(s) marked worth checking.")
        return "\n".join(lines)

    def list_questions(part: str = "", matching: str = "", unanswered_only: bool = False, limit: int = 40) -> str:
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
            return (
                f"Nothing matched {scope.describe()}. `matching` is a literal substring, "
                "not a query -- try one plain word, or call describe_form for the "
                "sheets and sections this file actually has."
            )
        shown = chosen[: max(1, min(int(limit or 40), 100))]
        place = {question["id"]: index for index, question in enumerate(report["questions"], start=1)}
        lines = [
            f"{len(chosen)} question(s) matched {scope.describe()} "
            '(#n is a question\'s place in the file: "the second question" is #2):'
        ]
        for question in shown:
            # The id first, because it is what every other tool takes. The
            # place after it, because it is what a person says: "the second one".
            lines.append(
                f"  {question['id']}  [{_LIST_MARKS.get(_mark(question), _mark(question))}]  "
                f"#{place[question['id']]}  {question['text'][:110]}"
            )
        if len(chosen) > len(shown):
            lines.append(f"  ... and {len(chosen) - len(shown)} more")
        return "\n".join(lines)

    _LIST_MARKS = {"blank": "blank    ", "in file": "in file  ", "flagged": "flagged  ", "approved": "approved "}

    def _mark(question: dict) -> str:
        if question.get("skip"):
            return "set aside"
        if question.get("blanked"):
            return "left blank"
        if question.get("answer"):
            if question.get("approved"):
                return "approved"
            return "answered" if question.get("will_be_written") else "flagged"
        if question.get("existing"):
            return "in file"
        return "blank"

    def _positions(text: str, total: int) -> list[int]:
        """ "2", "2-5", "1,3", "last", "first" -> places in the file, counting from 1."""
        places: list[int] = []
        for piece in (text or "").replace(";", ",").split(","):
            piece = piece.strip().casefold()
            if not piece:
                continue
            if piece in ("last", "final"):
                places.append(total)
            elif piece == "first":
                places.append(1)
            elif "-" in piece:
                low, _, high = piece.partition("-")
                if low.strip().isdigit() and high.strip().isdigit():
                    places.extend(range(int(low), int(high) + 1))
            elif piece.isdigit():
                places.append(int(piece))
        return [place for place in dict.fromkeys(places) if 1 <= place <= total]

    def read_answers(
        question_ids: str = "",
        matching: str = "",
        position: str = "",
        only: str = "",
        limit: int = 5,
        with_sources: bool = False,
    ) -> str:
        """Read back the answers already written for questions. Free and instant.

        The answer text itself, with whether it is flagged and why, its
        confidence, and whether it will go into the file. For "what is the answer to question 2", "what did you write about
        encryption", "read me the flagged ones", "why is the third one flagged".
        Nothing is changed.

        With `with_sources=true`, also the sources it cites, what each one says,
        whether it is our own policy, a regulation or a previous answer, and the
        reasoning the answer was drafted with. For "what sources did you use for question 3",
        "which clause is that answer based on", "why does it say that", "is that
        from our policy or from a regulation". These are the sources that answer
        was written from; a fresh `search_policies` finds what matches now, which
        is a different list, so never search to answer this.

        Args:
            question_ids: specific question ids, comma separated.
            matching: one literal phrase, to find them by topic.
            position: by place in the file, counting from 1: "2" for the second
                question, "2-4" for a range, "last".
            only: "flagged" for answers held back from the file, "approved" for
                approved ones, "" for any.
            limit: how many to show.
            with_sources: include the text of every cited source, what kind of
                source it is, and the reasoning.
        """
        _log(
            f"read_answers({question_ids or position or matching or only or 'answers'!r}"
            + (", with sources" if with_sources else "")
            + ")"
        )
        if not _batch_id():
            return "No questionnaire is open in this conversation."

        report = tools.inspect(user, _batch_id(), _scope("", matching, False, question_ids))
        questions = report["questions"]
        if position.strip():
            wanted = _positions(position, len(questions))
            if not wanted:
                return f"This questionnaire has {len(questions)} questions; there is no question at {position!r}."
            chosen = [questions[place - 1] for place in wanted]
        else:
            chosen = [q for q in questions if q["selected"]] if (question_ids or matching) else list(questions)
        filtering = only.strip().casefold()
        written = [q for q in questions if q.get("answer")]
        if filtering == "flagged":
            chosen = [q for q in chosen if q.get("answer") and not q.get("skip") and not q.get("will_be_written")]
        elif filtering == "approved":
            chosen = [q for q in chosen if q.get("approved")]
        elif not (question_ids or matching or position):
            chosen = [q for q in chosen if q.get("answer") or q.get("existing")]
        if not chosen:
            # Facts, not "nothing matched". Told only that no flagged answer
            # matched, the assistant concluded aloud that every answer had been
            # approved -- which nobody had done.
            approved = sum(1 for q in written if q.get("approved"))
            if filtering == "flagged":
                return (
                    f"None of the {len(written)} answers is flagged: all of them would go into "
                    f"the file. {approved} of them have been approved by a person; approving "
                    "is done on each answer card, not here."
                )
            if filtering == "approved":
                return (
                    f"None of the {len(written)} answers has been approved by a person yet. "
                    "Approving is done on each answer card, not here."
                )
            return (
                f"No answers match that. {len(written)} of {len(questions)} questions have an "
                "answer; `list_questions` shows each one's state."
            )

        place = {question["id"]: index for index, question in enumerate(questions, start=1)}
        shown = chosen[: max(1, min(int(limit or 5), 5 if with_sources else 20))]
        lines = []
        for question in shown:
            lines.append(f"#{place[question['id']]}  {question['id']} -- {question['text']}")
            answered = question.get("answered") or {}
            if question.get("answer"):
                length = question.get("length") or "full"
                text = question.get("brief") if length == "brief" and question.get("brief") else question["answer"]
                lines.append(
                    f"    state: {_mark(question)}, confidence {round(100 * (answered.get('confidence') or 0))}%"
                    + (", written at brief length" if length == "brief" else "")
                )
                lines.append(f"    answer, to relay word for word: {text[:1800]}")
                if not question.get("will_be_written") and question.get("held_back_because"):
                    lines.append(f"    held back from the file because: {question['held_back_because'][:400]}")
                lines.extend(_sources_of(answered, detailed=with_sources))
            elif question.get("existing"):
                lines.append(f"    no answer written here; the file arrived saying: {question['existing'][:600]}")
            else:
                lines.append(f"    state: {_mark(question)} -- nothing has been written for it yet.")
        if len(chosen) > len(shown):
            lines.append(f"... and {len(chosen) - len(shown)} more; ask for them by position or id.")
        return "\n".join(lines)

    def _sources_of(answered: dict, *, detailed: bool) -> list[str]:
        """What one answer was written from, exactly as its card shows it.

        The citations are the answer's own list and the text beside each is the
        chunk the drafter was given, so "which sources did you use" is answered
        from the record rather than re-searched. Searching again returned a
        similar list, not the same one -- and a person comparing the reply with
        the card saw sources the answer never cited.
        """
        # Only when asked. A plain read-back is the answer and its state: with a
        # list of sources after it, an answer asked for in Arabic came back
        # translated rather than quoted more often -- two runs in three against
        # one in three without.
        if not detailed:
            return []
        cited = [c for c in (answered.get("citations") or []) if c]

        found: dict[str, dict] = {}
        for item in answered.get("evidence") or []:
            found.setdefault(item.get("locator") or item.get("source_name") or "", item)
        lines = [] if cited else ["    sources cited: none"]
        for citation in cited:
            item = found.get(citation)
            if item is None:
                lines.append(f"    cited: {citation} -- named in the answer; the text of it was not kept")
                continue
            kind = (
                "a previous answer of ours"
                if item.get("source_type") == "prior_answer"
                else "a law or external requirement, not our own policy"
                if item.get("authority") == "external"
                else "our own policy"
            )
            said = " ".join(str(item.get("snippet") or "").split())
            if len(said) > SOURCE_CHARS:
                said = said[:SOURCE_CHARS].rsplit(" ", 1)[0] + " ..."
            lines.append(f"    cited: {citation} ({kind})")
            lines.append(f"      it says: {said}")
        if (answered.get("rationale") or "").strip():
            lines.append(f"    reasoning when it was drafted: {answered['rationale'].strip()[:800]}")
        return lines

    def put_back_drafts(question_ids: str = "", matching: str = "", position: str = "") -> str:
        """Undo rewording: put answers back as they were first drafted.

        For "undo that", "put the original answers back", "that was better
        before" after a rewording, a skill or preferences changed the wording.
        Answers that were never reworded are left as they are.

        Args:
            question_ids: specific question ids, comma separated.
            matching: one literal phrase, to find them by topic.
            position: by place in the file, counting from 1.
        """
        _log(f"put_back_drafts({question_ids or position or matching or 'all'!r})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        report = tools.inspect(user, _batch_id(), _scope("", matching, False, question_ids))
        questions = report["questions"]
        if position.strip():
            chosen = [questions[place - 1] for place in _positions(position, len(questions))]
        elif question_ids or matching:
            chosen = [q for q in questions if q["selected"]]
        else:
            chosen = list(questions)
        reworded = [q for q in chosen if (q.get("answered") or {}).get("drafted")]
        if not reworded:
            return "None of those answers has been reworded since it was drafted, so nothing was put back."
        for question in reworded:
            tools.restore_draft(user, _batch_id(), question["id"])
        state["refreshed"] = True
        return f"Put {len(reworded)} answer(s) back as they were first drafted."

    def read_existing(question_ids: str = "", matching: str = "", limit: int = 20) -> str:
        """What questions already said when the file arrived. Free and instant.

        A questionnaire is often last year's submission, or the security
        team's own draft. Those words were written by the people who own the
        subject and are the authoritative answer to the question; quote them
        when asked what the file says, and do not replace them.

        Args:
            question_ids: specific questions, comma separated.
            matching: one literal phrase, to find them by topic instead.
            limit: how many to show.
        """
        _log(f"read_existing({question_ids!r}, {matching!r})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."

        scope = _scope("", matching, False, question_ids)
        report = tools.inspect(user, _batch_id(), scope)
        chosen = [question for question in report["questions"] if question["selected"] and question.get("existing")]
        if not chosen:
            return (
                "None of those arrived with an answer in the file. "
                "`list_questions` shows which ones did, marked 'in file'."
            )
        lines = []
        for question in chosen[: max(1, min(int(limit or 20), 50))]:
            lines.append(f"{question['id']} — {question['text'][:90]}")
            lines.append(f"    the file says: {question['existing'][:400]}")
        return "\n".join(lines)

    async def answer_questions(
        part: str = "",
        matching: str = "",
        unanswered_only: bool = False,
        ids: str = "",
        replace_existing: bool = False,
        position: str = "",
    ) -> str:
        """Answer questions from the organisation's policies. Slow and not free.

        Questions that already have an answer are skipped, not overwritten,
        unless `replace_existing` is set.

        Args:
            part: a sheet name, or the section the questions sit under.
            matching: free text matched against the question and its section.
            unanswered_only: narrow to questions with no answer yet.
            ids: specific question ids, comma separated.
            replace_existing: throw away answers that are already there and
                write new ones. Only when the person asked for those questions
                to be answered again.
            position: by place in the file, counting from 1: "3" for the third
                question, "2-4", "last". Use this when the person counts questions;
                the number inside an id is a spreadsheet row, not a place.
        """
        scope = _scope(part, matching, unanswered_only, ids, position)
        again = ", replacing what is there" if replace_existing else ""
        _log(f"answer_questions({scope.describe()}{again})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        try:
            outcome = await tools.answer(
                user,
                _batch_id(),
                scope,
                replace_existing=replace_existing,
                run_id=state.get("run_id") or "",
            )
        except tools.ToolError as refused:
            return str(refused)
        state["refreshed"] = True
        if outcome.nothing_matched:
            return (
                f"Nothing matched {scope.describe()}. Call describe_form to see what "
                "sheets and sections this file actually has."
            )
        # Said before the counts, because it is the part that changes what to
        # report: "answered 0 of 0" reads as a failure and is not one.
        kept = ""
        if outcome.protected:
            kept = (
                f"{outcome.protected} question(s) in that scope already had an answer "
                "and were left exactly as they were. "
            )
            if not outcome.attempted:
                return kept + "Nothing else there was blank, so nothing was answered."
        styled = f" {outcome.styled} were reworded to your preferences." if outcome.styled else ""
        # Said here, in the result, and not only in the prompt: this is the
        # moment the agent decides whether it is finished, and asked to "answer
        # everything and keep each to one sentence" it answered, then reported
        # every answer as one sentence without ever rewording one.
        reminder = (
            " Answering applies no wording instruction: if the person asked for a "
            "length, tone or language, that is still to do with reword_answers, and "
            "it is not done until that has run."
        )
        return (
            kept + f"Answered {outcome.answered} of {outcome.attempted} "
            f"({scope.describe()}). {outcome.failed} failed, "
            f"{outcome.needs_review} flagged for review.{styled}{reminder}"
        )

    async def reword_answers(
        instruction: str,
        part: str = "",
        matching: str = "",
        unanswered_only: bool = False,
        ids: str = "",
        include_written: bool = False,
        language: str = "",
        position: str = "",
    ) -> str:
        """Change how existing answers are worded, keeping what they say.

        Answers a person wrote are left as they are unless `include_written`.

        Args:
            instruction: how they should change -- "keep each to one sentence",
                "more formal", "in Arabic".
            part: a sheet name, or the section the questions sit under.
            matching: free text matched against the question and its section.
            unanswered_only: ignored here; rewording needs an existing answer.
            ids: specific question ids, comma separated.
            include_written: reword answers a person wrote too. Only when the
                person asked for exactly those to be reworded.
            language: "ar" or "en" only when they asked for the answers in a
                language -- "in Arabic", "translate them to English". Left
                empty, each answer stays in its question's language.
            position: by place in the file, counting from 1: "3" for the third
                question, "2-4", "last". Use this when the person counts questions;
                the number inside an id is a spreadsheet row, not a place.
        """
        scope = _scope(part, matching, False, ids, position)
        _log(f"reword_answers({instruction!r}, {scope.describe()})")
        if language and language not in ("ar", "en"):
            return 'The language is "ar" or "en".'
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        try:
            outcome = await tools.revise(
                user,
                _batch_id(),
                instruction,
                scope,
                run_id=state.get("run_id") or "",
                include_written=include_written,
                language=language or None,
            )
        except tools.ToolError as refused:
            return str(refused)
        state["refreshed"] = True
        return _reworded(outcome, scope)

    def _reworded(outcome: tools.Outcome, scope: tools.Scope, skill: str = "") -> str:
        kept = f" {outcome.protected} written by a person were left exactly as they are." if outcome.protected else ""
        if outcome.nothing_matched:
            return (
                f"No answered questions matched {scope.describe()}, so there was "
                "nothing to reword. Rewording a blank question is answering it."
            )
        if not outcome.attempted:
            return f"Nothing was reworded ({scope.describe()}).{kept}"
        how = f" with the skill {skill!r}" if skill else ""
        failed = f" {outcome.failed} could not be reworded and were left as they were." if outcome.failed else ""
        return f"Reworded {outcome.answered} of {outcome.attempted}{how} ({scope.describe()}).{failed}{kept}"

    def list_skills() -> str:
        """The skills the person can use: built-in ones, and any they wrote.

        Names and what each is for. The instructions themselves stay on the
        Preferences page.
        """
        _log("list_skills")

        def line(skill: preferences.Skill) -> str:
            return f"- {skill.name}" + (f": {skill.description}" if skill.description else "")

        builtin = [s for s in preferences.skills(user.email) if s.builtin]
        mine = preferences.own_skills(user.email)
        said = ["Built in:", *map(line, builtin)]
        said += (
            ["Their own:", *map(line, mine)]
            if mine
            else ["They have not written any of their own; that is done on the Preferences page."]
        )
        return "\n".join(said)

    def _which_skill(name: str) -> tuple[preferences.Skill | None, str]:
        found, candidates = preferences.find_skill(user.email, name)
        if found is not None:
            return found, ""
        if candidates:
            return None, (
                "More than one skill matches "
                f"{name!r}: " + ", ".join(repr(s.name) for s in candidates) + ". Ask which one they meant."
            )
        mine = preferences.skills(user.email)
        return None, (
            f"There is no skill called {name!r}. "
            + (
                "Their skills are: " + ", ".join(repr(s.name) for s in mine) + "."
                if mine
                else "They have not saved any skills yet."
            )
        )

    async def apply_skill(
        skill: str,
        part: str = "",
        matching: str = "",
        ids: str = "",
        include_written: bool = False,
        position: str = "",
    ) -> str:
        """Reword existing answers with one of the person's saved skills.

        The same rewording as `reword_answers`, with the skill's saved
        instruction in place of one given now. Answers a person wrote are left
        as they are unless `include_written`.

        Args:
            skill: the skill's name, as the person said it.
            part: a sheet name, or the section the questions sit under.
            matching: free text matched against the question and its section.
            ids: specific question ids, comma separated.
            include_written: reword answers a person wrote too. Only when the
                person asked for exactly those to be reworded.
            position: by place in the file, counting from 1: "3" for the third
                question, "2-4", "last". Use this when the person counts questions;
                the number inside an id is a spreadsheet row, not a place.
        """
        scope = _scope(part, matching, False, ids, position)
        _log(f"apply_skill({skill!r}, {scope.describe()})")
        found, refused = _which_skill(skill)
        if found is None:
            return refused
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        try:
            found, outcome = await tools.apply_skill(
                user,
                _batch_id(),
                found.skill_id,
                scope,
                run_id=state.get("run_id") or "",
                include_written=include_written,
            )
        except tools.ToolError as refusal:
            return str(refusal)
        state["refreshed"] = True
        return _reworded(outcome, scope, skill=found.name)

    def write_one_answer(text: str, question_id: str = "", position: str = "") -> str:
        """Replace one answer with words a person dictated.

        Args:
            text: exactly what they said to put there.
            question_id: the question's id, from list_questions or an answer card.
            position: or its place in the file, counting from 1: "4" for the
                fourth question. The number inside an id is a spreadsheet row.
        """
        _log(f"write_one_answer({question_id or '#' + position!r})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        if not question_id and position:
            placed = _scope("", "", False, "", position).ids
            if len(placed) != 1 or placed[0].startswith("("):
                return f"There is no single question at {position!r}. Name one question."
            question_id = placed[0]
        if not question_id:
            return "Say which question: its place in the file, or its id."
        try:
            tools.set_answer(user, _batch_id(), question_id, text)
        except tools.ToolError as refused:
            return str(refused)
        state["refreshed"] = True
        return f"Replaced the answer to {question_id} with the words given."

    def set_aside(question_ids: str = "", include: bool = False, position: str = "") -> str:
        """Leave questions out of the file, or bring them back in.

        Args:
            question_ids: ids to set aside, comma separated.
            include: true to bring them back rather than set them aside.
            position: by place in the file, counting from 1: "3" for the third
                question, "2-4", "last". Use this when the person counts questions;
                the number inside an id is a spreadsheet row, not a place.
        """
        _log(f"set_aside({question_ids or '#' + position!r}, include={include})")
        if not _batch_id():
            return "No questionnaire is open in this conversation."
        chosen = [piece.strip() for piece in question_ids.replace(";", ",").split(",") if piece.strip()]
        if position:
            chosen += [qid for qid in _scope("", "", False, "", position).ids if not qid.startswith("(")]
        if not chosen:
            return "Name the questions to set aside."
        try:
            tools.set_questions(user, _batch_id(), [{"id": qid, "skip": not include} for qid in chosen])
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
            1
            for question in report["questions"]
            for target in question.get("targets", [])
            if target.get("role") in ("answer", "status")
        )
        if not counts["answered"]:
            return "Nothing is answered yet, so filling the file would write nothing."
        state["offer_fill"] = True

        # The gate, said out loud. Reporting the answered count as though all of
        # it were going in would be a promise the button does not keep: an
        # answer nobody has confirmed is held back, and the person needs to know
        # that before they press it rather than after.
        held = counts.get("held_back", 0)
        going_in = sum(1 for q in report["questions"] if q.get("answer") and q.get("will_be_written"))
        aside = counts.get("set_aside", 0)
        lines = [
            f"Ready to fill {report['source_name']}: {going_in} answer(s) would be written "
            f"across about {writable} cell(s). Evidence columns are left blank unless asked "
            "for" + (f", and the {aside} set-aside question(s) are not written." if aside else ".")
        ]
        if held:
            lines.append(
                f"{held} more are held back because nobody has confirmed them -- each is "
                "either flagged for review or below the confidence needed to write "
                "unread. They are marked in the answer panel; editing or approving one "
                "releases it."
            )
        lines.append("I have not written anything -- the 'Fill the original file' button beside the answers does that.")
        return " ".join(lines)

    async def search_policies(query: str) -> str:
        """Look something up in the organisation's own documents, and read the clauses found.

        Search with the plain words of the question, without quotation marks: a
        quoted phrase matches only that exact text. Then quote the sentence that
        answers it word for word and name its document. At most three searches
        a turn; more, or the same one again, are refused.

        Args:
            query: what to look for, in plain words.
        """
        _log(f"search_policies({query!r})")
        refused = assistant_turn.search_refused(state, query)
        if refused:
            return refused
        try:
            found = await tools.search(query, team_id=user.team_id, product_id=state.get("product_id", ""))
        except Exception as failed:
            return f"The search failed: {failed}"
        hits = found.get("results", [])[:SOURCES_SHOWN]
        if not hits:
            return f"Nothing in the indexed policies matched {query!r}."

        # Kept for the interface as well as returned to the model. A claim about
        # what the policies say is worth exactly as much as the clause behind
        # it, and a person reading the reply should be able to open that clause
        # rather than take the sentence on trust -- the same bargain every
        # answer card makes.
        assistant_turn.add_sources(state, hits)
        return assistant_turn.clauses(hits)

    async def answer_directly(questions: str, skill: str = "") -> str:
        """Draft this organisation's answer to a question asked in conversation.

        NOT for "what does our policy say about X", "where is X written down",
        "which policy covers X" -- those ask to be shown a clause and belong to
        `search_policies`, which is seconds rather than half a minute. This is
        for "do we do X", "are we compliant with X", "what would we tell an
        assessor about X": a questionnaire question that arrived in a sentence
        instead of a spreadsheet.

        The same pipeline `answer_questions` runs -- retrieval, drafting,
        review, citations -- over a question somebody typed rather than one
        read out of a spreadsheet. Slow and not free, the same as answering a
        questionnaire row. Nothing is stored against a file and nothing can be
        filled in; the answer is for the person reading the reply.

        Args:
            questions: the question, or a few, one per line. At most five.
            skill: the name of one of the person's skills to word the answer
                with, when they asked for one. Otherwise their preferences, if
                they chose any, are applied on their own.
        """
        asked = [line.strip() for line in (questions or "").splitlines() if line.strip()]
        # The step is drawn under the reply, so which wording was used is said
        # there too -- a short answer is otherwise indistinguishable from a
        # skill that was asked for and quietly not applied.
        _log(
            f"answer_directly({len(asked)} question(s)" + (f", skill {skill.strip()!r}" if skill.strip() else "") + ")"
        )
        chosen = None
        if skill.strip():
            chosen, refused = _which_skill(skill)
            if chosen is None:
                return refused
        if not asked:
            return "Nothing to answer -- pass the question itself."
        if len(asked) > DIRECT_QUESTIONS:
            return (
                f"That is {len(asked)} questions. Answer at most {DIRECT_QUESTIONS} at a "
                "time this way; a list this long belongs in a questionnaire file."
            )

        drafted = await service.answer_questions(
            [
                Question(
                    id=f"asked-{index + 1}",
                    text=text,
                    language=detect_question_language(text),
                )
                for index, text in enumerate(asked)
            ],
            team_id=user.team_id,
            product_id=state.get("product_id", ""),
        )

        # Worded after drafting and never before, exactly as a questionnaire's
        # rows are: a named skill if one was asked for, their preferences if not.
        if chosen is not None:
            drafted = [
                await rewrite.rewrite(
                    result,
                    chosen.instruction,
                    note=f"Reworded with the skill \u201c{chosen.name}\u201d.",
                )
                if not result.error and result.answer.strip()
                else result
                for result in drafted
            ]
            events.record(
                user,
                events.SKILL_APPLIED,
                subject_type="conversation",
                subject_id=state.get("batch_id") or "",
                skill=chosen.name,
                reworded=len(drafted),
            )
        else:
            drafted = await tools.in_house_style(user, drafted)

        lines = []
        for result in drafted:
            lines.append(result.question.text)
            if result.error:
                lines.append(f"    could not be answered: {result.error}")
                continue
            # Verbatim, and said so, because this is a drafted answer and not
            # a note to summarise. The sources go to the interface for the same
            # reason they do under an answer card: a claim about the policies
            # is worth what the clause behind it is worth.
            lines.append(f"    answer, to relay word for word: {result.answer}")
            if result.drafted:
                lines.append("    (reworded to your preferences)")
            if result.needs_review:
                lines.append(f"    flagged for review: {result.confidence_reason or 'low confidence'}")
            # What it cites, in the reply's own history, so "where did that come
            # from" a few messages later is answered from this and not from a
            # new search that finds something similar.
            lines.extend(_sources_of(result.model_dump(), detailed=True))
            assistant_turn.add_sources(state, (item.model_dump() for item in result.evidence[:SOURCES_SHOWN]))
        return "\n".join(lines)

    return [
        open_questionnaire,
        describe_form,
        list_questions,
        read_existing,
        answer_questions,
        reword_answers,
        write_one_answer,
        set_aside,
        propose_fill,
        search_policies,
        answer_directly,
        list_skills,
        apply_skill,
        read_answers,
        put_back_drafts,
    ]


def _language_of_the_turn(messages: list[BaseMessage]) -> str:
    last = next((m for m in reversed(messages) if isinstance(m, HumanMessage) and not _is_correction(m)), None)
    return detect_question_language(spoken(str(last.content))) if last is not None else "en"


def _agent(tool_list: list, product: str = ""):
    from langchain.agents import create_agent
    from langchain.agents.middleware import ClearToolUsesEdit, ContextEditingMiddleware, dynamic_prompt

    @dynamic_prompt
    def in_their_language(request) -> str:
        for_product = FOR_PRODUCT.format(name=product) if product else ""
        return SYSTEM + for_product + (IN_ARABIC if _language_of_the_turn(request.messages) == "ar" else "")

    return create_agent(
        chat_llm(temperature=0.0),
        tools=tool_list,
        middleware=[
            in_their_language,
            ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=40_000, keep=6)]),
        ],
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
                content = "".join(block.get("text", "") for block in content if isinstance(block, dict))
            # Whatever a reasoning model thought on the way is not what it
            # said, and the reply is shown to a person verbatim.
            spoken_text = without_reasoning(str(content))
            if spoken_text:
                return without_repetition(spoken_text)
    return ""


def _trace_config(conversation: Conversation, recursion_limit: int) -> dict:
    """Name and group one turn, for whoever is reading the traces.

    The same argument as `graph.workflow.trace_config`, which this deliberately
    mirrors: every turn of every conversation arrives called "LangGraph", and a
    project of a few hundred of those cannot be navigated at all. Here the unit
    is the conversation rather than the batch -- `session_id` is the id Phoenix
    groups by, so a conversation reads as one thread of turns instead of five
    unrelated traces.

    No message text: the prompts already carry it, and a trace does not need
    the customer's questionnaire twice.
    """
    return {
        "recursion_limit": recursion_limit,
        "run_name": f"assistant[{conversation.id}]",
        "tags": ["assistant"],
        "metadata": {
            "conversation_id": conversation.id,
            "session_id": conversation.id,
            "batch_id": conversation.batch_id or "",
        },
    }


async def say(
    user: User,
    conversation: Conversation,
    message: str,
    *,
    upload: Path | None = None,
    run_id: str = "",
) -> Turn:
    """One exchange. Runs the tools, saves the conversation, returns what happened.

    The conversation is saved even when the turn fails part way through: the
    tools it did call have already changed the batch, and a history that does
    not mention them would leave the assistant contradicting the answer panel
    beside it.
    """
    started = time.monotonic()
    turn = Turn(conversation_id=conversation.id, batch_id=conversation.batch_id)

    # Registered before the first model call, so a page watching this turn has
    # something to read from the moment it starts asking. `run_id` comes from
    # the caller rather than being minted here: on a first turn there is no
    # conversation and no batch to name it after, which is exactly the turn
    # that takes longest.
    progress.start(run_id, stage="Thinking…")

    state: dict = {
        "run_id": run_id,
        "batch_id": conversation.batch_id,
        "product_id": conversation.product_id,
        "pending_upload": str(upload) if upload else "",
        "steps": turn.steps,
        "refreshed": False,
        "offer_fill": False,
        "sources": turn.sources,
    }
    # What the person actually typed, kept apart from what the model is told.
    # The note below is plumbing -- it exists so the agent knows a file arrived
    # -- and it was going into the conversation's title, so the history filled
    # up with entries reading "Read this file. [A file has been uploaded to
    # this conversation: HR…".
    asked = message
    if upload:
        message = (f"{message}\n\n{UPLOAD_NOTE} {upload.name}. Call open_questionnaire to read it.]").strip()

    # When it was said and what came with it, on the message itself: a
    # conversation kept open for a week reads as one undifferentiated scroll
    # without the first, and "read this" means nothing without the second.
    # Neither is sent to the model -- extra fields on a message stay local.
    said = HumanMessage(
        message,
        additional_kwargs={
            "at": store.utcnow(),
            **({"file": upload.name} if upload else {}),
        },
    )
    history = _window(list(conversation.messages)) + [said]
    final: dict = {}
    sending = history
    tools_bound = _tools(user, state)
    # Named in the prompt only when there is one, so a General conversation's is unchanged.
    product = next((p.name for p in products.list_products(user.team_id) if p.id == conversation.product_id), "")
    earlier = [str(message.content) for message in history if _said(message)][-3:]

    def reply_now() -> str:
        # This turn's reply and no other: one that stopped used to repeat the last turn's.
        return tidy_reply(_reply_from({"messages": _this_turn(history, final)}), earlier)

    unquoted: list[str] = []
    asked_again = False
    for attempt in range(1 + CARRY_ON):
        unquoted = []
        try:
            async for chunk in _agent(tools_bound, **({"product": product} if product else {})).astream(
                {"messages": sending},
                _trace_config(conversation, MAX_STEPS),
                stream_mode="values",
            ):
                final = chunk
        except Exception as failed:
            if attempt < CARRY_ON and _invented_a_tool(failed):
                # Carried on from what the turn had finished, not started again:
                # an answer_questions that already ran is not paid for twice.
                logger.info("The model called a tool that does not exist; carrying on")
                sending = _resume_from(history, final) + [_correction(failed)]
                continue
            logger.warning("The assistant stopped early: %s", failed)
            turn.stopped_early = True
            break
        # A quotation no source contains is asked about once, the draft dropped unseen (TD-043).
        unquoted = assistant_turn.unquoted(reply_now(), final, turn.sources)
        if not unquoted or asked_again or attempt == CARRY_ON:
            break
        asked_again = True
        sending = _resume_from(history, assistant_turn.without_reply(final)) + [
            assistant_turn.quote_correction(unquoted)
        ]

    _account(final, turn)
    language = _language_of_the_turn(history)
    turn.reply = reply_now() or (
        assistant_turn.stopped_reply(state, language)
        if turn.stopped_early
        else "I could not work out what to do with that. Could you say it another way?"
    )
    if unquoted:
        turn.reply = assistant_turn.as_paraphrase(turn.reply, unquoted, language, listed=bool(turn.sources))
    turn.batch_id = state.get("batch_id", "")
    turn.refreshed = bool(state.get("refreshed"))

    conversation.messages = _remember(
        _keep(conversation.messages, history, final, turn.reply),
        turn,
    )
    conversation.batch_id = turn.batch_id
    if not conversation.title:
        conversation.title = conversations.title_from(asked)
    conversations.save(conversation)

    events.record(
        user,
        events.ASSISTANT_TURN,
        subject_type=conversations.SUBJECT,
        subject_id=conversation.id,
        steps=len(turn.steps),
        batch_id=turn.batch_id,
        tokens=turn.input_tokens + turn.output_tokens,
    )
    turn.seconds = time.monotonic() - started
    progress.finish(run_id)
    return turn


def _remember(messages: list[BaseMessage], turn: Turn) -> list[BaseMessage]:
    """Attach what this turn did to the reply it produced."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            # Stored as it was shown. A reply kept with an echo in it is re-sent
            # with the history, and the model imitates what it is shown.
            if turn.reply:
                message.content = turn.reply
            message.additional_kwargs[UI_KEY] = {
                "steps": list(turn.steps),
                "sources": list(turn.sources),
                "at": store.utcnow(),
                # Whether the answers changed, so the reply can offer to show
                # them -- a conversation reopened tomorrow included.
                "changed": bool(turn.refreshed),
            }
            break
    return messages


def _turns(messages: list[BaseMessage]) -> list[list[BaseMessage]]:
    """A conversation cut into turns, each starting with what a person said."""
    turns: list[list[BaseMessage]] = []
    for message in messages:
        if isinstance(message, HumanMessage) or not turns:
            turns.append([])
        turns[-1].append(message)
    return [turn for turn in turns if isinstance(turn[0], HumanMessage)]


def _complete(turn: list[BaseMessage]) -> list[BaseMessage]:
    """A turn with nothing in it the model API would refuse.

    A turn that stopped part way through can end on a tool call whose result
    never came, and a saved conversation is re-sent every time: one such call
    left in the history failed every later turn. Calls without results, and
    results without their call, are dropped; everything else stays.
    """
    answered = {m.tool_call_id for m in turn if isinstance(m, ToolMessage)}
    asked: set[str] = set()
    kept: list[BaseMessage] = []
    for message in turn:
        if isinstance(message, AIMessage) and message.tool_calls:
            ids = {call.get("id") for call in message.tool_calls}
            if not ids <= answered:
                continue
            asked |= ids
        elif isinstance(message, ToolMessage) and message.tool_call_id not in asked:
            continue
        kept.append(message)
    return kept


def _said(message: BaseMessage) -> bool:
    return isinstance(message, AIMessage) and not message.tool_calls and bool(str(message.content or "").strip())


def _window(messages: list[BaseMessage]) -> list[BaseMessage]:
    """What the model is shown of a conversation: the recent past, whole.

    Always starts at a person's message, so no turn arrives cut in half. The
    last few turns keep their tool calls and results; older ones are reduced
    to what was asked and what was replied. The stored conversation is not
    touched -- this is only what is sent.
    """
    turns = _turns(messages)[-TURNS_REMEMBERED:]
    window: list[BaseMessage] = []
    for index, turn in enumerate(turns):
        if index >= len(turns) - TURNS_IN_FULL:
            window.extend(_complete(turn))
            continue
        window.append(turn[0])
        reply = next((m for m in reversed(turn) if _said(m)), None)
        if reply is not None:
            window.append(AIMessage(str(reply.content)))
    return window


def _invented_a_tool(failed: Exception) -> bool:
    """Whether the provider refused a call to a tool that was never offered.

    The model on Groq now and then calls `repo_browser.open_file` -- a tool from
    its own training, not from this request -- and Groq rejects the whole
    request. In the assistant evaluation that ended two turns, one of them a
    turn that had already answered four questions, and the next turn then
    reported the broken one instead of doing what was asked.
    """
    text = str(failed)
    return "tool_use_failed" in text or "not in request.tools" in text


CARRY_ON = 2
"""How many times a turn carries on: after the model calls a tool that does not
exist, or, once, after its reply quoted what no source says."""


def _correction(failed: Exception) -> HumanMessage:
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


def _this_turn(sent: list[BaseMessage], final: dict) -> list[BaseMessage]:
    """What this turn added after the person's message, corrections left out."""
    produced = list((final or {}).get("messages", []))
    new = produced[len(sent) :] if len(produced) >= len(sent) else []
    return [message for message in new if not _is_correction(message)]


def _resume_from(history: list[BaseMessage], final: dict) -> list[BaseMessage]:
    """The history plus whatever this turn completed before it was refused."""
    return history[:-1] + _complete([history[-1], *_this_turn(history, final)])


def _keep(
    stored: list[BaseMessage],
    sent: list[BaseMessage],
    final: dict,
    reply: str,
) -> list[BaseMessage]:
    """The whole conversation after a turn: everything before, and this turn.

    What was stored stays stored. The model is shown a window of it, and this
    used to save that window back as though it were the conversation -- so past
    about ten turns the start of every long conversation was deleted, turn by
    turn, from the history a person scrolls back through.

    This turn is taken from the agent's own final state where there is one, so
    its tool calls and results are kept for the next turn to refer to. A turn
    that failed before the graph produced anything keeps the person's message
    and whatever was said, so nothing they typed is silently dropped.
    """
    turn = _complete([sent[-1], *_this_turn(sent, final)])
    if not any(_said(message) for message in turn[1:]):
        turn.append(AIMessage(reply))
    return list(stored) + turn


def start(user: User, message: str = "", product_id: str = "") -> Conversation:
    """A new conversation, titled from what was first asked of it, for a product or General ("")."""
    conversation = conversations.create(user, message, products.chosen(user.team_id, product_id))
    events.record(
        user,
        events.ASSISTANT_STARTED,
        subject_type=conversations.SUBJECT,
        subject_id=conversation.id,
    )
    return conversation


def choose_product(user: User, conversation: Conversation, product_id: str) -> None:
    """Refused unless it is the chat's own product: a chat's product is fixed once it starts (TD-040).

    So are the questionnaires opened in it, which take the chat's product. Another
    team's product, or a deleted one, is still `product_not_found`.
    """
    products.refuse_change(
        user.team_id,
        conversation.product_id,
        product_id,
        "A chat's product is fixed once it starts. To work on another product, start a new chat with it chosen.",
    )


def answers_for(user: User, conversation: Conversation) -> dict | None:
    """The answer cards to draw beside the chat, or None if no file is open.

    The same payload the other interface renders, deliberately: the cards, the
    sources and the reviewer's reasoning are the thing worth looking at, and
    two renderings of it would drift.
    """
    if not conversation.batch_id:
        return None
    batch = batches.load(conversation.batch_id, team_id=user.team_id, actor_email=user.email)
    if batch is None:
        return None
    return tools.inspect(user, conversation.batch_id)


def configured() -> bool:
    """Whether the assistant can run at all."""
    return bool(settings.groq_api_key)
