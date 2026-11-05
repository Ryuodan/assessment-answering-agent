"""A person's preferences, applied to freshly drafted answers (the house style).

Moved out of `src/tools.py` in plan 029 to make room there, behaviour
unchanged; `tools.in_house_style` is still the name every caller uses.
Preferences are applied after drafting and review and never handed to the
drafter: see `src.preferences` for why.
"""

from __future__ import annotations

import asyncio

from src import preferences, progress, rewrite
from src.identity import User
from src.logs import get_logger
from src.models import AnsweredQuestion, Language
from src.selection import _has_answer

logger = get_logger(__name__)


async def in_house_style(
    user: User,
    results: list[AnsweredQuestion],
    *,
    run_id: str = "",
    language: Language | None = None,
) -> list[AnsweredQuestion]:
    """Reword freshly drafted answers to this person's preferences, if they chose any.

    Every answer keeps its draft in `drafted`, so what the rewording changed can
    be seen and undone. An answer the rewrite could not reword comes back
    exactly as drafted: preferences that fail cost the wording, never the answer.

    Public because several paths draft: questionnaire rows here, questions
    typed into the workbench, and a question asked in the assistant's
    conversation, which is answered with no file.

    `language` is the one the answers were forced into, when they were. Left
    out, the rewrite writes in each question's own language -- which would
    quietly translate an Arabic question's English answer back into Arabic.
    """
    instruction = preferences.load(user.email).instruction()
    worth = [result for result in results if _has_answer(result)]
    if not instruction or not worth:
        return results

    progress.start(run_id, stage="styling")
    progress.set_total(run_id, len(worth))
    try:

        async def one(result: AnsweredQuestion) -> AnsweredQuestion:
            try:
                styled = await rewrite.rewrite(
                    result,
                    instruction,
                    language,
                    note="Reworded to your preferences.",
                )
            except Exception:  # noqa: BLE001 - one failure is one unstyled answer
                logger.exception("styling.failed", question_id=result.question.id)
                return result
            finally:
                progress.advance(run_id)
            if styled is result:
                return result
            styled.drafted = result.answer
            return styled

        styled = {item.question.id: item for item in await asyncio.gather(*(one(r) for r in worth))}
    finally:
        progress.finish(run_id)
    return [styled.get(result.question.id, result) for result in results]
