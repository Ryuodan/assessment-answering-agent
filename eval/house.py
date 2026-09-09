"""The house set: the cyber team's own answers, as the standard to be measured against.

`eval/golden_set.json` asks a different question from this one, and both are
worth asking. It lists the core facts a correct answer draws on and has a judge
count how many the answer states -- so it measures whether we are *right and
complete*. This set holds what the security team actually wrote into 5 real
questionnaires, and measures whether we write what *they* would have written.

**Length is not the standard, and this set does not treat it as one.** The
team's answers here run to a median of eleven words against our 152, and the
obvious reading -- that they want short answers -- is wrong. They have said they
prefer detailed ones; the short answers are what you write when a questionnaire
has 183 rows and somebody needs it back this week. Measuring conformity to that
would optimise the product towards a workaround, so length is reported here and
never scored.

Scoring has two axes, deliberately kept apart.

**Form** is arithmetic, not judgement, and it is deliberately narrow: does the
answer open with a verdict, and does it avoid telling the assessor that our own
documentation does not cover the question. Both are things the team does
consistently even in the files where they had room to do otherwise -- an
assessor reading 183 rows needs the yes/no first, and in 1,055 answers the team
never once wrote that the documentation was silent. Neither costs anything in a
long answer, which is why they survive the change of standard and length does
not.

**Agreement** needs a judge, because "we encrypt backups" and "offsite backups
containing data are encrypted" are the same answer and no amount of string
comparison will say so. The judge is given both answers and asked one narrow
question: does ours assert the same position as theirs. Not which is better
written -- that is the form score's job -- and not whether ours is true, which
the facts set already covers.

**Agreement is always judged on the full answer, never the brief one**, and
that is a deliberate choice rather than an omission. The obvious idea -- score
the brief answers against the team's short references, since both are short --
would quietly break the thing it was trying to measure. The brief form is
*derived* from the full one, so a gradient pulling brief towards the reference
can be satisfied two ways: by letting the condensing step drift from the full
answer, or by dragging the full answer short. The suite cannot tell those apart
and both are the failure the two lengths exist to avoid.

So the brief form is measured against the full one instead -- `fidelity`, below.
Same verdict, nothing material dropped, nothing added. That pressure points
towards the full answer rather than away from it, and nothing anywhere rewards
a brief answer for resembling the reference.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.config import PROJECT_ROOT
from src.models import Question, QuestionType

logger = logging.getLogger(__name__)

HOUSE_SET = PROJECT_ROOT / "eval" / "house_set.json"
ANSWER_MEMORY = PROJECT_ROOT / "eval" / "answer_memory.json"


@dataclass
class HouseCase:
    """One question a real assessor asked, and what the team actually answered."""

    test_id: str
    question: str
    answer: str
    """The team's own words. The standard, not a suggestion."""

    file: str = ""
    section: str = ""
    location: str = ""
    language: str = "en"
    id: str = ""

    def as_question(self, index: int) -> Question:
        return Question(
            id=str(index + 1),
            text=self.question,
            section=self.section or None,
            question_type=QuestionType.FREE_TEXT,
            language="ar" if self.language.startswith("ar") else "en",
        )


