"""Turn raw document text into structured questions or question/answer pairs.

Both extractions follow the same shape — slide a window over the document, run
one structured Groq call per window, merge and de-duplicate — so that shape
lives once in `_extract_over_windows` and the two public functions just supply a
schema and a pair of prompts.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from typing import TypeVar

from pydantic import BaseModel

from src.config import settings
from src.documents import windows
from src.llm import structured_llm
from src.models import Language, Question
from src.schemas import ExtractedQAPair, ExtractedQAPairs, ExtractedQuestions
from src.prompts import (
    QA_EXTRACTION_SYSTEM,
    QA_EXTRACTION_USER,
    QUESTION_EXTRACTION_SYSTEM,
    QUESTION_EXTRACTION_USER,
)

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Arabic block, excluding the punctuation-only ranges, used for language detection.
_ARABIC_CHARS = re.compile(r"[ء-ي٠-٩]")


async def _extract_over_windows(
    text: str,
    schema: type[SchemaT],
    system_prompt: str,
    user_template: str,
) -> list[SchemaT]:
    """Run one structured extraction per window, concurrently, dropping failures.

    A window that fails after the LLM layer's own retries is logged and skipped
    rather than failing the whole document: losing one window of a 40-page PDF
    is far better than losing the upload.
    """
    chunks = windows(text, size=settings.extraction_window)
    runnable = structured_llm(schema)
    semaphore = asyncio.Semaphore(settings.max_concurrent_questions)

    async def run(index: int, chunk: str) -> SchemaT | None:
        messages = [
            ("system", system_prompt),
            ("user", user_template.format(index=index, total=len(chunks), text=chunk)),
        ]
        async with semaphore:
            try:
                return await runnable.ainvoke(messages)
            except Exception:  # noqa: BLE001 - one bad window must not sink the document
                logger.exception("Extraction failed for window %d/%d", index, len(chunks))
                return None

    results = await asyncio.gather(*(run(i, c) for i, c in enumerate(chunks, start=1)))
    return [result for result in results if result is not None]


def detect_language(text: str) -> Language:
    """Classify text as Arabic or English by Arabic character density.

    Cheap and deterministic — an LLM call here would cost a round trip to answer
    a question that counting characters already answers.
    """
    arabic = len(_ARABIC_CHARS.findall(text))
    letters = sum(1 for char in text if char.isalpha())
    return "ar" if letters and arabic / letters > 0.3 else "en"


_LATIN_CHARS = re.compile(r"[A-Za-z]")


def detect_question_language(text: str) -> Language:
    """Which language a *single typed question* is in, when nobody said.

    Not `detect_language`, and the difference is the point. That one reads a
    whole document, where a third of the letters being Arabic means an Arabic
    document. One question is far too short for a ratio: an English question
    routinely carries an Arabic gloss -- "Do you enforce MFA (المصادقة متعددة
    العوامل)?" -- and three glossed words would tip a density test over. So the
    two scripts are counted against each other, and whichever carries the
    question carries the answer.
    """
    return "ar" if len(_ARABIC_CHARS.findall(text)) > len(_LATIN_CHARS.findall(text)) else "en"


def _normalise(text: str) -> str:
    """Collapse whitespace and case for de-duplication comparisons."""
    return re.sub(r"\s+", " ", text).strip().casefold()


async def extract_questions(text: str) -> tuple[Language, list[Question]]:
    """Extract the questions from an assessment document.

    Returns the document's dominant language and the de-duplicated questions in
    the order they appear. Overlapping windows mean the same question can be
    reported twice; the first occurrence wins.
    """
    results = await _extract_over_windows(
        text, ExtractedQuestions, QUESTION_EXTRACTION_SYSTEM, QUESTION_EXTRACTION_USER
    )

    votes: Counter[Language] = Counter()
    questions: list[Question] = []
    seen: set[str] = set()

    for window_result in results:
        votes[window_result.language] += len(window_result.questions) or 1
        for extracted in window_result.questions:
            key = _normalise(extracted.text)
            if not key or key in seen:
                continue
            seen.add(key)
            questions.append(
                Question(
                    id=extracted.number.strip() or f"q{len(questions) + 1}",
                    text=extracted.text.strip(),
                    section=extracted.section.strip() or None,
                    question_type=extracted.question_type,
                    options=[option.strip() for option in extracted.options if option.strip()],
                    language=detect_language(extracted.text),
                )
            )

    # The model's per-window vote is a sanity check; the characters on the page
    # are the ground truth, so they break ties.
    language = votes.most_common(1)[0][0] if votes else detect_language(text)
    logger.info("Extracted %d questions (language=%s)", len(questions), language)
    return language, _deduplicate_ids(questions)


def _deduplicate_ids(questions: list[Question]) -> list[Question]:
    """Make question ids unique, since documents reuse numbers across sections."""
    counts: Counter[str] = Counter()
    for question in questions:
        counts[question.id] += 1
        if counts[question.id] > 1:
            question.id = f"{question.id}-{counts[question.id]}"
    return questions


async def extract_qa_pairs(text: str) -> list[ExtractedQAPair]:
    """Extract answered question/answer pairs from a completed assessment."""
    results = await _extract_over_windows(text, ExtractedQAPairs, QA_EXTRACTION_SYSTEM, QA_EXTRACTION_USER)

    pairs: list[ExtractedQAPair] = []
    seen: set[str] = set()

    for window_result in results:
        for pair in window_result.pairs:
            question = pair.question.strip()
            answer = pair.answer.strip()
            key = _normalise(question)
            if not question or not answer or key in seen:
                continue
            seen.add(key)
            pairs.append(ExtractedQAPair(question=question, answer=answer, section=pair.section.strip()))

    logger.info("Extracted %d question/answer pairs", len(pairs))
    return pairs
