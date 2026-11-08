"""The answer card, the review's tabs and the server's sentences, in Arabic (plan 038).

The card (`cards.js`) is drawn on the Workbench, in the chat's answers panel
and, for a source's authority, on the knowledge page. In Arabic every word it
writes is Arabic, right to left; what it shows of the questionnaire and the
answer is content, kept as it came and in its own direction, so an English
answer reads left to right. The server keeps writing English: the review's
reasons, why an answer is held back and the errors are put into Arabic in the
page (`I18n.server`, `I18n.error`), keeping what the case put into them.

Only the card and the tabs are read here (`within`): the rest of each page is
read by that page's own Arabic tests.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import errors, forms, service
from src.agents import assistant
from src.config import PROJECT_ROOT, settings
from src.graph.workflow import failed_answer
from src.models import AnsweredQuestion, Evidence, Question, SourceType
from src.selection import ready_to_write
from src.verification import (
    INCONSISTENT,
    MEMORY_ALONE,
    PARTIAL_SOURCE,
    UNGROUNDED,
    UNSUPPORTED_CLAUSES,
    explain_confidence,
)
from tests import forms_fixtures as shapes
from tests.browser.arabic import english_on_screen, expect_arabic, in_arabic
from tests.browser.choosing import choose_general
from tests.conftest import FakeVectorStore, bare_store
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

ARABIC_LETTER = re.compile(r"[؀-ۿ]")
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")

ANSWER = "Yes, multi-factor authentication is enforced for every account."
ARABIC_ANSWER = "نعم، يتم فرض المصادقة متعددة العوامل على جميع الحسابات."
NOTE = "The policy says nothing about quarterly reviews."  # the reviewer's own words: content
THEIR_WORDS = "إجابة عام 2023 قالت خلاف ذلك"  # the drafter's, in the question's language

POLICY = Evidence(
    source_type=SourceType.GUIDELINE,
    source_name="Access Control Policy.pdf",
    snippet="## 4.2 Access\n- Multi-factor authentication is enforced.\n\n| Control | Owner |\n|---|---|\n| MFA | IT |",
    score=0.82,
    clause="4.2",
)
LAW = Evidence(
    source_type=SourceType.GUIDELINE,
    source_name="PDPL.pdf",
    snippet="Article 19: the controller shall protect personal data.",
    score=0.61,
    clause="19",
    authority="external",
)
BEFORE = Evidence(
    source_type=SourceType.PRIOR_ANSWER,
    source_name="Answer memory",
    snippet="Q: Do you enforce MFA?\nA: Yes, for administrators.",
    score=0.7,
    chunk=0,
    entry_id="mem-1",
    answered_date="2026-10-01",
)
EVERY_REASON = [
    INCONSISTENT + THEIR_WORDS,
    UNGROUNDED,
    MEMORY_ALONE,
    PARTIAL_SOURCE,
    UNSUPPORTED_CLAUSES + "9.9, 5.1",
]


def made(index: int, question: Question) -> AnsweredQuestion:
    """Eight states, one a row: confident with every kind of source, held by every check,
    held for its score, failed, an Arabic answer, and three confident to approve, blank and edit."""
    if index == 0:
        sources = [POLICY, LAW, BEFORE]
        return AnsweredQuestion(
            question=question,
            answer=ANSWER,
            confidence=0.9,
            needs_review=False,
            evidence=sources,
            citations=[source.locator for source in sources],
            rationale="The access control policy states it in section 4.2.",
        )
    if index == 1:
        return AnsweredQuestion(
            question=question,
            answer=ANSWER,
            confidence=0.9,
            needs_review=True,
            review_reasons=EVERY_REASON,
            confidence_reason=explain_confidence(
                0.5, [POLICY], grounded=False, review_threshold=0.6, verdict_reason=NOTE
            ),
            evidence=[POLICY],
            citations=[POLICY.locator],
        )
    if index == 2:
        return AnsweredQuestion(question=question, answer="Probably.", confidence=0.45, needs_review=False)
    if index == 3:
        return failed_answer(question, RuntimeError("the model was unavailable"))
    if index == 4:
        return AnsweredQuestion(question=question, answer=ARABIC_ANSWER, confidence=0.9, needs_review=False)
    return AnsweredQuestion(question=question, answer=ANSWER, confidence=0.9, needs_review=False)


@pytest.fixture
def states(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(questions, language=None, run_id=None, **extra):
        return [made(index, q) for index, q in enumerate(questions)]

    async def shorten(answered):
        return "Yes."

    monkeypatch.setattr("src.tools.service.answer_questions", answered)
    monkeypatch.setattr("src.rewrite.shorten", shorten)


# --- reading the page ----------------------------------------------------------

_MARK_CARDS = """(selector) => {
  const cards = [...document.querySelectorAll(selector)];
  cards.forEach((card, at) => card.setAttribute("data-test-card", String(at)));
  return cards.length;
}"""


def cards_in_arabic(page: Page, where: str, cards: str = "#results > .answer") -> None:
    """Each card on its own: its insides are the card's, its own attributes the page's."""
    count = page.evaluate(_MARK_CARDS, cards)
    assert count, f"no cards {where}"
    for at in range(count):
        expect_arabic(page, f"{where}, card {at + 1}", within=f'[data-test-card="{at}"]')


_LAYOUT = """(selector) => {
  const problems = [];
  const page = document.documentElement;
  if (page.scrollWidth > page.clientWidth + 1) problems.push(`the page scrolls sideways: ${page.scrollWidth} > ${page.clientWidth}`);
  // The rows laid out side by side: their parts must not cover each other.
  const ROWS = ".answer-status, .card-controls, .field-label, .cites, .cite-head, .qmeta, .len-pick, .view-toggle";
  document.querySelectorAll(selector).forEach((card, n) => {
    if (!card.offsetParent) return;
    const box = card.getBoundingClientRect();
    // The card clips what does not fit: anything wider shows as its scroll width.
    if (card.scrollWidth > card.clientWidth + 1) problems.push(`card ${n} is cut off: ${card.scrollWidth} > ${card.clientWidth}`);
    card.querySelectorAll(ROWS).forEach((row) => {
      const parts = [...row.children].filter((child) => child.offsetParent && child.getClientRects().length)
        .map((child) => [child, child.getBoundingClientRect()]).filter(([, r]) => r.width && r.height);
      parts.forEach(([child, r]) => {
        if (r.left < box.left - 1 || r.right > box.right + 1) {
          problems.push(`card ${n}: ${child.className || child.tagName} "${child.textContent.slice(0, 30)}" is outside the card`);
        }
      });
      for (let i = 0; i < parts.length; i += 1) {
        for (let j = i + 1; j < parts.length; j += 1) {
          const [a, ra] = parts[i];
          const [b, rb] = parts[j];
          const wide = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
          const high = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
          if (wide > 1 && high > 1) {
            problems.push(`card ${n}: "${a.textContent.slice(0, 24)}" overlaps "${b.textContent.slice(0, 24)}" in ${row.className}`);
          }
        }
      }
    });
  });
  return problems;
}"""


def laid_out(page: Page, where: str, cards: str = "#results > .answer") -> None:
    """At 1280 px and at 375 px: nothing overlaps, nothing is cut off, nothing scrolls sideways."""
    for width, height in ((1280, 900), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(150)  # the question's clamp is measured after layout
        problems = page.evaluate(_LAYOUT, cards)
        assert not problems, f"{where} at {width} px: {problems[:10]}"
    page.set_viewport_size({"width": 1280, "height": 900})


def direction(page: Page, selector: str) -> str:
    return page.locator(selector).first.evaluate("(element) => getComputedStyle(element).direction")


def tab(page: Page, tabs: str, arabic: str):
    return page.locator(tabs).get_by_role("button", name=re.compile("^" + re.escape(arabic) + " \\("))


def card_for(page: Page, number: int, cards: str = "#results .answer"):
    return page.locator(cards, has_text=f"control number {number} documented")


# --- the Workbench -------------------------------------------------------------


def answered_on_the_workbench(page: Page, tmp_path: Path) -> None:
    in_arabic(page)
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.numbered(tmp_path / "vendor.xlsx", 8)))
    choose_general(page)
    expect(page.locator("#questionList .qrow")).to_have_count(8)
    page.click("#answerBtn")
    expect(page.locator("#reviewBar")).to_be_visible(timeout=15_000)


def test_the_workbenchs_cards_and_tabs_read_in_arabic(page: Page, tmp_path: Path, states: None) -> None:
    answered_on_the_workbench(page, tmp_path)

    # The review opens on what needs a person: held by the checks, held for its score, failed.
    expect(tab(page, "#reviewTabs", "تحتاج إلى مراجعة")).to_have_text("تحتاج إلى مراجعة (3)")
    expect(tab(page, "#reviewTabs", "ستُكتب في الملف")).to_have_text("ستُكتب في الملف (5)")
    expect(tab(page, "#reviewTabs", "الكل")).to_have_text("الكل (8)")
    expect_arabic(page, "in the tabs", within="#reviewTabs")
    expect(page.locator("#results > .answer")).to_have_count(3)
    cards_in_arabic(page, "needing review")

    held = card_for(page, 2)
    expect(held.locator(".status-word")).to_have_text("تحتاج إلى مراجعة")
    expect(held.locator(".reason-chip")).to_have_text(
        [
            "المصادر متعارضة",
            "غير مدعومة بوثائقنا",
            "مستندة إلى إجابات سابقة فقط",
            "مصدر جزئي",
            "تستشهد ببنود ليست في مصادرها",
        ]
    )
    expect(held.locator(".status-score")).to_have_text("درجة الثقة 90%")
    expect(held.locator(".card-hint")).to_have_text("لن تُكتب في الملف بعد.")
    expect(held.locator(".reasons").first).to_contain_text("لسنا متسقين في هذا: " + THEIR_WORDS)
    expect(held.locator(".reasons").first).to_contain_text("تستشهد ببنود لا تغطيها مصادرها: 9.9, 5.1")
    # The reviewer's words are kept as they came, as content in their own direction.
    note = held.locator(".reasons.why [data-no-translate]")
    expect(note).to_have_text(NOTE.rstrip("."))
    expect(note).to_have_attribute("dir", "auto")

    low = card_for(page, 3)
    expect(low.locator(".reason-chip")).to_have_text(["ثقة منخفضة"])
    expect(low.locator(".reasons").first).to_contain_text("درجة الثقة 45%، وهي لا تتجاوز حدّ 60%")
    failed = card_for(page, 4)
    expect(failed.locator(".status-word")).to_have_text("تعذّرت الإجابة")
    expect(failed.locator(".rationale")).to_have_text("تعذّرت الإجابة: the model was unavailable")
    laid_out(page, "Needs review")

    # An empty tab says where the answers are.
    tab(page, "#reviewTabs", "أنجزها شخص").click()
    expect(page.locator("#results .qlist-empty")).to_have_text(
        "لا توجد إجابات هنا. تحتاج إلى مراجعة: 3، وستُكتب في الملف: 5."
    )
    expect_arabic(page, "in an empty tab", within="#results")

    tab(page, "#reviewTabs", "ستُكتب في الملف").click()
    expect(page.locator("#results > .answer")).to_have_count(5)
    cards_in_arabic(page, "to be written")

    tab(page, "#reviewTabs", "الكل").click()
    expect(page.locator("#results > .answer")).to_have_count(8)
    cards_in_arabic(page, "all")
    laid_out(page, "All")

    # Each answer in its own direction, in a right-to-left page.
    first = card_for(page, 1)
    expect(first.locator(".rendered")).to_have_attribute("dir", "ltr")
    assert direction(page, "#results .answer >> nth=0 >> .qtext") == "ltr"
    expect(card_for(page, 5).locator(".rendered")).to_have_attribute("dir", "rtl")
    assert direction(page, "#results .answer >> nth=0 >> .answer-status") == "rtl"

    # The sources, opened, formatted and raw.
    first.locator(".cite").first.click()
    panel = first.locator(".cite-panel")
    expect(panel).to_be_visible()
    expect(panel.locator(".cite-head")).to_contain_text("الصلة 0.82")
    expect(first.locator(".tag.external").first).to_have_text("متطلب خارجي")
    cards_in_arabic(page, "with its sources open")
    assert direction(page, "#results .answer >> nth=0 >> .cite-panel .chunk") == "ltr"
    panel.get_by_role("button", name="خام").click()
    expect(panel.locator("pre.snippet")).to_be_visible()
    cards_in_arabic(page, "with the raw text")
    panel.get_by_role("button", name="منسّق").click()
    laid_out(page, "with its sources open")

    # Approved, left blank, and the editor open.
    first.get_by_role("button", name="اعتماد", exact=True).click()
    approved = page.locator("#results .answer", has=page.get_by_role("button", name="معتمدة ✓"))
    expect(approved.locator(".status-word")).to_have_text("أنجزها شخص")
    card_for(page, 7).locator(".card-more summary").click()
    card_for(page, 7).get_by_role("button", name="اتركها فارغة").click()
    blank = card_for(page, 7)
    expect(blank.locator(".status-word")).to_have_text("تُركت فارغة")
    expect(blank.locator(".rendered")).to_have_text("ستُترك هذه الإجابة فارغة.")
    editing = card_for(page, 8)
    editing.get_by_role("button", name="تعديل", exact=True).click()
    expect(editing.locator("textarea")).to_be_visible()
    expect(editing.get_by_role("button", name="إنهاء التعديل")).to_be_visible()
    cards_in_arabic(page, "approved, blank and being edited")
    laid_out(page, "approved, blank and being edited")
    editing.get_by_role("button", name="إنهاء التعديل").click()

    tab(page, "#reviewTabs", "فارغة أو مستبعدة من الملف").click()
    expect(page.locator("#results > .answer")).to_have_count(1)
    cards_in_arabic(page, "left blank")
    tab(page, "#reviewTabs", "الكل").click()

    # Brief, for the whole questionnaire.
    expect_arabic(page, "in the length and skill pickers", within="#detailPick")
    page.locator("#detailPick").get_by_role("button", name="مختصرة").click()
    expect(page.locator("#detailPick").get_by_role("button", name="مختصرة")).to_have_attribute(
        "aria-pressed", "true", timeout=15_000
    )
    expect(card_for(page, 6).locator(".rendered")).to_have_text("Yes.")
    expect_arabic(page, "with Brief chosen", within="#detailPick")
    cards_in_arabic(page, "with Brief chosen")
    laid_out(page, "with Brief chosen")


# --- the chat's answers panel ---------------------------------------------------


def test_the_chats_cards_and_tabs_read_in_arabic(page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def answer_one(question, language, *, run_id="", team_id=None):
        if "awareness training" in question.text:
            return AnsweredQuestion(
                question=question, answer=ANSWER, confidence=0.9, needs_review=True, review_reasons=[UNGROUNDED]
            )
        if "background checks" in question.text:
            return AnsweredQuestion(question=question, answer=ARABIC_ANSWER, confidence=0.45, needs_review=False)
        return AnsweredQuestion(question=question, answer=ANSWER, confidence=0.9, needs_review=False)

    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    monkeypatch.setattr(service, "answer_one_question", answer_one)
    script = [("open_questionnaire", {"file_name": ""}), ("answer_questions", {})]
    monkeypatch.setattr(assistant, "_agent", lambda tools: _graph(script)(tools))

    in_arabic(page)
    page.goto("/")
    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    page.fill("#prompt", "Answer it")
    page.select_option("#productPick", "general")
    page.click("#send")
    expect(page.locator("#answerTabs")).to_be_visible(timeout=30_000)
    expect(page.locator(".working")).to_have_count(0, timeout=30_000)

    tabs = "#answerTabs"
    expect(tab(page, tabs, "تحتاج إلى مراجعة")).to_have_text("تحتاج إلى مراجعة (2)")
    expect_arabic(page, "in the panel's tabs", within=tabs)
    expect_arabic(page, "in the panel", within="#answersPane")
    cards_in_arabic(page, "in the panel", cards="#answers > .answer")
    held = page.locator("#answers .answer", has_text=ARABIC_ANSWER)
    expect(held.locator(".rendered")).to_have_attribute("dir", "rtl")
    laid_out(page, "in the panel", cards="#answers > .answer")

    tab(page, tabs, "الكل").click()
    expect(page.locator("#answers > .answer")).to_have_count(4)
    english = page.locator("#answers .answer", has_text=ANSWER).last
    expect(english.locator(".rendered")).to_have_attribute("dir", "ltr")
    # The button is an action, the status a state: one English, two Arabic ("action|Set aside").
    english.locator(".card-more summary").click()
    english.get_by_role("button", name="استبعاد من الملف", exact=True).click()
    aside = page.locator("#answers .answer.set-aside")
    expect(aside.locator(".status-word")).to_have_text("مستبعدة من الملف")
    expect(aside.get_by_role("button", name="أدرجها في الملف مجدداً")).to_be_visible()
    expect_arabic(page, "with one set aside", within="#answersPane")
    cards_in_arabic(page, "with one set aside", cards="#answers > .answer")
    laid_out(page, "with one set aside", cards="#answers > .answer")

    tab(page, tabs, "فارغة أو مستبعدة من الملف").click()
    expect(page.locator("#answers > .answer")).to_have_count(1)
    expect_arabic(page, "in Blank or set aside", within="#answersPane")
    cards_in_arabic(page, "in Blank or set aside", cards="#answers > .answer")

    tab(page, tabs, "أنجزها شخص").click()
    expect(page.locator("#answers .tab-empty")).to_have_text(
        "لا توجد إجابات هنا. تحتاج إلى مراجعة: 2، وستُكتب في الملف: 1."
    )
    expect_arabic(page, "in an empty tab", within="#answers .tab-empty")


# --- the knowledge page ----------------------------------------------------------


def test_the_knowledge_pages_authority_badge_and_questions_read_in_arabic(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = bare_store(FakeVectorStore([]))
    law = {"source_name": "PDPL.pdf", "source_type": "guideline", "authority": "external"}
    store._store.records.append({"text": "text", "metadata": law, "id": "c1"})
    store._reset_caches()
    monkeypatch.setattr("src.knowledge.get_store", lambda team_id=None, *, product_id="": store)

    in_arabic(page)
    page.goto("/knowledge")
    page.select_option("#kbScope", "general")
    badge = page.locator("#kbSources .tag.external")
    expect(badge).to_have_text("متطلب خارجي")
    title = badge.get_attribute("title") or ""
    assert ARABIC_LETTER.search(title) and not LATIN_WORD.search(title), title

    asked = page.evaluate(
        """() => [Cards.removalQuestion("PDPL.pdf", ""), Cards.removalQuestion("PDPL.pdf", "Availo"),
                  Cards.clearQuestion(1, ""), Cards.clearQuestion(4, "Availo"), Cards.clearQuestion(0, "")]"""
    )
    assert asked[0].startswith("إزالة «PDPL.pdf» من قاعدة المعرفة المشتركة؟")
    assert asked[1].startswith("إزالة «PDPL.pdf» من قاعدة معرفة المنتج Availo؟")
    assert asked[3].startswith("إزالة جميع وثائق السياسات (4) من قاعدة معرفة المنتج Availo؟")
    for question in asked:
        left = [word for word in LATIN_WORD.findall(question) if word not in ("PDPL", "pdf", "Availo")]
        assert not left, question


# --- the server's sentences ------------------------------------------------------


def _question() -> Question:
    return Question(id="1", text="Do you enforce MFA?")


def _held(**answered) -> str:
    ready, because = ready_to_write(AnsweredQuestion(question=_question(), answer="Yes.", **answered), threshold=0.7)
    assert not ready and because
    return because


def server_sentences() -> list[tuple[str, str]]:
    """Each sentence the card shows from the server, and what it carries from the case (kept as it came)."""
    reasons = [(reason, "") for reason in (UNGROUNDED, MEMORY_ALONE, PARTIAL_SOURCE)]
    reasons += [
        (UNSUPPORTED_CLAUSES + "9.9, 5.1", ""),
        (INCONSISTENT + "a 2023 answer said otherwise", "a 2023 answer said otherwise"),
    ]
    explained = [
        (explain_confidence(0.5, [], grounded=False, review_threshold=0.7), ""),
        (
            explain_confidence(0.5, [POLICY], grounded=False, review_threshold=0.7, verdict_reason=NOTE),
            NOTE.rstrip("."),
        ),
        (explain_confidence(0.5, [POLICY, LAW, BEFORE], grounded=False, review_threshold=0.7), ""),
        (explain_confidence(0.2, [POLICY], grounded=True, review_threshold=0.7), ""),
        (explain_confidence(0.5, [POLICY], grounded=True, review_threshold=0.7), ""),
        (explain_confidence(0.5, [POLICY, LAW, BEFORE], grounded=True, review_threshold=0.7), ""),
    ]
    held = [
        (_held(error="the model was unavailable"), ""),
        (_held(needs_review=True, review_reasons=[PARTIAL_SOURCE, UNGROUNDED, UNSUPPORTED_CLAUSES + "4.4"]), ""),
        (
            _held(needs_review=True, review_reasons=[INCONSISTENT + "it said no; then yes", MEMORY_ALONE]),
            "it said no; then yes",
        ),
        (_held(needs_review=True, confidence_reason=explained[3][0]), ""),
        (_held(needs_review=True), ""),
        (_held(confidence=0.45), ""),
    ]
    failed = [(failed_answer(_question(), RuntimeError("timed out")).rationale, "timed out")]
    return reasons + explained + held + failed


def test_the_servers_sentences_read_in_arabic(page: Page) -> None:
    in_arabic(page)
    page.goto("/workbench")
    for english, kept in server_sentences():
        arabic = page.evaluate("(sentence) => I18n.server(sentence)", english)
        assert arabic != english and ARABIC_LETTER.search(arabic), f"no Arabic for {english!r}"
        rest = arabic.replace(kept, "") if kept else arabic
        assert kept in arabic, f"{english!r} lost {kept!r}: {arabic!r}"
        assert not LATIN_WORD.search(rest), f"English left in {arabic!r}"

    # The held-back reasons are the review's own, each in its Arabic, as the server joined them.
    joined = page.evaluate(
        "(sentence) => I18n.server(sentence)", _held(needs_review=True, review_reasons=[PARTIAL_SOURCE, UNGROUNDED])
    )
    assert joined == "عُلِّمت للمراجعة — " + "؛ ".join(
        page.evaluate("(reasons) => reasons.map((reason) => I18n.server(reason))", [PARTIAL_SOURCE, UNGROUNDED])
    )
    # Counted: one source, two, three.
    one, two, three = (
        page.evaluate(
            "(sentence) => I18n.server(sentence)", explain_confidence(0.5, sources, grounded=True, review_threshold=0.7)
        )
        for sources in ([POLICY], [POLICY, LAW], [POLICY, LAW, BEFORE])
    )
    assert "من مصدر واحد" in one and "من مصدرين" in two and "من 3 مصادر" in three


def test_a_reasons_own_words_are_content_on_the_card(page: Page) -> None:
    """The drafter's English in an Arabic sentence is kept, marked, and reads left to right."""
    in_arabic(page)
    page.goto("/workbench")
    page.evaluate(
        """(reasons) => {
             const card = Cards.render({
               question: { id: "1", text: "Do you enforce MFA?", question_type: "free_text" }, answer: "Yes.",
               confidence: 0.4, needs_review: true, review_reasons: reasons, citations: [],
               will_be_written: false, held_back_because: "flagged for review -- " + reasons.join("; "),
             }, 0);
             card.id = "drawn";
             document.body.append(card);
           }""",
        [INCONSISTENT + "a 2023 answer said otherwise", UNGROUNDED],
    )
    carried = page.locator("#drawn .reasons [data-no-translate]")
    expect(carried).to_have_text("a 2023 answer said otherwise")
    expect(carried).to_have_attribute("dir", "auto")
    assert english_on_screen(page, within="#drawn .answer-body") == []


