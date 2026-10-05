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

import asyncio
import logging
import random
import weakref

from src.config import settings
from src.formatting import without_reasoning
from src.graph.state import order_evidence
from src.llm import TRANSIENT, chat_llm
from src.models import AnsweredQuestion, Language
from src.prompts import BRIEF_INSTRUCTION, LANGUAGE_NAMES, REWRITE_SYSTEM, REWRITE_USER

logger = logging.getLogger(__name__)

MAX_SOURCES = 8
"""Sources shown to the rewriter. The drafter cites about this many anyway."""

ATTEMPTS = 5
"""Tries per rewording when the provider says it is busy."""

_pause = asyncio.sleep
"""How a retry waits. A seam, so the tests of retrying need not sit through it."""

_gates: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _gate() -> asyncio.Semaphore:
    """The limit on rewordings in flight, one per event loop.

    Every path that rewords sends one call per answer, all at once: preferences
    over a run's drafts, the brief form over a whole file, a skill over a scope.
    Against Groq, 80 at once lost 44 to the rate limit. Per loop because a
    semaphore belongs to the loop it first waited on, and the tests and the CLI
    each run their own.
    """
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(settings.max_concurrent_rewrites)
    return gate


async def _ask(messages):
    """One model call, tried again with a growing pause while the provider is busy."""
    async with _gate():
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return await chat_llm(temperature=0.2).ainvoke(messages)
            except TRANSIENT:
                if attempt == ATTEMPTS:
                    raise
                await _pause(min(2**attempt, 20) * (0.5 + random.random()))


def _sources_block(answered: AnsweredQuestion) -> str:
    evidence = order_evidence(answered.evidence)[:MAX_SOURCES]
    if not evidence:
        return "(none recorded)"
    return "\n\n".join(f"[{index}] {item.locator}\n{item.snippet}" for index, item in enumerate(evidence, start=1))


async def rewrite(
    answered: AnsweredQuestion,
    instruction: str,
    language: Language | None = None,
    *,
    note: str = "",
) -> AnsweredQuestion:
    """Reword one answer under an instruction, keeping its evidence.

    Returns a copy. On failure the original comes back unchanged rather than
    half-rewritten: a revision that fails should cost the wording, not the
    answer -- and callers can tell the two apart by identity.

    `note` is what the reasoning records about the rewording. It defaults to
    the instruction itself, which is right for "make it shorter" and wrong for a
    two-paragraph house style that would otherwise be pasted under every answer.

    The copy is the model's words, whatever the original was. An answer a person
    wrote and then had reworded is no longer theirs, and must not reach the
    answer memory as though it were.
    """
    if not answered.answer.strip():
        return answered

    target = language or answered.question.language
    messages = [
        ("system", REWRITE_SYSTEM.format(language_name=LANGUAGE_NAMES[target])),
        (
            "user",
            REWRITE_USER.format(
                question=answered.question.text,
                answer=answered.answer,
                sources_block=_sources_block(answered),
                instruction=instruction,
            ),
        ),
    ]

    try:
        response = await _ask(messages)
    except Exception:
        logger.exception("Could not rewrite the answer to %s", answered.question.id)
        return answered

    # A rewrite is the one path that puts a model's plain text straight into an
    # answer, so it is where a reasoning model's thinking surfaced first: the
    # Brief button answered with "<think>The user wants me to rewrite...".
    text = without_reasoning(str(getattr(response, "content", "") or ""))
    if not text:
        return answered

    revised = answered.model_copy(deep=True)
    revised.answer = text
    revised.by_hand = False
    # Condensed from the words just replaced, so no longer a version of this answer.
    revised.brief = ""
    # Evidence and citations are carried over deliberately: the sources did not
    # change, so the clause a reader would go and check has not moved either.
    revised.rationale = f"{answered.rationale} {note or 'Reworded on request: ' + instruction}".strip()
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
