"""Measure what the assistant actually does, against the real model.

    python -m scripts.eval_assistant                  # every case, once
    python -m scripts.eval_assistant --repeat 3       # and how much it varies
    python -m scripts.eval_assistant --only arabic    # cases whose name matches
    python -m scripts.eval_assistant --json out.json

`tests/test_assistant.py` tests the machinery a model's choices land on, with
the model stubbed out. This tests the choices, which is a different question
and cannot be answered deterministically: an agent asked the same thing twice
may do it two ways, and both may be right.

So a case does not assert a transcript. It asserts the things that would be
wrong whichever route was taken:

  wants        tools that must have been called
  forbids      tools that must NOT have been -- usually `answer_questions`,
               because answering again when asked to reword is the expensive
               mistake, and re-answering a question that already has an answer
               is the same mistake by a different name.
               Note that this is per *case*, not per turn: a case whose first
               turn is meant to answer cannot forbid answering, and has to rely
               on `answered` to catch a second turn doing it again
  answered     how many questions should end up with an answer
  reply_in     the language the reply must be written in
  reply_has    alternatives, one of which the reply must contain -- for when
               the answer is a fact rather than a tool call
  at_most      a ceiling on how often a tool may be called, for the ones where
               calling it is right and calling it five times is a mess

A failing case prints the tools it called and what it said. Both are evidence
you cannot get back afterwards: "it did not call X" is not a finding -- what it
called instead is -- and "replied in ar, got en" does not say whether the
assistant was wrong or the counting was.

Each case runs against a fixture questionnaire built by the suite, so nothing
here depends on a customer's file. The answering pipeline is real -- these are
real retrievals against the real corpus -- because "did it answer the right
questions" is the thing being measured and a stub would answer all of them
equally well.

Run it with `--repeat` after changing the system prompt or the tool
descriptions. A score that drops is a regression; a score that swings between
runs at the same commit is telling you the instruction is ambiguous, which is
worth knowing before a person hits it.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print = functools.partial(print, flush=True)  # noqa: A001 - flush each line, so a slow run reads as alive

# Half the cases are in Arabic, and a Windows console defaults to a codepage
# that cannot encode it -- so `--verbose`, the one flag you reach for to find
# out why an Arabic case failed, died with a UnicodeEncodeError before printing
# the reply. Replacement rather than strict: a mangled character in a diagnostic
# line is a nuisance, and a crash in the middle of a suite is an hour.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src import batches, conversations, identity, llm, tools
from src.agents import assistant
from src.conversations import Conversation
from tests import forms_fixtures as shapes

_ARABIC = re.compile(r"[؀-ۿ]")


@dataclass
class Case:
    """One instruction, and what would be wrong about any way of following it."""

    name: str
    says: list[str]
    """The turns, in order. More than one where the point is the follow-up."""

    wants: tuple[str, ...] = ()
    forbids: tuple[str, ...] = ()
    answered: int | None = None
    reply_in: str = ""
    reply_has: tuple[str, ...] = ()
    """Alternatives, at least one of which the reply must contain.

    For the cases where the answer is a fact rather than a tool call and
    getting it wrong is invisible in the steps. Alternatives rather than a
    single string because a correct answer has several spellings: asked in
    Arabic how many were left, the assistant wrote the number in words."""
    shape: str = "status_and_comment"
    """Which fixture questionnaire to run against."""

    at_most: dict | None = None
    """A ceiling on how often a tool may be called.

    For the ones where calling it at all is right and calling it five times is
    a wall of sources under a two-line reply."""

    last_wants: tuple[str, ...] = ()
    """Tools the *last* turn must call.

    For follow-ups. A case whose first turn answers cannot forbid answering,
    and "what is the answer to question 2" is exactly the follow-up where
    answering again -- or reporting how to fill the file -- is the mistake."""

    last_forbids: tuple[str, ...] = ()
    """Tools the last turn must not call."""

    last_calls_nothing: bool = False
    """The last turn is conversation, not work: "thanks", "what can you do"."""

    quotes_answer: int = 0
    """The reply must contain the answer stored for the question at this place
    in the file, counting from 1. Read back from the batch after the case, so
    the check holds whatever the pipeline happened to write."""

    names_sources_of: int = 0
    """The reply must name the documents the stored answer at this place cites.

    Asked which sources an answer used, the assistant searched the policies
    again and listed what that search found -- a similar list, not the one on
    the answer's card. Each cited document counts as named when the reply has
    its file name (without the extension) or the clause it was cited at, with
    dashes and spacing ignored: the model writes "T2 \u2013 Human Resources
    Policy", and an Arabic reply translates the name and keeps "\u00a73.1-3.1.4".
    Only policy documents are held to this: a remembered answer has neither a
    file name nor a clause, and "the team's previous answers" in Arabic is the
    right way to name one."""

    answers_in: str = ""
    """Every stored answer must be written in this language, "ar" or "en"."""

    answer_contains: dict | None = None
    """{place: text} -- the stored answer at that place must contain the text."""

    upload_on: int = 0
    """Which turn carries the file, or -1 for a case with no file at all.

    A question can be asked straight out -- "do we encrypt backups?" -- and the
    assistant answers it from the policies without anything being uploaded."""


CASES: list[Case] = [
    Case(
        name="read-and-report",
        says=["Read this questionnaire and tell me what is in it."],
        wants=("open_questionnaire",),
        forbids=("answer_questions",),
        answered=0,
    ),
    Case(
        name="answer-everything",
        says=["Read this and answer all of it."],
        wants=("open_questionnaire", "answer_questions"),
        answered=4,
    ),
    Case(
        name="scoped-by-topic",
        says=["Read this and answer only the questions about training or awareness."],
        wants=("open_questionnaire", "answer_questions"),
        answered=1,
    ),
    Case(
        name="compound-answer-then-reword",
        says=["Read this, answer everything, and keep every answer to a single short sentence."],
        wants=("open_questionnaire", "answer_questions", "reword_answers"),
        answered=4,
    ),
    Case(
        name="finish-the-rest",
        says=[
            "Read this and answer only the training question.",
            "Now finish the rest of them.",
        ],
        wants=("answer_questions",),
        answered=4,
    ),
    Case(
        name="reword-only-never-re-answers",
        says=[
            "Read this and answer all of it.",
            "Make them all more formal.",
        ],
        wants=("reword_answers",),
        answered=4,
    ),
    Case(
        name="will-not-fill-a-file",
        says=[
            "Read this and answer all of it.",
            "Now write the answers into the file and save it.",
        ],
        wants=("propose_fill",),
        answered=4,
    ),
    Case(
        name="declines-knowledge-base-work",
        says=["Delete the HR policy from the knowledge base and re-index everything."],
        forbids=("answer_questions", "reword_answers", "propose_fill"),
        answered=0,
    ),
    Case(
        name="arabic-reply",
        says=["اقرأ هذا الاستبيان وأخبرني بعدد الأسئلة الموجودة فيه"],
        wants=("open_questionnaire",),
        forbids=("answer_questions",),
        answered=0,
        reply_in="ar",
    ),
    Case(
        name="arabic-compound",
        says=["اقرأ هذا الملف وأجب عن جميع الأسئلة، واجعل كل إجابة جملة واحدة قصيرة"],
        wants=("open_questionnaire", "answer_questions", "reword_answers"),
        answered=4,
        reply_in="ar",
    ),
    Case(
        name="set-aside-by-instruction",
        says=[
            "Read this file.",
            "Leave out the question about background checks — we do not do those.",
        ],
        wants=("set_aside",),
        answered=0,
    ),
    Case(
        name="counts-what-is-left",
        says=[
            "Read this and answer only the training question.",
            "How many are still unanswered?",
        ],
        reply_has=("3", "three"),
        answered=1,
    ),
    Case(
        name="arabic-counts-what-is-left",
        says=[
            "Read this and answer only the training question.",
            "كم سؤالاً بقي بدون إجابة؟",
        ],
        reply_has=("3", "٣", "ثلاث"),
        reply_in="ar",
        answered=1,
    ),
    Case(
        name="knows-what-the-file-already-said",
        says=["Read this and tell me how many already have answers."],
        wants=("open_questionnaire",),
        forbids=("answer_questions",),
        reply_has=("2", "two"),
        answered=0,
        shape="already_answered",
    ),
    Case(
        name="does-not-overwrite-what-the-file-had",
        says=[
            "Read this file.",
            "Answer the ones that are still blank.",
        ],
        wants=("answer_questions",),
        answered=2,
        shape="already_answered",
    ),
    Case(
        name="reads-back-what-the-file-said",
        says=[
            "Read this file.",
            "What did we say about the human resources process last time?",
        ],
        wants=("read_existing",),
        forbids=("answer_questions",),
        answered=0,
        shape="already_answered",
    ),
    Case(
        # The expensive one. Two of the four arrived answered by the security
        # team, the instruction is the broadest there is, and the right
        # behaviour is to answer the other two and leave theirs standing.
        name="answers-the-blanks-not-the-whole-file",
        says=[
            "Read this file.",
            "Answer this questionnaire.",
        ],
        wants=("answer_questions",),
        answered=2,
        shape="already_answered",
    ),
    Case(
        # The other half of it: told plainly to redo one, it must actually redo
        # it rather than reporting the guard back as a refusal.
        name="redoes-an-answer-when-told-to",
        says=[
            "Read this file.",
            "The answer about the human resources process is out of date. "
            "Throw it away and write a new one from our policies.",
        ],
        wants=("answer_questions",),
        answered=1,
        shape="already_answered",
    ),
    Case(
        name="answers-a-question-with-no-file",
        says=["Do we encrypt customer data at rest? Answer it properly, as if for an assessor."],
        wants=("answer_directly",),
        forbids=("open_questionnaire", "answer_questions"),
        answered=0,
        upload_on=-1,
    ),
    Case(
        name="arabic-question-with-no-file",
        says=["هل نقوم بتشفير بيانات العملاء أثناء التخزين؟"],
        wants=("answer_directly",),
        answered=0,
        reply_in="ar",
        upload_on=-1,
    ),
    Case(
        name="one-search-not-five",
        says=["What does our policy say about password length?"],
        wants=("search_policies",),
        forbids=("answer_questions",),
        answered=0,
        at_most={"search_policies": 2},
    ),
    Case(
        name="searches-rather-than-inventing",
        says=["What does our own policy say about password length?"],
        wants=("search_policies",),
        forbids=("answer_questions",),
        answered=0,
    ),
    # The two cases above and the two below draw the same line from both
    # sides. Which tool answers a question with no file behind it is decided
    # by the shape of the question -- and a person who wants the other one
    # should be able to say so in the words they would naturally use, without
    # learning a command. These two are that escape hatch, held to by the
    # suite rather than left to hold by luck.
    Case(
        name="show-me-the-clause-overrides-drafting",
        says=["Do we encrypt customer data at rest? Just show me what the policy says — do not write me an answer."],
        wants=("search_policies",),
        forbids=("answer_directly", "answer_questions"),
        answered=0,
        upload_on=-1,
    ),
    Case(
        name="answer-it-properly-overrides-looking-up",
        says=[
            "What does our policy say about password length? Answer it properly, "
            "the way we would put it to an assessor."
        ],
        wants=("answer_directly",),
        forbids=("answer_questions",),
        answered=0,
        upload_on=-1,
        # One incidental search is forgivable; falling back into pure lookup
        # and never drafting is the regression, and `wants` catches that.
        at_most={"search_policies": 1},
    ),
    # --- asked about the answers, rather than asked to change them -----------
    #
    # The failure these were written for: asked "what is the second question
    # answer?", the assistant replied that the answer "has been drafted and is
    # ready to be written to the file" and pointed at the fill button. It had
    # no way to read an answer back, so it described the one thing it could
    # see. Every case here is a question about the answers; none is a request
    # to change one.
    Case(
        name="reads-back-an-answer-by-position",
        says=["Read this and answer all of it.", "what is the second question answer?"],
        answered=4,
        last_wants=("read_answers",),
        last_forbids=("answer_questions", "reword_answers", "propose_fill", "answer_directly"),
        quotes_answer=2,
    ),
    Case(
        name="reads-back-the-last-answer",
        says=["Read this and answer all of it.", "Read me the last answer."],
        answered=4,
        last_wants=("read_answers",),
        last_forbids=("answer_questions", "reword_answers", "propose_fill", "answer_directly"),
        quotes_answer=4,
    ),
    Case(
        name="reads-back-an-answer-by-topic",
        says=["Read this and answer all of it.", "What did you write for the training question?"],
        answered=4,
        last_forbids=("answer_questions", "reword_answers", "propose_fill", "answer_directly"),
        quotes_answer=2,
    ),
    Case(
        name="reads-back-an-answer-asked-in-arabic",
        says=["Read this and answer all of it.", "ما هي إجابة السؤال الثالث؟"],
        answered=4,
        last_forbids=("answer_questions", "reword_answers", "propose_fill", "answer_directly"),
        quotes_answer=3,
    ),
    Case(
        name="says-which-sources-an-answer-used",
        says=["Read this and answer all of it.", "What sources did you use for the answer to question 2?"],
        answered=4,
        last_wants=("read_answers",),
        last_forbids=("search_policies", "answer_questions", "reword_answers", "propose_fill", "answer_directly"),
        names_sources_of=2,
    ),
    Case(
        name="says-which-sources-an-answer-used-in-arabic",
        says=["Read this and answer all of it.", "ما هي المصادر التي اعتمدت عليها في إجابة السؤال الأول؟"],
        answered=4,
        last_wants=("read_answers",),
        last_forbids=("search_policies", "answer_questions", "reword_answers", "propose_fill", "answer_directly"),
        names_sources_of=1,
    ),
    Case(
        name="says-which-are-flagged-and-why",
        says=["Read this and answer all of it.", "Are any of the answers flagged? Why?"],
        answered=4,
        last_forbids=("answer_questions", "reword_answers", "propose_fill", "answer_directly"),
    ),
    Case(
        name="answer-before-it-exists-is-not-invented",
        says=["Read this file.", "What is the answer to question 2?"],
        answered=0,
        last_forbids=("reword_answers", "propose_fill", "answer_directly"),
        reply_has=("not", "no answer", "hasn't", "has not", "yet"),
    ),
    Case(
        name="no-file-open-says-so",
        says=["What is the answer to question 2?"],
        forbids=("answer_questions", "reword_answers", "propose_fill"),
        answered=0,
        upload_on=-1,
    ),
    # --- changing, undoing, and what it cannot do ---------------------------------
    Case(
        name="undoes-a-rewording",
        says=[
            "Read this and answer all of it.",
            "Make every answer a single short sentence.",
            "Undo that, the original answers were better.",
        ],
        answered=4,
        last_wants=("put_back_drafts",),
        last_forbids=("answer_questions", "reword_answers"),
    ),
    Case(
        # Question 3's id is `Human Resources!4` in this fixture: the row. Asked
        # for question 3, the assistant reworded the training question instead,
        # whose id ends in 3 -- the question counted, taken for the row.
        name="counts-questions-not-rows",
        says=["Read this and answer all of it.", "Change the answer to question 3 to: Yes, on the same day."],
        answered=4,
        last_wants=("write_one_answer",),
        last_forbids=("answer_questions",),
        answer_contains={3: "on the same day"},
    ),
    Case(
        name="translates-when-asked",
        says=["Read this and answer all of it.", "Translate all the answers to Arabic."],
        answered=4,
        last_wants=("reword_answers",),
        last_forbids=("answer_questions",),
        answers_in="ar",
    ),
    Case(
        name="replaces-one-answer-as-dictated",
        says=[
            "Read this and answer all of it.",
            "Change the answer to question 4 to: Yes, background checks are completed for every new hire.",
        ],
        answered=4,
        last_wants=("write_one_answer",),
        last_forbids=("answer_questions", "reword_answers"),
        answer_contains={4: "background checks are completed for every new hire"},
    ),
    Case(
        name="cannot-approve-and-says-where",
        says=["Read this and answer all of it.", "Approve all of them."],
        answered=4,
        last_forbids=("answer_questions", "reword_answers", "propose_fill", "write_one_answer"),
        reply_has=("card",),
    ),
    Case(
        name="asks-rather-than-guesses-a-vague-request",
        says=["Read this and answer all of it.", "fix it"],
        answered=4,
        last_forbids=(
            "answer_questions",
            "reword_answers",
            "propose_fill",
            "write_one_answer",
            "set_aside",
            "put_back_drafts",
        ),
    ),
    # --- conversation that is not work -------------------------------------------------
    Case(
        name="thanks-is-not-an-instruction",
        says=["Read this and answer all of it.", "Thanks, that is all for now."],
        answered=4,
        last_calls_nothing=True,
    ),
    Case(
        name="says-what-it-can-do",
        says=["What can you do?"],
        answered=0,
        upload_on=-1,
        last_calls_nothing=True,
    ),
    Case(
        name="declines-something-off-topic",
        says=["Write me a short poem about cats."],
        forbids=("answer_directly", "answer_questions", "search_policies"),
        answered=0,
        upload_on=-1,
    ),
]


@dataclass
class Result:
    case: str
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    reply: str = ""
    seconds: float = 0.0
    tokens: int = 0

    @property
    def score(self) -> float:
        total = len(self.passed) + len(self.failed)
        return len(self.passed) / total if total else 1.0


def _language(text: str) -> str:
    arabic = len(_ARABIC.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "ar" if arabic > latin else "en"


async def run_case(case: Case, user) -> Result:
    """One case, start to finish, against the real model."""
    result = Result(case=case.name)
    workspace = Path(tempfile.mkdtemp(prefix="eval_assistant_"))
    path = getattr(shapes, case.shape)(workspace / "HR Assessment.xlsx") if case.upload_on >= 0 else None

    conversation: Conversation = assistant.start(user, "")
    last_steps: list[str] = []
    for index, says in enumerate(case.says):
        turn = await assistant.say(user, conversation, says, upload=path if index == case.upload_on else None)
        last_steps = list(turn.steps)
        result.steps.extend(turn.steps)
        result.reply = turn.reply
        result.seconds += turn.seconds
        result.tokens += turn.input_tokens + turn.output_tokens

    called = {step.split("(", 1)[0] for step in result.steps}
    for wanted in case.wants:
        (result.passed if wanted in called else result.failed).append(f"called {wanted}")
    for forbidden in case.forbids:
        (result.failed if forbidden in called else result.passed).append(f"did not call {forbidden}")

    last_called = {step.split("(", 1)[0] for step in last_steps}
    for wanted in case.last_wants:
        (result.passed if wanted in last_called else result.failed).append(f"last turn called {wanted}")
    for forbidden in case.last_forbids:
        (result.failed if forbidden in last_called else result.passed).append(f"last turn did not call {forbidden}")
    if case.last_calls_nothing:
        (result.passed if not last_steps else result.failed).append(
            "last turn called nothing" if not last_steps else f"last turn called {', '.join(last_steps)}"
        )

    stored = []
    if conversation.batch_id and (
        case.quotes_answer or case.answers_in or case.answer_contains or case.names_sources_of
    ):
        stored = tools.inspect(user, conversation.batch_id)["questions"]

    def at_place(place: int) -> str:
        return (stored[place - 1].get("answer") or "") if 0 < place <= len(stored) else ""

    if case.quotes_answer:
        answer = " ".join(at_place(case.quotes_answer).split())
        spoken = " ".join(result.reply.split())
        # The opening of the stored answer, allowing for Markdown the reply may
        # have wrapped around it: a relay that changes the words is a summary.
        probe = re.sub(r"[*_`]", "", answer)[:60].casefold()
        quoted = bool(probe) and probe in re.sub(r"[*_`]", "", spoken).casefold()
        (result.passed if quoted else result.failed).append(
            f"quoted answer #{case.quotes_answer}"
            if quoted
            else f"did not quote answer #{case.quotes_answer} ({answer[:60]!r})"
        )

    if case.names_sources_of:
        place = case.names_sources_of
        answered = (stored[place - 1].get("answered") or {}) if 0 < place <= len(stored) else {}
        cited = set(answered.get("citations") or [])

        def flat(text: str) -> str:
            return re.sub(r"[\s*_`]+", "", re.sub(r"[\u2010-\u2015\u2212]", "-", text)).casefold()

        # Each cited document, as the two ways a reply can name it.
        documents: dict[str, set[str]] = {}
        for item in answered.get("evidence") or []:
            locator = item.get("locator") or item.get("source_name") or ""
            if locator in cited and item.get("source_name") and item.get("source_type") != "prior_answer":
                ways = documents.setdefault(Path(item["source_name"]).stem, set())
                ways.add(flat(Path(item["source_name"]).stem))
                if "\u00a7" in locator:
                    ways.add(flat(locator.split("\u00a7", 1)[1].split("(", 1)[0]))
        spoken = flat(result.reply)
        missing = sorted(name for name, ways in documents.items() if not any(way and way in spoken for way in ways))
        named = bool(documents) and not missing
        (result.passed if named else result.failed).append(
            f"named the sources answer #{place} cites"
            if named
            else f"answer #{place} cites nothing to name"
            if not documents
            else f"did not name {missing} that answer #{place} cites"
        )

    if case.answers_in:
        written = [q.get("answer") or "" for q in stored if q.get("answer")]
        right = bool(written) and all(_language(text) == case.answers_in for text in written)
        (result.passed if right else result.failed).append(
            f"answers written in {case.answers_in}" if right else f"answers not all in {case.answers_in}"
        )

    for place, text in (case.answer_contains or {}).items():
        found = text.casefold() in at_place(place).casefold()
        (result.passed if found else result.failed).append(
            f"answer #{place} says what was dictated" if found else f"answer #{place} is {at_place(place)[:60]!r}"
        )

    for name, ceiling in (case.at_most or {}).items():
        used = sum(1 for step in result.steps if step.split("(", 1)[0] == name)
        (result.passed if used <= ceiling else result.failed).append(
            f"called {name} at most {ceiling}x"
            if used <= ceiling
            else f"called {name} {used}x, at most {ceiling} wanted"
        )

    if case.answered is not None:
        got = 0
        if conversation.batch_id:
            report = tools.inspect(user, conversation.batch_id)
            got = report["counts"]["answered"]
        check = f"answered {case.answered}"
        (result.passed if got == case.answered else result.failed).append(
            check if got == case.answered else f"{check}, got {got}"
        )

    if case.reply_has:
        # Case-insensitively: "Two of the questions already have answers" is the
        # right answer, and a check that only accepted "two" failed it.
        spoken = result.reply.casefold()
        said = any(wanted.casefold() in spoken for wanted in case.reply_has)
        (result.passed if said else result.failed).append(
            "gave the right count" if said else "did not say any of " + ", ".join(repr(w) for w in case.reply_has)
        )

    if case.reply_in:
        spoken = _language(result.reply)
        (result.passed if spoken == case.reply_in else result.failed).append(
            f"replied in {case.reply_in}" if spoken == case.reply_in else f"replied in {case.reply_in}, got {spoken}"
        )

    # Last, after everything that reads them. A suite that leaves a batch and a
    # conversation behind per case leaves sixty per run, and they turn up in
    # the interface: "Or pick up" and the conversation list filled with fixture
    # questionnaires nobody uploaded, until somebody went and deleted 177 rows
    # by hand. A test that dirties the thing it is testing is not finished.
    _forget(conversation)
    return result


def _forget(conversation: Conversation) -> None:
    """Drop what one case created. Best effort -- a failure here is not a result."""
    try:
        if conversation.batch_id:
            batches.delete(conversation.batch_id)
        conversations.delete(conversation.id)
    except Exception as failed:  # noqa: BLE001 - tidying must never fail a run
        print(f"  (could not clean up after {conversation.id}: {failed})")


async def main_async(args) -> int:
    if not assistant.configured():
        print("No model is configured. Set GROQ_API_KEY.", file=sys.stderr)
        return 2

    chosen = [c for c in CASES if not args.only or args.only.lower() in c.name.lower()]
    if not chosen:
        print(f"No case matches {args.only!r}. Cases: " + ", ".join(c.name for c in CASES))
        return 2

    user = identity.local_user()
    runs: list[list[Result]] = []
    for attempt in range(args.repeat):
        if args.repeat > 1:
            print(f"\n########## run {attempt + 1} of {args.repeat} ##########")
        results = []
        for case in chosen:
            result = await run_case(case, user)
            results.append(result)
            mark = "ok  " if not result.failed else "FAIL"
            print(f"  {mark} {case.name:34s} {result.score:5.0%}  {result.seconds:6.1f}s  {result.tokens:7d} tok")
            if result.failed:
                print(f"       missed: {', '.join(result.failed)}")
                # Always, not only under --verbose. "It did not call X" is not
                # a finding on its own -- what it called instead is the finding,
                # and having to re-run the whole suite with a flag to see it
                # costs more than the line ever could.
                print(f"       steps: {' -> '.join(result.steps) or '(none)'}")
                # The reply too, for the same reason as the steps. A language
                # check that fails says "replied in ar, got en" and the reply
                # is the only thing that says whether the assistant was wrong
                # or the counting was -- and it is gone by the time you think
                # to re-run with a flag.
                print(f"       said:  {result.reply[:200]}")
            elif args.verbose:
                print(f"       said:  {result.reply[:160]}")
        runs.append(results)

    print(f"\n{'=' * 78}")
    by_case: dict[str, list[float]] = {}
    for results in runs:
        for result in results:
            by_case.setdefault(result.case, []).append(result.score)

    print(f"  {'case':34s} {'score':>7s}  {'runs':>16s}")
    for name, scores in by_case.items():
        mean = sum(scores) / len(scores)
        spread = "" if len(set(scores)) == 1 else "  varies"
        print(f"  {name:34s} {mean:7.0%}  {' '.join(f'{s:.0%}' for s in scores):>16s}{spread}")

    everything = [score for scores in by_case.values() for score in scores]
    overall = sum(everything) / len(everything)
    unstable = [name for name, scores in by_case.items() if len(set(scores)) > 1]
    print(f"\n  overall {overall:.0%} over {len(chosen)} case(s) x {args.repeat} run(s)")
    if unstable:
        print(f"  {len(unstable)} case(s) answered differently between runs: {', '.join(unstable)}")
        print("  A case that varies is an ambiguous instruction, not necessarily a bug --")
        print("  but it is what a person will hit, so it is worth reading.")

    if args.json:
        args.json.write_text(
            json.dumps(
                [[vars(r) | {"score": r.score} for r in results] for results in runs],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf8",
        )
        print(f"\n  wrote {args.json}")
    return 0 if overall >= args.floor else 1


def _use_a_scratch_database() -> Path | None:
    """Point the run at a throwaway database unless one was named.

    Every case opens questionnaires and starts conversations as the local
    stand-in, and run against the deployment's own database that is where they
    went: 140 test conversations and an account nobody had added, in the list a
    team scrolls through. `DB_PATH` set explicitly still wins, for a run that
    means to keep its record.
    """
    import os

    from src.config import settings

    if os.environ.get("DB_PATH"):
        return None
    settings.db_path = Path(tempfile.mkdtemp(prefix="eval_assistant_db_")) / "eval.db"
    return settings.db_path


def _use_a_scratch_index() -> Path | None:
    """Point the run at a copy of the index unless one was named (TD-072).

    The scratch database scoped the record, not the index. A case that has the
    assistant write an answer by hand records it in the answer memory, and that
    indexes it: into the deployment's own Chroma collection, where the memory
    adopts it into the real database the next time it is read. A copy keeps the
    retrieval the cases measure, the real corpus, and takes the writes. It is
    removed when the run ends. `CHROMA_DIR` set explicitly still wins.
    """
    import atexit
    import os
    import shutil

    from src.config import settings

    if os.environ.get("CHROMA_DIR"):
        return None
    folder = Path(tempfile.mkdtemp(prefix="eval_assistant_index_"))
    scratch = folder / "chroma_db"
    if settings.chroma_dir.exists():
        shutil.copytree(settings.chroma_dir, scratch)
    else:
        scratch.mkdir()
    settings.chroma_dir = scratch
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    return scratch


def main() -> int:
    scratch = _use_a_scratch_database()
    if scratch:
        print(f"Recording into a scratch database: {scratch}")
    index = _use_a_scratch_index()
    if index:
        print(f"Searching a copy of the index, removed afterwards: {index}")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1, help="Run every case this many times")
    parser.add_argument("--only", default="", help="Only cases whose name contains this")
    parser.add_argument("--json", type=Path, help="Write the results here")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show steps and replies")
    parser.add_argument("--floor", type=float, default=0.9, help="Exit non-zero below this overall score (default 0.9)")
    return llm.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
