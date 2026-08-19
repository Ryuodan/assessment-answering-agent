"""The golden question set, and the answer files scored against it.

One loader for both, because the point of this harness is to score the current
system and the two archived runs the same way. If the judge disagrees with the
human grades on the archived runs, the judge is what needs fixing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from src.config import PROJECT_ROOT
from src.models import Question, QuestionType

# The extended golden set: the original 28 cases plus the ones covering the NCA
# ECC guide and the SDAIA PDPL material added to the knowledge base. Kept here
# rather than beside the archived runs because it now describes this system's
# corpus, not the one the two archived runs were measured on.
#
# `previous_results/golden_test_dataset.json` remains the original 28 and is
# what the archived old/new runs should still be scored against.
DEFAULT_GOLDEN_SET = PROJECT_ROOT / "eval" / "golden_set.json"
ORIGINAL_GOLDEN_SET = PROJECT_ROOT.parent.parent / "previous_results" / "golden_test_dataset.json"


class GoldenCase(BaseModel):
    """One graded question: what was asked, and what a correct answer must say."""

    test_id: str
    category: str
    question_language: str = "en"
    question: str
    expected_core_facts: list[str] = Field(default_factory=list)
    source_reference: str = ""
    evaluator_notes: str = ""

    def as_question(self, index: int) -> Question:
        """The question in the form the answering graph expects."""
        return Question(
            id=str(index + 1),
            text=self.question,
            question_type=QuestionType.FREE_TEXT,
            language="ar" if self.question_language.startswith("ar") else "en",
        )


class ScoredAnswer(BaseModel):
    """One answer pulled out of a run, ready to be judged."""

    question: str
    answer: str
    confidence: float = 0.0
    needs_review: bool = False
    citations: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


def load_golden_set(path: Path | str = DEFAULT_GOLDEN_SET) -> list[GoldenCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [GoldenCase.model_validate(case) for case in payload]


def load_answers(path: Path | str) -> list[ScoredAnswer]:
    """Read an answers file written by this harness or by an archived run."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    # `eval/run_eval.py --runs N` in the old harness wrote a list of runs; the
    # service writes a single AssessmentResult. Accept both, take the first run.
    if isinstance(payload, list):
        payload = payload[0]

    return [
        ScoredAnswer(
            question=entry["question"]["text"] if isinstance(entry.get("question"), dict) else entry.get("question", ""),
            answer=entry.get("answer", ""),
            confidence=float(entry.get("confidence", 0.0)),
            needs_review=bool(entry.get("needs_review", False)),
            citations=list(entry.get("citations") or []),
            sources=sorted({item.get("source_name", "") for item in entry.get("evidence") or []}),
        )
        for entry in payload["answers"]
    ]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def align(cases: list[GoldenCase], answers: list[ScoredAnswer]) -> list[tuple[GoldenCase, ScoredAnswer | None]]:
    """Pair each golden case with the answer to the same question.

    Matched on question text rather than position, because a run that drops or
    reorders a question would otherwise silently grade every later answer
    against the wrong expectations. Position is the fallback only when the text
    does not match anything, which is what a paraphrased extraction looks like.
    """
    by_text = {_normalise(answer.question): answer for answer in answers}
    used: set[int] = set()
    pairs: list[tuple[GoldenCase, ScoredAnswer | None]] = []

    for index, case in enumerate(cases):
        match = by_text.get(_normalise(case.question))
        if match is None and index < len(answers) and index not in used:
            match = answers[index]
        if match is not None:
            used.add(answers.index(match))
        pairs.append((case, match))

    return pairs