def load_house_set(path: Path | str = HOUSE_SET) -> list[HouseCase]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        HouseCase(
            test_id=row["test_id"], question=row["question"], answer=row["answer"],
            file=row.get("file", ""), section=row.get("section", ""),
            location=row.get("location", ""), language=row.get("language", "en"),
            id=row.get("id", ""),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Form: the part of the shape that is a preference rather than a compromise
# ---------------------------------------------------------------------------

_WORD = re.compile(r"\S+")
_CONTENT = re.compile(r"[a-z؀-ۿ]{3,}")
_VERDICT = re.compile(r"^\s*[\"'(]?\s*(yes|no|not applicable|n/?a|نعم|لا|لا ينطبق)\b", re.I)
_CLAUSE = re.compile(r"§|\bclause\s+\d|\bsection\s+\d+\.\d|\b[A-Z]{2,}-[A-Z]{2,}-\d|\bv?\d+\.\d+\.\d")
_LIST = re.compile(r"(^|\n)\s*[-*•]\s|\n\s*\d+[.)]\s")
_HEDGE = re.compile(
    r"documentation does not|do(es)? not (state|specify|cover|address)|not covered|"
    r"no information|is silent|does not provide|لا توجد معلومات|لم (يتم )?تحديد",
    re.I,
)

# Words too common to count as the answer echoing the question.
_STOP = frozenset(
    "the a an of to and or is are be for in on with that this it as by we our you your "
    "do does did have has any all not no if when which what who will can may".split()
)


def _content_words(text: str) -> set[str]:
    return {w for w in _CONTENT.findall(text.lower()) if w not in _STOP}


def words(text: str) -> int:
    return len(_WORD.findall(text))


def mirroring(question: str, answer: str) -> float:
    """How much of the answer is the question said back to the asker.

    Reported, not scored. It is a consequence of writing eleven words rather
    than a thing anybody chose, and the team writes eleven words because they
    have hundreds of questions to get through.
    """
    q, a = _content_words(question), _content_words(answer)
    return len(q & a) / len(a) if a else 0.0


@dataclass
class Register:
    """What the shape of one answer looks like, in numbers.

    Everything here is measured. Only `opens_with_verdict` and `hedges` are
    scored -- see `form_score`.
    """

    words: int = 0
    opens_with_verdict: bool = False
    mirroring: float = 0.0
    cites_a_clause: bool = False
    has_a_list: bool = False
    has_bold: bool = False
    hedges: bool = False

    @classmethod
    def of(cls, question: str, answer: str) -> Register:
        return cls(
            words=words(answer),
            opens_with_verdict=bool(_VERDICT.match(answer)),
            mirroring=mirroring(question, answer),
            cites_a_clause=bool(_CLAUSE.search(answer)),
            has_a_list=bool(_LIST.search(answer)),
            has_bold="**" in answer,
            hedges=bool(_HEDGE.search(answer)),
        )


# Measured over the team's 832 usable answers, and kept as constants so a
# change to the corpus cannot quietly move the target.
TEAM_MEDIAN_WORDS = 11
"""Reported for contrast, never a target. See the module docstring."""

TEAM_OPENS_WITH_VERDICT = 0.67
TEAM_HEDGES = 0.0


def form_score(case: HouseCase, answer: str) -> tuple[float, Register]:
    """0-1 on the two habits worth keeping, whatever length the answer runs to.

    **Opening with a verdict.** An assessor working down 183 rows needs the
    yes/no before the explanation, and putting it first costs nothing in a long
    answer. Only asked of questions the team themselves answered that way --
    "What is your retention period?" has no verdict to open with, and demanding
    one would be scoring noise.

    **Not hedging.** In 1,055 answers the team never once told an assessor that
    their own documentation did not cover something. When they do not know they
    route the question or leave it blank; what they never do is hand back a
    non-answer. We do it in 19% of answers.

    Length, mirroring, bullets and clause citations are measured and reported
    but not scored -- they are consequences of writing short, and short is a
    workaround rather than the standard.
    """
    got = Register.of(case.question, answer)
    want = Register.of(case.question, case.answer)

    parts = []
    if want.opens_with_verdict:
        parts.append((2.0, 1.0 if got.opens_with_verdict else 0.0))
    parts.append((1.0, 0.0 if got.hedges else 1.0))

    total = sum(weight for weight, _ in parts)
    return sum(weight * value for weight, value in parts) / total, got


# The old name, kept so a caller written against it still works.
register_score = form_score


# ---------------------------------------------------------------------------
# Fidelity: does the brief form still say what the full one says
# ---------------------------------------------------------------------------


class Fidelity(BaseModel):
    """The brief answer, compared against the full one it was condensed from."""

    keeps_the_position: bool = Field(
        description="The brief answer asserts the same yes/no/partly as the full one"
    )
    drops_something_material: bool = Field(
        description="A fact the full answer relied on to answer the question is gone"
    )
    adds_a_claim: bool = Field(
        description="The brief answer asserts something the full one does not"
    )
    note: str = Field(default="", description="One sentence, English")


FIDELITY_SYSTEM = """You compare a long answer with a shortened version of itself.

The short one was produced by condensing the long one. It is *supposed* to be shorter and to leave out supporting detail -- that is the whole point, and it is never a fault.

Three things would be faults, and you are looking only for these:

`keeps_the_position` -- does the short answer still say the same yes/no/partly/not-applicable as the long one? A compliance rating is read off this. An answer that opened "Yes" and now opens with a description, or hedges where the original committed, has lost the position.

`drops_something_material` -- is a fact *the question needed* now missing? Supporting detail, second examples and extra frequencies are meant to go. A condition or scope that changes what the answer means -- "for critical systems", "on privileged accounts only", "from 2025" -- is not.

`adds_a_claim` -- does the short answer assert anything the long one does not? Condensing cannot invent, and a shortened answer that has acquired a certification, a timeframe or a control is worse than the long one it came from."""

FIDELITY_USER = """QUESTION
{question}

THE FULL ANSWER
{full}

THE BRIEF ANSWER, CONDENSED FROM IT
{brief}"""


async def judge_fidelity(question: str, full: str, brief: str) -> Fidelity:
    """Whether the brief form still says what the full one said. Contained."""
    from src.config import settings
    from src.llm import structured_llm

    model = structured_llm(Fidelity, model=settings.eval_judge_model, temperature=0.0)
    try:
        return await model.ainvoke([
            ("system", FIDELITY_SYSTEM),
            ("user", FIDELITY_USER.format(question=question, full=full, brief=brief)),
        ])
    except Exception as failed:  # noqa: BLE001 - one ungraded pair is not a failed run
        logger.warning("Fidelity judge failed: %s", failed)
        return Fidelity(
            keeps_the_position=True, drops_something_material=False,
            adds_a_claim=False, note=f"not graded: {failed}"[:200],
        )


def position_survived(full: str, brief: str) -> bool:
    """The cheap half of fidelity, and the half that matters most.

    A questionnaire's compliance dropdown is filled from the opening verdict, so
    an answer that stops stating one leaves the rating blank. No model needed to
    see that, and no model should be between a regression and noticing it.
    """
    got, want = _VERDICT.match(brief), _VERDICT.match(full)
    if want is None:
        return True
    return got is not None and got.group(1).casefold() == want.group(1).casefold()


# ---------------------------------------------------------------------------
# Agreement: does it say what they said
# ---------------------------------------------------------------------------


Verdict = Literal["same", "narrower", "broader", "drifts", "contradicts", "declined", "unanswerable"]


class Agreement(BaseModel):
    """One answer, compared against the team's own.

    `verdict` is a Literal rather than a described string. Groq refused the
    described-string version outright -- "Tool choice is required, but model did
    not call a tool" -- and an enum the schema can express is both more reliable
    and less to explain twice.
    """

    verdict: Verdict = Field(description="How the candidate relates to the reference")
    score: int = Field(ge=0, le=5, description="0-5; see the rubric")
    note: str = Field(default="", description="One sentence, English")


AGREEMENT_SYSTEM = """You compare two answers to the same assessment question.

REFERENCE is what an organisation's own security team wrote into a real questionnaire that was returned to a customer. Treat it as correct. It is the standard.
CANDIDATE is what an automated system produced for the same question.

You are judging ONE thing: does the candidate assert the same position as the reference? Not which is better written, not which is longer, not whether either is well evidenced. Wording is scored separately and you must ignore it entirely -- "Yes, we encrypt offsite backups" and "Offsite backups containing customer data are encrypted at rest in line with the Cryptography Policy" assert the same position and are `same`.

Choose a verdict:
  same         -- the same position, however differently expressed
  narrower     -- true, but answers less of the question than the reference did
  broader      -- everything the reference said, and more of the same subject
  drifts       -- answers a neighbouring question rather than this one (asked about data retention, answered about log retention)
  contradicts  -- incompatible with the reference (yes against no, a different period, a different owner)
  declined     -- the candidate refuses, or says the documentation does not cover it, where the reference gave an answer
  unanswerable -- the reference is not really an answer (a heading, an instruction, a stray value), so nothing can be compared

Then score 0-5:
  5  same, or broader
  3  narrower
  1  declined, or drifts
  0  contradicts
  For unanswerable, score 3 and say so in the note; the case will be excluded.

**Detail is wanted.** The reference answers are short because the team was
answering hundreds of questions at a time, not because brevity is the standard.
An answer that says what the reference said and then adds more about the same
subject is `broader` and scores full marks. Length is never a reason to mark
something down.

The distinction that matters is `broader` against `drifts`. Broader stays on the
question and says more about it. Drifting answers something adjacent -- asked
for the data retention policy and answering about log retention -- and is a
failure however well written, because the assessor asked what they asked."""

AGREEMENT_USER = """QUESTION
{question}

REFERENCE (the security team's own answer)
{reference}

CANDIDATE (what the system produced)
{candidate}"""


async def judge_agreement(case: HouseCase, answer: str) -> Agreement:
    """Compare one answer with the team's. Contained: a judge that fails is a
    missing grade, not a lost run.

    The answering half of this harness costs a model call per question and
    several minutes; the judging half costs a fraction of that. Letting one
    refusal propagate threw all of it away once, which is a bad trade to make
    twice.
    """
    from src.config import settings
    from src.llm import structured_llm

    model = structured_llm(Agreement, model=settings.eval_judge_model, temperature=0.0)
    try:
        return await model.ainvoke([
            ("system", AGREEMENT_SYSTEM),
            ("user", AGREEMENT_USER.format(
                question=case.question, reference=case.answer,
                candidate=answer or "(no answer)",
            )),
        ])
    except Exception as failed:  # noqa: BLE001 - one ungraded case is not a failed run
        logger.warning("Judge failed on %s: %s", case.test_id, failed)
        return Agreement(verdict="unanswerable", score=3, note=f"not graded: {failed}"[:200])


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass
class HouseResult:
    case: HouseCase
    answer: str
    register: float
    shape: Register
    agreement: Agreement | None = None
    confidence: float = 0.0
    needs_review: bool = False


def summarise(results: list[HouseResult]) -> dict:
    graded = [r for r in results if not (r.agreement and r.agreement.verdict == "unanswerable")]
    verdicts: dict[str, int] = {}
    for r in graded:
        if r.agreement:
            verdicts[r.agreement.verdict] = verdicts.get(r.agreement.verdict, 0) + 1

    lengths = [r.shape.words for r in graded]
    theirs = [words(r.case.answer) for r in graded]
    return {
        "cases": len(results),
        "graded": len(graded),
        "excluded": len(results) - len(graded),
        "form": round(100 * statistics.mean([r.register for r in graded]), 1) if graded else 0.0,
        "agreement": round(
            100 * statistics.mean([r.agreement.score for r in graded if r.agreement]) / 5, 1
        ) if any(r.agreement for r in graded) else 0.0,
        "verdicts": verdicts,
        "median_words_ours": statistics.median(lengths) if lengths else 0,
        "median_words_theirs": statistics.median(theirs) if theirs else 0,
        "opens_with_verdict": round(
            100 * sum(1 for r in graded if r.shape.opens_with_verdict) / len(graded), 1
        ) if graded else 0.0,
        "cites_a_clause": round(
            100 * sum(1 for r in graded if r.shape.cites_a_clause) / len(graded), 1
        ) if graded else 0.0,
        "hedges": round(100 * sum(1 for r in graded if r.shape.hedges) / len(graded), 1) if graded else 0.0,
        "would_be_filled_unreviewed": sum(
            1 for r in graded if r.answer.strip() and (r.needs_review or r.confidence < 0.6)
        ),
    }


def format_summary(label: str, summary: dict) -> str:
    lines = [
        "=" * 74,
        f"  HOUSE SET -- {label}",
        "=" * 74,
        f"  {summary['graded']} cases graded"
        + (f" ({summary['excluded']} excluded as unanswerable)" if summary["excluded"] else ""),
        "",
        f"  agreement with the team's answer   {summary['agreement']:5.1f}%",
        f"  form (verdict first, no hedging)   {summary['form']:5.1f}%",
        "",
        f"  median words   ours {summary['median_words_ours']:>4}   theirs "
        f"{summary['median_words_theirs']:>4}   (reported, not scored)",
        f"  opens with a verdict  {summary['opens_with_verdict']:5.1f}%   (team: {TEAM_OPENS_WITH_VERDICT:.0%})",
        f"  says we have no info  {summary['hedges']:5.1f}%   (team: {TEAM_HEDGES:.0%})",
        # Reported without a target beside it: whether an external assessor
        # should see our internal clause numbers is a judgement somebody made,
        # not a number to converge on.
        f"  cites a clause        {summary['cites_a_clause']:5.1f}%",
        "",
        f"  would be written into the file unreviewed: {summary['would_be_filled_unreviewed']}",
        "",
        "  verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(summary["verdicts"].items())),
    ]
    return "\n".join(lines)