def test_a_lists_tabs_say_ready_to_use(page: Page) -> None:
    """A list of questions has no file (plan 033): its confident answers are "Ready to use", in Arabic too."""
    in_arabic(page)
    page.goto("/workbench")
    drawn = page.evaluate(
        """() => {
             const tabs = document.createElement("div");
             const counted = { review: 1, written: 2, person: 1, blank: 0, all: 4 };
             Cards.fileless = true;
             try {
               Cards.reviewTabs(tabs, counted, "review", () => {});
               return [[...tabs.children].map((tab) => [tab.textContent, tab.title]),
                       Cards.emptyTab("review", counted), Cards.emptyTab("blank", counted)];
             } finally {
               Cards.fileless = false;
             }
           }"""
    )
    names, review, blank = drawn
    assert names[1] == ["جاهزة للاستخدام (2)", "إجابات واثقة لم يراجعها أحد: جاهزة للاستخدام كما صيغت في المسودة"]
    assert review == "لا توجد إجابات تحتاج إلى مراجعة. 3 إجابات جاهزة للاستخدام."
    assert blank == "لا توجد إجابات هنا. تحتاج إلى مراجعة: 1، وجاهزة للاستخدام: 3."
    for name, title in names:
        assert not LATIN_WORD.search(name + title), (name, title)


