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

from src import identity, tools                                   # noqa: E402
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

    upload_on: int = 0
    """Which turn carries the file. Every case starts by uploading one."""


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
        name="searches-rather-than-inventing",
        says=["What does our own policy say about password length?"],
        wants=("search_policies",),
        forbids=("answer_questions",),
        answered=0,
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
    path = getattr(shapes, case.shape)(workspace / "HR Assessment.xlsx")

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
        said = any(wanted in result.reply for wanted in case.reply_has)
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
    return result


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
            if args.verbose:
                print(f"       steps: {' -> '.join(result.steps) or '(none)'}")
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
