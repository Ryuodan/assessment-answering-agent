"""A question answered in the chat, shown as its answer card, in a real browser (plan 030).

The reply used to be the model's own retelling of the drafted answer, with the
first six chunks it carried under it. Now the drafted answer is drawn under the
reply as the Workbench's card, word for word, with its status, its confidence
and the clauses it cites, read-only, and drawn again when the conversation is
reopened.
"""

from __future__ import annotations

import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from playwright.sync_api import Page, expect

from src import conversations, identity, service
from src.agents import assistant, assistant_cards
from src.config import settings
from src.models import AnsweredQuestion, Evidence, Question, SourceType
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

ENGLISH = (
    "Do we encrypt our backups?",
    "Yes. Backups are encrypted at rest with AES-256, and the keys are rotated every year.",
)
ARABIC = (
    "هل نقوم بتشفير النسخ الاحتياطية؟",
    "نعم، تُشفَّر النسخ الاحتياطية أثناء التخزين باستخدام AES-256، وتُدوَّر المفاتيح سنوياً.",
)
REASON = "the sources disagree on how long backups are kept"
CHANGES = re.compile(r"^(Approve|Approved ✓|Edit|Done editing|Leave blank|Write an answer|Set aside|Full|Brief)$")


def _clause(n: int, snippet: str) -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE, source_name=f"Backup Policy {n}.pdf", snippet=snippet, clause=f"{n}.1"
    )


CITED = [_clause(1, "Backups shall be encrypted at rest using AES-256."), _clause(3, "Keys are rotated every year.")]
UNCITED = _clause(2, "Backups are kept for ninety days.")


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch):
    """The model scripted to answer what it is asked with `answer_directly`; the pipeline flags each answer."""
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")
    answers = dict([ENGLISH, ARABIC])

    async def fake(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=question,
                answer=answers[question.text],
                confidence=0.55,
                needs_review=True,
                review_reasons=[REASON],
                evidence=[CITED[0], UNCITED, CITED[1]],
                citations=[item.locator for item in CITED],
            )
            for question in questions
        ]

    monkeypatch.setattr(service, "answer_questions", fake)

    def ask(page: Page, question: str):
        script = [("answer_directly", {"questions": question})]
        monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph(script)(tools))
        page.goto("/")
        page.fill("#prompt", question)
        page.select_option("#productPick", "general")  # plan 029: a new chat's first message waits for a choice
        page.click("#send")
        expect(page.locator(".working")).to_have_count(0, timeout=30_000)
        return page.locator(".turn.assistant").last

    return ask


def test_a_question_asked_in_the_chat_is_shown_as_its_card(page: Page, asked) -> None:
    question, answer = ENGLISH
    reply = asked(page, question)

    card = reply.locator(".asked-cards .answer")
    expect(card).to_have_count(1)
    expect(card.locator(".qtext")).to_have_text(question)
    expect(card.locator(".rendered")).to_have_text(answer)
    expect(card).to_contain_text("55%")
    expect(card).to_contain_text(re.compile("needs review", re.IGNORECASE))
    expect(card).to_contain_text(REASON)
    expect(reply.locator(".bubble")).to_have_text("Done.")  # the model's words lead in; the card says the answer

    chips = card.locator(".cite")
    expect(chips).to_have_count(2)
    chips.first.click()
    expect(card.locator(".cite-panel")).to_contain_text("Backups shall be encrypted at rest using AES-256.")

    # The clauses it cited under the reply, and not the one it carried without citing.
    expect(reply.locator(".sources > summary")).to_have_text("2 sources — click to read the clauses")
    expect(reply.locator(".sources")).not_to_contain_text("Backup Policy 2.pdf")


def test_the_card_in_the_chat_is_read_only(page: Page, asked) -> None:
    """A question asked in the chat has no questionnaire to approve, edit, blank or set it aside in."""
    reply = asked(page, ENGLISH[0])

    card = reply.locator(".asked-cards .answer")
    expect(card).to_have_count(1)
    expect(card.get_by_role("button", name=CHANGES)).to_have_count(0)
    expect(card.locator(".qdelete")).to_have_count(0)
    expect(card.locator("textarea")).to_be_hidden()
    assert page.evaluate("Cards.readOnly") is False, "the page's own answers can still be changed"
    assert page.evaluate("Cards.canSetAside") is True


def test_an_arabic_answer_reads_right_to_left(page: Page, asked) -> None:
    question, answer = ARABIC
    reply = asked(page, question)

    card = reply.locator(".asked-cards .answer")
    expect(card.locator(".rendered")).to_have_text(answer)
    expect(card.locator(".rendered")).to_have_attribute("dir", "rtl")
    expect(card.locator(".qtext")).to_have_attribute("dir", "rtl")


def test_the_card_is_drawn_again_when_the_conversation_is_reopened(page: Page, asked) -> None:
    question, answer = ENGLISH
    asked(page, question)

    page.goto("/")
    page.locator("#historyList .convo", has_text=question).click()
    card = page.locator(".turn.assistant .asked-cards .answer")
    expect(card).to_have_count(1)
    expect(card.locator(".rendered")).to_have_text(answer)
    expect(card).to_contain_text("55%")
    expect(card.get_by_role("button", name=CHANGES)).to_have_count(0)


def test_a_reply_stored_before_cards_is_drawn_as_it_was_beside_one_with_a_card(page: Page) -> None:
    """A conversation carried on across the change: its earlier reply has no cards, and nothing breaks."""
    question, answer = ENGLISH
    drafted = AnsweredQuestion(
        question=Question(id="asked-1", text=question),
        answer=answer,
        confidence=0.55,
        needs_review=True,
        review_reasons=[REASON],
        evidence=CITED,
        citations=[item.locator for item in CITED],
    )
    before = {"steps": ["answer_directly(1 question(s))"], "sources": [], "at": "2026-11-01T09:00:00Z"}
    after = {**before, "direct_answers": [assistant_cards.card(drafted)]}
    conversation = assistant.start(identity.local_user(), "Do we log access?")
    conversation.messages = [
        HumanMessage("Do we log access?"),
        AIMessage("Yes, access is logged.", additional_kwargs={assistant.UI_KEY: before}),
        HumanMessage(question),
        AIMessage("Here is the drafted answer.", additional_kwargs={assistant.UI_KEY: after}),
    ]
    conversations.save(conversation)

    page.goto("/")
    page.locator("#historyList .convo", has_text="Do we log access?").click()
    earlier, later = page.locator(".turn.assistant").nth(0), page.locator(".turn.assistant").nth(1)
    expect(earlier.locator(".bubble")).to_have_text("Yes, access is logged.")
    expect(earlier.locator(".did")).to_have_count(1)
    expect(earlier.locator(".asked-cards")).to_have_count(0)
    expect(later.locator(".asked-cards .answer .rendered")).to_have_text(answer)
