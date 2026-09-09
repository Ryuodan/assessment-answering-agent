"""Rewording an answer that has already been written and checked.

Distinct from answering, and the distinction matters. Asking the pipeline to
"make it shorter" by running it again with a style re-retrieves, re-drafts and
re-reviews -- so the answer can come back saying something different, which is
not what anyone means by *revise*. The facts were settled the first time.

So a rewrite is one call over the answer and the sources it was already built
from: no retrieval, no review loop, and the citations come through untouched
because the evidence did not change. It is also about a fifth of the cost.

The grounding rule is the same one that governs the drafter, and it is why the
sources are passed in at all: an instruction that cannot be followed without
inventing something loses to the evidence.
"""

from __future__ import annotations

import logging

from src.graph.state import order_evidence
from src.llm import chat_llm
from src.models import AnsweredQuestion, Language
from src.prompts import BRIEF_INSTRUCTION, LANGUAGE_NAMES, REWRITE_SYSTEM, REWRITE_USER

logger = logging.getLogger(__name__)

MAX_SOURCES = 8
"""Sources shown to the rewriter. The drafter cites about this many anyway."""


def _sources_block(answered: AnsweredQuestion) -> str:
    evidence = order_evidence(answered.evidence)[:MAX_SOURCES]
    if not evidence:
        return "(none recorded)"
    return "\n\n".join(
        f"[{index}] {item.locator}\n{item.snippet}"
        for index, item in enumerate(evidence, start=1)
    )


async def rewrite(
    answered: AnsweredQuestion, instruction: str, language: Language | None = None
) -> AnsweredQuestion:
    """Reword one answer under an instruction, keeping its evidence.

    Returns a copy. On failure the original comes back unchanged rather than
    half-rewritten: a revision that fails should cost the wording, not the
    answer.
    """
    if not answered.answer.strip():
        return answered

    target = language or answered.question.language
    messages = [
        ("system", REWRITE_SYSTEM.format(language_name=LANGUAGE_NAMES[target])),
        ("user", REWRITE_USER.format(
            question=answered.question.text,
            answer=answered.answer,
            sources_block=_sources_block(answered),
            instruction=instruction,
        )),
    ]

    try:
        response = await chat_llm(temperature=0.2).ainvoke(messages)
    except Exception:
        logger.exception("Could not rewrite the answer to %s", answered.question.id)
        return answered

    text = (response.content or "").strip() if hasattr(response, "content") else ""
    if not text:
        return answered

    revised = answered.model_copy(deep=True)
    revised.answer = text
    # Evidence and citations are carried over deliberately: the sources did not
    # change, so the clause a reader would go and check has not moved either.
    revised.rationale = (
        f"{answered.rationale} Reworded on request: {instruction}".strip()
    )
    return revised


async def shorten(answered: AnsweredQuestion) -> str:
    """The same answer, condensed. Returns the text; stores nothing.

    One fixed instruction rather than free text, because the brief form has to
    be predictable: "make it shorter" gives a different length every time, and a
    person switching a 183-row questionnaire to brief is not asking for variety.

    Goes through the rewrite path, so the facts and the citations come through
    by construction. A brief answer drafted from scratch could say something the
    full one does not, and then neither is the organisation's position.
    """
    rewritten = await rewrite(answered, BRIEF_INSTRUCTION)
    return rewritten.answer
