"""A question answered in the chat reaches the page as its answer card (plan 030).

The model was handed the drafted answer and wrote the reply in its own words:
six of twelve stored direct answers were paraphrased, and once, in Arabic, the
reply contradicted a correct draft. Under the reply were the first six chunks
the answer carried, not the clauses it cited. Now each drafted answer rides on
the reply word for word, with its status, its confidence and only the clauses
it cites, is stored with it, and the model is told not to restate it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from src import conversations, identity, service
from src.agents import assistant
from src.api import app
from src.config import settings
from src.models import AnsweredQuestion, Evidence, SourceType
from tests.test_assistant import _graph, _stops_after

ASKED = {
    "en": (
        "Do we encrypt our backups?",
        "Yes. Backups are encrypted at rest with AES-256, and the keys are rotated every year.",
    ),
    "ar": (
        "هل نقوم بتشفير النسخ الاحتياطية؟",
        "نعم، تُشفَّر النسخ الاحتياطية أثناء التخزين باستخدام AES-256، وتُدوَّر المفاتيح سنوياً.",
    ),
}
REASONS = ["the sources disagree: one policy says ninety days, another a year"]
WHY_LOW = "the reviewer did not find every claim in the sources"


def _clause(n: int, *, product_id: str = "") -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE,
        source_name=f"Backup Policy {n}.pdf",
        snippet=f"Clause {n}: backups are encrypted at rest and their keys are rotated.",
        clause=f"{n}.1",
        chunk=n,
        product_id=product_id,
    )


# Seven cited, more than the six that used to be shown, and one the answer
# carried without citing it, second in the list where "the top six" took it.
CITED = [_clause(n, product_id="p-ole5" if n == 3 else "") for n in (1, 3, 4, 5, 6, 7, 8)]
UNCITED = _clause(2)


@pytest.fixture
def drafts(monkeypatch):
    """The pipeline, standing in: a flagged answer citing seven clauses, carrying an eighth it does not cite."""

    async def fake(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=question,
                answer=dict(ASKED.values())[question.text],
                rationale="Two policies give different retention periods.",
                confidence=0.55,
                needs_review=True,
                review_reasons=REASONS,
                confidence_reason=WHY_LOW,
                evidence=[CITED[0], UNCITED, *CITED[1:]],
                citations=[item.locator for item in CITED],
            )
            for question in questions
        ]

    monkeypatch.setattr(service, "answer_questions", fake)


@pytest.fixture
def chat(monkeypatch, drafts):
    """The chat route, its model scripted to answer the question it is asked with `answer_directly`."""
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")

    def ask(client: TestClient, question: str) -> dict:
        script = [("answer_directly", {"questions": question})]
        monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph(script)(tools))
        response = client.post("/api/chat", json={"message": question, "product": ""})
        assert response.status_code == 200, response.text
        return response.json()

    return ask


@pytest.mark.parametrize("language", ["en", "ar"])
def test_a_drafted_answer_reaches_the_reply_as_its_card_word_for_word(chat, language):
    question, answer = ASKED[language]

    with TestClient(app) as client:
        said = chat(client, question)

    [card] = said["direct_answers"]
    assert card["answer"] == answer, "word for word: not translated, not reworded"
    assert card["question"]["text"] == question and card["question"]["language"] == language
    assert card["needs_review"] is True and card["confidence"] == 0.55
    assert card["review_reasons"] == REASONS and card["confidence_reason"] == WHY_LOW
    assert card["citations"] == [item.locator for item in CITED]
    assert [item["locator"] for item in card["evidence"]] == [item.locator for item in CITED], "cited only"
    assert [item["product_id"] for item in card["evidence"]] == [item.product_id for item in CITED]
    assert said["reply"] == "Done.", "the model's own words lead into the card"


@pytest.mark.parametrize("language", ["en", "ar"])
def test_the_sources_under_the_reply_are_the_clauses_it_cited(chat, language):
    """Not the first six it carried: the seventh cited clause was missing, and an uncited one shown."""
    with TestClient(app) as client:
        said = chat(client, ASKED[language][0])

    assert [source["locator"] for source in said["sources"]] == [item.locator for item in CITED]
    assert UNCITED.locator not in [source["locator"] for source in said["sources"]]


@pytest.mark.parametrize("language", ["en", "ar"])
def test_the_card_is_stored_with_the_reply_and_handed_back_when_reopened(chat, language):
    question, answer = ASKED[language]
    with TestClient(app) as client:
        said = chat(client, question)
        reopened = client.get(f"/api/chat/{said['conversation_id']}").json()

    saved = conversations.load(said["conversation_id"])
    reply = [m for m in saved.messages if isinstance(m, AIMessage) and not m.tool_calls][-1]
    assert reply.additional_kwargs[assistant.UI_KEY]["direct_answers"] == said["direct_answers"]
    [replied] = [m for m in reopened["messages"] if m["role"] == "assistant"]
    assert replied["direct_answers"] == said["direct_answers"]
    assert replied["direct_answers"][0]["answer"] == answer


def test_a_conversation_stored_before_cards_opens_without_them():
    """Its replies carry steps and sources and nothing else: they are drawn as they always were."""
    user = identity.local_user()
    conversation = assistant.start(user, "Do we encrypt our backups?")
    ui = {"steps": ["answer_directly(1 question(s))"], "sources": [], "at": "2026-11-01T09:00:00Z", "changed": False}
    conversation.messages = [
        HumanMessage("Do we encrypt our backups?"),
        AIMessage("Yes, backups are encrypted.", additional_kwargs={assistant.UI_KEY: ui}),
    ]
    conversations.save(conversation)

    with TestClient(app) as client:
        reopened = client.get(f"/api/chat/{conversation.id}").json()

    [replied] = [m for m in reopened["messages"] if m["role"] == "assistant"]
    assert replied["text"] == "Yes, backups are encrypted."
    assert replied["direct_answers"] == []


async def test_the_model_is_told_the_card_shows_the_answer_and_not_to_restate_it(drafts):
    """In the result, where it decides what to reply, in the tool's description, and in the prompt."""
    state: dict = {"batch_id": "", "pending_upload": "", "steps": []}
    tool = {t.__name__: t for t in assistant._tools(identity.local_user(), state)}

    said = " ".join((await tool["answer_directly"](ASKED["en"][0])).split())

    assert f"on the person's screen as a card exactly as drafted (do not restate it): {ASKED['en'][1]}" in said
    assert "Your reply is one short sentence that leads into the card." in said
    assert "Do not repeat an answer in your reply, restated, translated or summarised" in said
    assert "relay" not in said.casefold()
    described = " ".join(tool["answer_directly"].__doc__.split())
    assert "shown to the person under your reply as an answer card, exactly as drafted" in described
    prompt = " ".join(assistant.SYSTEM.split())
    assert "shown to the person under your reply as an answer card, exactly as drafted" in prompt
    assert "Do not repeat the drafted text in your reply, restated, translated or summarised" in prompt
    assert "Relay what it hands back word for word" not in prompt
    # Not "reword": told never to reword an answer, the model stopped calling reword_answers
    # for "answer them all, one short sentence each" (plan 031's evaluation: 1 run in 4).
    assert "reword" not in prompt.split("`answer_directly` is the only way", 1)[1].split("`reword_answers` still")[0]
    assert "reword" not in said.split("Each answer above", 1)[1]