# --- the errors ------------------------------------------------------------------

ERRORS_DOC = PROJECT_ROOT / "docs" / "generated" / "errors.md"
# The modules whose errors reach a person (plan 038): the routes and what they call.
RAISING = [
    "src/routes",
    "src/api.py",
    "src/tools.py",
    "src/forms",
    "src/products.py",
    "src/identity.py",
    "src/access_codes.py",
    "src/preferences.py",
    "src/interface_language.py",
    "src/lists.py",
    "src/questionnaire.py",
    "src/retention.py",
    "src/reading.py",
    "src/knowledge.py",
    "src/busy.py",
    "src/chat_running.py",
    "src/scoped_knowledge.py",
    "src/documents.py",
]


def error_codes() -> list[str]:
    text = ERRORS_DOC.read_text(encoding="utf-8")
    codes = re.findall(r"^\| `\w+` \| \d{3} \| `(\w+)` \|", text, re.MULTILINE)  # a class's default
    codes += re.findall(r"^\| `(\w+)` \| \d{3} \|", text, re.MULTILINE)  # a raise site's, and the framework's
    return sorted({code for code in codes if code.islower()})


def fixed_messages() -> list[str]:
    """Every error raised with a sentence of its own, written out in the source."""
    names = {"AppError"} | {cls.__name__ for cls in _subclasses(errors.AppError)}
    found: set[str] = set()
    paths: list[Path] = []
    for place in RAISING:
        path = PROJECT_ROOT / place
        paths += sorted(path.glob("*.py")) if path.is_dir() else [path]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            called = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if called not in names:
                continue
            message = node.args[0]
            if isinstance(message, ast.Constant) and isinstance(message.value, str):
                found.add(message.value)
            elif isinstance(message, ast.Name) and message.id in constants:
                found.add(constants[message.id])
    return sorted(found)


