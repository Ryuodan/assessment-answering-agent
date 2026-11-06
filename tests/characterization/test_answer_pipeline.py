"""One question through the whole answering pipeline, with the model scripted.

`service.answer_questions` is the entry point the workbench, the assistant and
the evaluation all reach. Here it runs the real graph -- plan, retrieve,
rerank, draft, review, finalize -- over a real chunked policy in the fake
vector store, with every model call answered from a script. Pinned: every
prompt the model is sent (the prompts are behaviour too), and the answer that
comes out: text, confidence, review flags, citations, evidence.

Two paths: the reviewer accepts the first draft; and the reviewer rejects it
with a refined query, which sends the question round retrieval a second time.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src import knowledge, organisation, service
from src.graph import nodes
from src.models import Question
from src.schemas import AnswerReview, DraftedAnswer
from tests.conftest import build_store

POLICY = """# Access Control Policy

## 3.4 Access revocation

3.4.1 Line managers notify the IT service desk of every leaver before the leaver's last working day.

3.4.2 All logical access of a leaver is revoked within 24 hours of the end of employment.

3.4.3 Privileged accounts of a leaver are disabled immediately on the last working day.

## 3.5 Access reviews

3.5.1 User access rights are reviewed every quarter by the system owner.

3.5.2 Privileged access rights are reviewed every month.
"""

QUESTION = Question(id="Q7", text="How quickly is a leaver's access revoked, and who is notified?", language="en")


class ScriptedModel:
    """Answers each model call from a script, and records what it was sent."""

    def __init__(self, plans: list[str], drafts: list[DraftedAnswer], reviews: list[AnswerReview]):
        self.queue: dict[str, deque[Any]] = {
            "plan": deque(plans),
            DraftedAnswer.__name__: deque(drafts),
            AnswerReview.__name__: deque(reviews),
        }
        self.calls: list[dict[str, Any]] = []

    def _runnable(self, step: str, wrap: Any = None) -> Any:
        model = self

        class Runnable:
            async def ainvoke(self, messages: list[tuple[str, str]], config: Any = None) -> Any:
                model.calls.append({"step": step, "messages": [list(m) for m in messages]})
                reply = model.queue[step].popleft()
                return wrap(reply) if wrap else reply

        return Runnable()

    def chat_llm(self, temperature: float | None = None, model: str | None = None) -> Any:
        return self._runnable("plan", wrap=lambda text: AIMessage(content=text))

    def structured_llm(self, schema: type, temperature: float | None = None, model: str | None = None) -> Any:
        return self._runnable(schema.__name__)


@pytest.fixture
def pipeline(monkeypatch, default_settings):
    store, fake = build_store(POLICY, source_name="Access Control Policy.pdf", chunk_size=default_settings.chunk_size)
    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None: store)
    # The profile is read from data/organisation.json, which tests must not
    # depend on (TD-023): pin the built-in default.
    monkeypatch.setattr(organisation, "load", lambda *args, **kwargs: organisation.Organisation())

    def run(model: ScriptedModel, staged: list[int]) -> dict[str, Any]:
        monkeypatch.setattr(nodes, "chat_llm", model.chat_llm)
        monkeypatch.setattr(nodes, "structured_llm", model.structured_llm)
        fake.stage(chunk_indexes=staged, score=0.71)
        [answered] = service_answer([QUESTION])
        return {
            "chunks": [{"text": r["text"], "metadata": r["metadata"]} for r in fake.records],
            "calls": model.calls,
            "answered": answered.model_dump(mode="json"),
            "unused_script": {step: len(queue) for step, queue in model.queue.items() if queue},
        }

    return run, fake


def service_answer(questions: list[Question]) -> list[Any]:
    import asyncio

    return asyncio.run(service.answer_questions(questions))


def test_a_grounded_first_draft(pipeline, snapshot):
    run, fake = pipeline
    model = ScriptedModel(
        plans=["leaver access revocation timeframe\nleaver notification IT service desk"],
        drafts=[
            DraftedAnswer(
                answer="All access is revoked within 24 hours of the end of employment, and privileged accounts "
                "are disabled on the last working day [1]. Line managers notify the IT service desk before then [1].",
                rationale="Clauses 3.4.1 to 3.4.3.",
                confidence=0.9,
                used_source_ids=[1],
            )
        ],
        reviews=[AnswerReview(grounded=True, verdict_reason="Every claim is in 3.4.", confidence=0.88)],
    )
    result = run(model, staged=[record["metadata"]["chunk"] for record in fake.records][:1])
    assert [call["step"] for call in result["calls"]] == ["plan", "DraftedAnswer", "AnswerReview"]
    snapshot("pipeline/grounded-first-draft", result)


def test_a_rejected_draft_goes_round_again(pipeline, snapshot):
    run, fake = pipeline
    model = ScriptedModel(
        plans=["leaver access revocation"],
        drafts=[
            DraftedAnswer(answer="Access is revoked promptly.", confidence=0.5, used_source_ids=[]),
            DraftedAnswer(
                answer="All logical access is revoked within 24 hours of the end of employment [1].",
                rationale="3.4.2.",
                confidence=0.85,
                used_source_ids=[1],
            ),
        ],
        reviews=[
            AnswerReview(
                grounded=False,
                verdict_reason="'Promptly' is not in the sources.",
                confidence=0.3,
                refined_query="revocation within 24 hours end of employment",
            ),
            AnswerReview(grounded=True, verdict_reason="Matches 3.4.2.", confidence=0.85),
        ],
    )
    result = run(model, staged=[record["metadata"]["chunk"] for record in fake.records][:1])
    assert [call["step"] for call in result["calls"]] == [
        "plan",
        "DraftedAnswer",
        "AnswerReview",
        "DraftedAnswer",
        "AnswerReview",
    ]
    snapshot("pipeline/rejected-draft-retried", result)


# --- answers a check holds (plan 030) ------------------------------------------
#
# Each is held for review by a different check, at a score the models rated
# well. Pinned: the answer that comes out, and the steps the model was asked
# for. The prompts are pinned by the two paths above.

HELD = {
    "held-sources-disagree": dict(
        plans=["leaver access revocation"],
        drafts=[
            DraftedAnswer(
                answer="All logical access is revoked within 24 hours of the end of employment [1].",
                rationale="3.4.2.",
                confidence=0.95,
                used_source_ids=[1],
                contradicts_memory="A 2023 answer said access is revoked within a week; the policy says 24 hours.",
            )
        ],
        reviews=[AnswerReview(grounded=True, verdict_reason="Matches 3.4.2.", confidence=0.9)],
    ),
    "held-not-grounded": dict(
        plans=["leaver access revocation"],
        drafts=[DraftedAnswer(answer="Access is revoked promptly.", confidence=0.85, used_source_ids=[1])],
        reviews=[
            AnswerReview(
                grounded=False, verdict_reason="'Promptly' is not in the sources.", confidence=0.8, refined_query=""
            )
        ],
    ),
    "held-unsupported-clause": dict(
        plans=["leaver access revocation"],
        drafts=[
            DraftedAnswer(
                answer="All logical access is revoked within 24 hours, as §9.9 requires [1].",
                rationale="3.4.2.",
                confidence=0.9,
                used_source_ids=[1],
            )
        ],
        reviews=[AnswerReview(grounded=True, verdict_reason="Matches 3.4.2.", confidence=0.9)],
    ),
}


def held_answer(run, fake, name: str) -> dict[str, Any]:
    script = HELD[name]
    model = ScriptedModel(plans=list(script["plans"]), drafts=list(script["drafts"]), reviews=list(script["reviews"]))
    result = run(model, staged=[record["metadata"]["chunk"] for record in fake.records][:1])
    return {"steps": [call["step"] for call in result["calls"]], "answered": result["answered"]}


@pytest.mark.parametrize("name", sorted(HELD))
def test_an_answer_a_check_holds(pipeline, snapshot, name):
    run, fake = pipeline
    result = held_answer(run, fake, name)
    assert result["answered"]["needs_review"] is True
    snapshot(f"pipeline/{name}", result)