async def test_a_turn_that_stops_after_drafting_keeps_its_cards(drafts, monkeypatch):
    """The stopped reply counts what was drafted, and the cards under it show it (the review of plan 030)."""
    user = identity.local_user()
    question, answer = ASKED["en"]
    monkeypatch.setattr(assistant, "_agent", _stops_after([("answer_directly", {"questions": question})]))
    conversation = assistant.start(user, "")

    turn = await assistant.say(user, conversation, question)

    assert turn.stopped_early and answer not in turn.reply and "shown below" in turn.reply
    assert [card["answer"] for card in turn.direct_answers] == [answer]
    saved = conversations.load(conversation.id)
    reply = [m for m in saved.messages if assistant._said(m)][-1]
    assert reply.additional_kwargs[assistant.UI_KEY]["direct_answers"] == turn.direct_answers


async def test_a_question_that_could_not_be_answered_is_a_card_saying_so(monkeypatch):
    async def failing(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(question=q, answer="", confidence=0.0, needs_review=True, error="rate limited")
            for q in questions
        ]

    monkeypatch.setattr(service, "answer_questions", failing)
    state: dict = {"batch_id": "", "pending_upload": "", "steps": []}
    tool = {t.__name__: t for t in assistant._tools(identity.local_user(), state)}

    said = await tool["answer_directly"]("Do we encrypt our backups?")

    assert "could not be answered: rate limited" in said
    [card] = state["direct_answers"]
    assert card["error"] == "rate limited" and card["answer"] == "" and card["evidence"] == []
    assert not state.get("sources") and not state.get("drafted"), "nothing to relay, and nothing cited"


@pytest.mark.parametrize(
    "reason",
    [
        "nothing in our documents backs this — it rests only on what we told somebody before",
        "we are not consistent about this: the memory says otherwise",
    ],
    ids=["only-previous-answers", "sources-disagree"],
)
def test_a_held_answer_is_said_to_be_held_for_the_reason_its_card_shows(reason):
    """A well-rated answer held by a check has no "why the score is low" sentence since
    plan 030, and the model was told it was held for "low confidence" while its card
    said "Sources disagree" (the review of plan 030)."""
    from src.agents import assistant_cards, assistant_stopped
    from src.models import Question

    held = AnsweredQuestion(question=Question(id="q1", text="Do we encrypt backups?"), answer="Yes.", confidence=0.6,
                            needs_review=True, review_reasons=[reason], confidence_reason="")  # fmt: skip

    assert assistant_stopped.held_because(held) == reason
    assert f"flagged for review: {reason}" in assistant_cards.handed_back({}, [held])
    assert "low confidence" not in assistant_cards.handed_back({}, [held])