def _subclasses(cls: type) -> set[type]:
    return {sub for child in cls.__subclasses__() for sub in {child} | _subclasses(child)}


def filled_messages() -> list[tuple[str, str, str]]:
    """Messages the server fills in, as it fills them: (code, message, what it keeps)."""
    supported = ", ".join(forms.SUPPORTED)
    return [
        ("operation_refused", f"No question {'Q7'!r} in this questionnaire.", "Q7"),
        ("operation_refused", f"No answer for {'Q7'!r} yet.", "Q7"),
        (
            "operation_refused",
            f"The uploaded file for {'vendor.xlsx'!r} is no longer on the server. Upload it again to fill it in.",
            "vendor.xlsx",
        ),
        (
            "questionnaire_type_unsupported",
            f".pdf is not a questionnaire this can read. Supported: {supported}.",
            "pdf",
        ),
        (
            "questionnaire_type_unsupported",
            f"That file is not a questionnaire this can read. Supported: {supported}.",
            "",
        ),
        ("document_type_unsupported", "'notes.txt' is not supported. Upload .pdf or .docx.", "notes.txt"),
        ("product_name_taken", f"This team already has a product called {'Availo'!r}.", "Availo"),
        ("access_denied", f"Too many attempts. Wait {settings.sign_in_lockout_minutes} minutes and try again.", ""),
        (
            "questionnaire_busy",
            "This questionnaire is being answered right now (3 of 10 done). Wait until it finishes, then try again.",
            "",
        ),
        ("questionnaire_unreadable", "vendor.xlsx is not a readable .xlsx file.", "vendor.xlsx"),
        (
            "questionnaire_unreadable",
            "vendor.xlsx holds 500,000 cells, past the 400,000 this reads. Split it into smaller files.",
            "vendor.xlsx",
        ),
        ("no_questions_found", "No questions could be extracted from 'vendor.xlsx'.", "vendor.xlsx"),
        (
            "product_deleted",
            "Availo was deleted, so this is kept read-only: it can still be read, and a questionnaire's filled file downloaded, but nothing in it can be changed.",
            "Availo",
        ),
        ("preference_invalid", f"You already have a skill called {'Shorter'!r}.", "Shorter"),
    ]


