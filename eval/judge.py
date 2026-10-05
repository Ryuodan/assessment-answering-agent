"""LLM-as-judge scoring against the golden set's expected core facts.

The rubric is the one the human evaluator used: 0-5 per case, rolled up by
category. Two things keep it honest.

**A different model does the grading.** The judge runs on `EVAL_JUDGE_MODEL`,
not the model that wrote the answer, so a wrong answer is not graded by the
system that is confident about it.

**The facts are supplied, not remembered.** The judge marks which of the
listed core facts the answer actually states, and the score follows from that
plus any contradiction it finds. It is not asked what the policy says, only
whether the answer says what the golden set already established.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from src.config import settings
from src.llm import structured_llm

from eval.dataset import GoldenCase, ScoredAnswer

logger = logging.getLogger(__name__)


class Judgement(BaseModel):
    """One graded answer."""

    decisive_fact_numbers: list[int] = Field(
        default_factory=list,
        description="The numbers of the expected facts that directly answer the question as asked",
    )
    covered_fact_numbers: list[int] = Field(
        default_factory=list,
        description="The numbers of the expected facts the answer actually states",
    )
    contradicted_fact_numbers: list[int] = Field(
        default_factory=list,
        description="The numbers of the expected facts the answer states something incompatible with",
    )
    unverified_claims: list[str] = Field(
        default_factory=list,
        description="Specifics the answer asserts that no listed fact confirms or denies",
    )
    score: int = Field(ge=0, le=5, description="0-5 on the rubric in the system prompt")
    justification: str = Field(default="", description="One or two sentences, in English")


JUDGE_SYSTEM = """You grade answers written by a compliance assistant against a golden reference.

You are given a question, the core facts a correct answer draws on, the grader's notes, and the answer the system produced. The core facts were verified against the source policies by a human. Treat them as true.

What you are grading is an answer written into a vendor security assessment: two to five sentences that a human reviewer will sign off. It is NOT an extract of everything the policy says on the topic. Brevity is correct behaviour. Do not deduct for facts the question did not ask about.

Work in this order.

1. `decisive_fact_numbers` — the facts that directly answer the question as asked. These are the values, deadlines, frequencies, actors or explicit absences a reviewer would call the answer wrong for missing. Most questions have one to four. Everything else on the list is supporting context, including procedural follow-ups such as "request this from the compliance function".

2. `covered_fact_numbers` — every listed fact the answer states, decisive or not. A fact counts as stated when the answer conveys the same substance; different wording, paraphrase and a different clause reference all still count. It does NOT count when the answer gestures at the topic without the specific value, deadline, frequency or actor the fact carries.

3. `contradicted_fact_numbers` — listed facts the answer states something incompatible with: a different value for the same control, or a claim that the policy is silent where the fact records that it is not.

4. `unverified_claims` — specifics the answer asserts that no listed fact either confirms or denies. Record them; do NOT score them. The fact list is known to be incomplete, so an unlisted specific is as likely to be a real clause the list missed as an invention, and you cannot tell which from here. This field is a queue for a human, not a penalty.

5. `score`, driven by coverage and contradiction only:
- 5: every decisive fact is stated, and no listed fact is contradicted. Missing supporting facts does not stop an answer scoring 5, and neither does an unverified claim.
- 4: every decisive fact is stated, but the answer is vaguer than the sources allow, or omits supporting context a reviewer would expect.
- 3: one decisive fact is missing, or a supporting fact is contradicted; the rest is correct.
- 2: more than one decisive fact is missing, or the answer is too vague to be usable as a response.
- 1: a decisive fact is contradicted — a wrong value for the control asked about.
- 0: the answer claims the policy does not specify something a decisive fact shows it does specify, or it does not address the question at all.

Two rules override the scale:
- Where a core fact records that something is NOT in the documentation, saying so plainly is the decisive fact. An answer that states the absence and supplies whatever related material IS documented scores 5.
- Stating a correct fact the golden list happens to omit is never a penalty.

Keep `justification` to one or two sentences."""

JUDGE_USER = """QUESTION ({category}, {language})
{question}

EXPECTED CORE FACTS
{facts}

GRADER'S NOTES
{notes}

ANSWER PRODUCED BY THE SYSTEM
{answer}"""


async def judge_case(case: GoldenCase, answer: ScoredAnswer | None) -> Judgement:
    """Grade one answer. A missing answer is a zero, not an error."""
    if answer is None or not answer.answer.strip():
        return Judgement(score=0, justification="No answer was produced for this question.")

    facts = "\n".join(f"{index}. {fact}" for index, fact in enumerate(case.expected_core_facts, start=1))
    messages = [
        ("system", JUDGE_SYSTEM),
        (
            "user",
            JUDGE_USER.format(
                category=case.category,
                language=case.question_language,
                question=case.question,
                facts=facts or "(none recorded)",
                notes=case.evaluator_notes or "(none)",
                answer=answer.answer,
            ),
        ),
    ]
    return await structured_llm(Judgement, temperature=0.0, model=settings.eval_judge_model).ainvoke(messages)


async def judge_all(pairs: list[tuple[GoldenCase, ScoredAnswer | None]], concurrency: int = 4) -> list[Judgement]:
    """Grade every pair, bounded so the judge does not trip Groq's rate limit."""
    semaphore = asyncio.Semaphore(concurrency)

    async def run(case: GoldenCase, answer: ScoredAnswer | None) -> Judgement:
        async with semaphore:
            try:
                return await judge_case(case, answer)
            except Exception as exc:  # noqa: BLE001 - one ungradeable case must not lose the run
                logger.exception("Judging %s failed", case.test_id)
                return Judgement(score=0, justification=f"Judging failed: {exc}")

    return list(await asyncio.gather(*(run(case, answer) for case, answer in pairs)))
