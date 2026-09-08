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
import asyncio
import functools
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print = functools.partial(print, flush=True)  # noqa: A001

# Half the cases are in Arabic, and a Windows console defaults to a codepage
# that cannot encode it -- so `--verbose`, the one flag you reach for to find
# out why an Arabic case failed, died with a UnicodeEncodeError before printing
# the reply. Replacement rather than strict: a mangled character in a diagnostic
# line is a nuisance, and a crash in the middle of a suite is an hour.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src import batches, conversations, identity, tools           # noqa: E402
from src.agents import assistant                                  # noqa: E402
from src.conversations import Conversation                        # noqa: E402
from tests import forms_fixtures as shapes                        # noqa: E402

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
        says=["Do we encrypt customer data at rest? Just show me what the policy "
              "says — do not write me an answer."],
        wants=("search_policies",),
        forbids=("answer_directly", "answer_questions"),
        answered=0,
        upload_on=-1,
    ),
    Case(
        name="answer-it-properly-overrides-looking-up",
        says=["What does our policy say about password length? Answer it properly, "
              "the way we would put it to an assessor."],
        wants=("answer_directly",),
        forbids=("answer_questions",),
        answered=0,
        upload_on=-1,
        # One incidental search is forgivable; falling back into pure lookup
        # and never drafting is the regression, and `wants` catches that.
        at_most={"search_policies": 1},
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
    path = (getattr(shapes, case.shape)(workspace / "HR Assessment.xlsx")
            if case.upload_on >= 0 else None)

    conversation: Conversation = assistant.start(user, "")
    for index, says in enumerate(case.says):
        turn = await assistant.say(
            user, conversation, says, upload=path if index == case.upload_on else None
        )
        result.steps.extend(turn.steps)
        result.reply = turn.reply
        result.seconds += turn.seconds
        result.tokens += turn.input_tokens + turn.output_tokens

    called = {step.split("(", 1)[0] for step in result.steps}
    for wanted in case.wants:
        (result.passed if wanted in called else result.failed).append(f"called {wanted}")
    for forbidden in case.forbids:
        (result.failed if forbidden in called else result.passed).append(
            f"did not call {forbidden}"
        )

    for name, ceiling in (case.at_most or {}).items():
        used = sum(1 for step in result.steps if step.split("(", 1)[0] == name)
        (result.passed if used <= ceiling else result.failed).append(
            f"called {name} at most {ceiling}x" if used <= ceiling
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
            "gave the right count" if said
            else "did not say any of " + ", ".join(repr(w) for w in case.reply_has)
        )

    if case.reply_in:
        spoken = _language(result.reply)
        (result.passed if spoken == case.reply_in else result.failed).append(
            f"replied in {case.reply_in}" if spoken == case.reply_in
            else f"replied in {case.reply_in}, got {spoken}"
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
            print(f"  {mark} {case.name:34s} {result.score:5.0%}  "
                  f"{result.seconds:6.1f}s  {result.tokens:7d} tok")
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
        print(f"  {name:34s} {mean:7.0%}  "
              f"{' '.join(f'{s:.0%}' for s in scores):>16s}{spread}")

    everything = [score for scores in by_case.values() for score in scores]
    overall = sum(everything) / len(everything)
    unstable = [name for name, scores in by_case.items() if len(set(scores)) > 1]
    print(f"\n  overall {overall:.0%} over {len(chosen)} case(s) x {args.repeat} run(s)")
    if unstable:
        print(f"  {len(unstable)} case(s) answered differently between runs: {', '.join(unstable)}")
        print("  A case that varies is an ambiguous instruction, not necessarily a bug --")
        print("  but it is what a person will hit, so it is worth reading.")

    if args.json:
        args.json.write_text(json.dumps(
            [[vars(r) | {"score": r.score} for r in results] for results in runs],
            indent=2, ensure_ascii=False,
        ), encoding="utf8")
        print(f"\n  wrote {args.json}")
    return 0 if overall >= args.floor else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1, help="Run every case this many times")
    parser.add_argument("--only", default="", help="Only cases whose name contains this")
    parser.add_argument("--json", type=Path, help="Write the results here")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show steps and replies")
    parser.add_argument("--floor", type=float, default=0.9,
                        help="Exit non-zero below this overall score (default 0.9)")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