def test_the_errors_read_in_arabic(page: Page) -> None:
    in_arabic(page)
    page.goto("/workbench")
    say = "(problem) => I18n.error(problem)"

    # Every code, for a message nobody has put into Arabic: what kind of problem it is.
    unknown = "Something the server has not said before."
    for code in error_codes():
        arabic = page.evaluate(say, {"code": code, "message": unknown})
        assert arabic != unknown and ARABIC_LETTER.search(arabic), f"no Arabic for the code {code!r}"

    # A fixed message, its own Arabic first, before its code's.
    for message in fixed_messages():
        arabic = page.evaluate(say, {"code": "invalid_request", "message": message})
        assert arabic != message and ARABIC_LETTER.search(arabic), f"no Arabic for {message!r}"
        assert arabic != page.evaluate(say, {"code": "invalid_request", "message": unknown}), message
    busy = "A chat is working with this questionnaire right now. Wait until it finishes."
    assert (
        page.evaluate(say, {"code": "questionnaire_busy", "message": busy})
        == "تعمل محادثة على هذا الاستبيان الآن. انتظر حتى تنتهي."
    )

    # One the server filled in, through its pattern, keeping what it was filled with.
    for code, message, kept in filled_messages():
        arabic = page.evaluate(say, {"code": code, "message": message})
        assert arabic != page.evaluate(say, {"code": code, "message": unknown}), f"{message!r} fell back to its code"
        assert kept in arabic, f"{message!r} lost {kept!r}: {arabic!r}"
        rest = arabic.replace(kept, "") if kept else arabic
        assert not [word for word in LATIN_WORD.findall(rest) if word not in ("Excel", "Word", "PDF")], arabic


def test_in_english_the_servers_sentences_are_as_they_came(page: Page) -> None:
    page.goto("/workbench")
    sentence = _held(needs_review=True, review_reasons=[PARTIAL_SOURCE, UNGROUNDED])
    assert page.evaluate("(sentence) => I18n.server(sentence)", sentence) == sentence
    problem = {"code": "operation_refused", "message": f"No question {'Q7'!r} in this questionnaire."}
    assert page.evaluate("(problem) => I18n.error(problem)", problem) == problem["message"]
