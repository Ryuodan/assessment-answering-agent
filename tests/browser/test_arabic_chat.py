"""The assistant's page in Arabic, in a real browser (plan 038).

Each state the page's English tests reach, opened in Arabic: right to left, and
no English left on screen but names. What people said, titles, files and
products are content, inside `data-no-translate`; the page's own words are the
catalog's (`src/static/i18n/ar-chat.js`).

One thing is allowed besides what `english_on_screen` allows: content that
only an attribute can hold (`names`), such as a conversation's title in its
Delete button's label or a product's name in the chip's title. No element can
mark part of an attribute as content.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from playwright.sync_api import JSHandle, Page, expect

from src import (
    batches,
    chat_running,
    conversations,
    identity,
    knowledge,
    products,
    progress,
    questionnaire,
    store,
    tools,
)
from src.agents import assistant
from src.config import settings
from src.models import AnsweredQuestion, Question
from tests import forms_fixtures as shapes
from tests.browser.arabic import expect_arabic, in_arabic
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team
WRITTEN = "Yes, every backup is encrypted."
# The server's own message for a failure, with no Arabic of its own: the page says what
# kind of failure it was, by its code (`I18n.error`, ar-server.js).
SERVER_SAYS = "The model could not be reached."
FAILED_CODE = "internal_error"


PRODUCT = "Availo"
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_ARABIC = re.compile(r"[؀-ۿ]")
_EASTERN_DIGITS = re.compile(r"[٠-٩]")


def expect_arabic_here(page: Page, where: str, *, names: tuple[str, ...] = (), besides: tuple[str, ...] = ()) -> None:
    """`expect_arabic`, where `names` -- content an attribute holds -- may stand among the Arabic.

    The product's name is always among them: the product chip's and the "Last used" button's titles hold it.
    """
    expect_arabic(page, where, besides=besides, names=(*names, PRODUCT))


def code_says(page: Page) -> str:
    """What the page says for the failure: its code's Arabic, not the server's English."""
    said = page.evaluate("([message, code]) => I18n.error({ message, code })", [SERVER_SAYS, FAILED_CODE])
    assert said != SERVER_SAYS and _ARABIC.search(said), said
    return said


def no_sideways_scroll(page: Page, where: str) -> None:
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1], f"{where}: the page scrolls sideways ({width[0]}px in {width[1]}px)"


# --- what the tests start from, as the English tests do -------------------------------


@pytest.fixture
def availo(monkeypatch: pytest.MonkeyPatch) -> products.Product:
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            # So deleting a product drops its fake collection rather than reaching Chroma.
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo", color="#16a34a")


def chat(
    title: str,
    reply: str = "Hello again.",
    *,
    batch: batches.Batch | None = None,
    product_id: str = "",
    ui: dict | None = None,
) -> str:
    """A conversation with one exchange in it; `ui` is what the reply was drawn with."""
    conversation = assistant.start(identity.local_user(), title, product_id)
    said = {assistant.UI_KEY: ui} if ui else {}
    conversation.messages = [HumanMessage(title), AIMessage(reply, additional_kwargs=said)]
    if batch is not None:
        conversation.batch_id = batch.id
    conversations.save(conversation)
    return conversation.id


def a_questionnaire(tmp_path: Path, *, product_id: str = "", answered: bool = True) -> batches.Batch:
    user = identity.local_user()
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=product_id)
    if answered:
        question = next(q for q in batch.form.questions if q.writable)
        tools.set_answer(user, batch.id, question.id, WRITTEN)
    return batch


def last_said(conversation_id: str, stamp: str) -> None:
    """Last said in at `stamp`, and not opened since."""
    conn = store.connect()
    with conn:
        conn.execute(
            "UPDATE conversations SET updated_at = ?, used_at = '' WHERE conversation_id = ?", (stamp, conversation_id)
        )


def ago(**since: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(**since)).isoformat(timespec="seconds")


def opened(page: Page) -> None:
    """The page in Arabic, started: the products are listed, so every handler is in place."""
    in_arabic(page)
    page.goto("/")
    expect(page.locator("#productPick option[value='general']")).to_have_count(1)


def row_of(page: Page, title: str):
    return page.locator("#historyList .convo-row", has=page.locator(".label", has_text=title))


def a_dragged_file(page: Page, name: str) -> JSHandle:
    return page.evaluate_handle(
        """(name) => {
            const transfer = new DataTransfer();
            transfer.items.add(new File([new Uint8Array([1, 2, 3])], name));
            return transfer;
        }""",
        name,
    )


def drag(page: Page, event: str, selector: str, transfer: JSHandle) -> None:
    page.dispatch_event(selector, event, {"dataTransfer": transfer})


class Echo:
    """The agent, stubbed: it replies to what it was asked, and does nothing else."""

    def __init__(self, tool_list: list) -> None:
        self.tools = tool_list

    async def astream(self, payload, config=None, stream_mode=None):
        messages = list(payload["messages"])
        messages.append(AIMessage(f"Reply to: {assistant.spoken(str(messages[-1].content))}"))
        yield {"messages": messages}


class Turns:
    """Turns the test holds back, by what was asked, counted at 1 of 4, until it lets them go."""

    def __init__(self) -> None:
        self.gates: dict[str, threading.Event] = {}
        self.runs: dict[str, str] = {}

    def hold(self, message: str) -> None:
        self.gates[message] = threading.Event()

    def release(self, message: str) -> None:
        self.gates[message].set()

    def release_all(self) -> None:
        for gate in self.gates.values():
            gate.set()


@pytest.fixture
def turns(monkeypatch: pytest.MonkeyPatch) -> Iterator[Turns]:
    held = Turns()
    real = assistant.say

    async def say(user, conversation, message, *, upload=None, run_id=""):
        gate = held.gates.get(message)
        if gate is not None:
            held.runs[message] = run_id
            progress.start(run_id, stage="answering")
            progress.set_total(run_id, 4)
            progress.advance(run_id)
            await asyncio.to_thread(gate.wait, 30)
        return await real(user, conversation, message, upload=upload, run_id=run_id)

    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")
    monkeypatch.setattr(chat_running, "_RUNNING", {})
    monkeypatch.setattr(assistant, "_agent", lambda tool_list, **named: Echo(tool_list))
    monkeypatch.setattr(assistant, "say", say)
    yield held
    held.release_all()  # no request left waiting when the server stops


# --- a new chat ---------------------------------------------------------------------------


def test_an_empty_chat_reads_right_to_left_in_arabic(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    expect_arabic_here(page, "in an empty chat")

    expect(page.locator("#empty h2")).to_have_text("ما الذي تريد إنجازه؟")
    expect(page.locator("#prompt")).to_have_attribute(
        "placeholder", "اطلب ما تريد، مثلاً: «أجب عن أسئلة الحوكمة باختصار»"
    )
    expect(page.locator("#historyList")).to_have_text("لا شيء بعد.")
    expect(page.locator("#productNeededText")).to_have_text(
        "لأي منتج هذه المحادثة؟ «عام» يستخدم السياسات المشتركة فقط."
    )
    expect(page.locator("#productPick option:checked")).to_have_text("المنتج: اختر…")
    expect(page.locator("#productPick option[value='general']")).to_have_text("عام (السياسات المشتركة فقط)")
    # The starters are suggestions, in the interface's language: sent in Arabic, they get Arabic replies.
    starters = page.locator("#starters button")
    expect(starters).to_have_count(6)
    for text in starters.all_inner_texts():
        assert _ARABIC.search(text) and not _WORD.search(text), text
    no_sideways_scroll(page, "an empty chat at 1280px")

    page.fill("#prompt", "Do we encrypt backups?")
    expect(page.locator("#productNeededText")).to_have_text("اختر المنتج لإرسال هذه الرسالة.")
    expect(page.locator("#productChip")).to_have_attribute("title", "اختر المنتج الذي تخصه هذه المحادثة قبل الإرسال.")
    expect_arabic_here(page, "with a message waiting for a product")


def test_a_file_attached_dragged_and_refused_in_arabic(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    attached = page.locator("#attached")
    expect(attached).to_be_visible()
    expect(attached).to_contain_text("الملف المرفق")
    expect(page.locator("#attachedName")).to_have_text("HR.xlsx")
    expect(page.locator("#attachedName")).to_have_attribute("dir", "auto")  # a file's name reads left to right
    expect_arabic_here(page, "with a file attached")

    other = a_dragged_file(page, "vendor.docx")
    drag(page, "dragenter", "#thread", other)
    target = page.locator("#dropTarget")
    expect(target).to_be_visible()
    expect(target).to_contain_text("أفلت الاستبيان لإرفاقه")
    expect(page.locator("#dropReplaces")).to_have_text("بدلاً من HR.xlsx")
    expect_arabic_here(page, "while a file is dragged over the page")

    pdf = a_dragged_file(page, "report.pdf")
    drag(page, "drop", "#thread", pdf)
    note = page.locator("#composerNote")
    expect(note).to_have_text(
        "لم يُرفق «report.pdf»: الاستبيان هنا ملف XLSX أو XLSM أو DOCX. يمكن قراءة أسئلة ملف PDF في مساحة العمل."
    )
    expect(note.locator("[data-no-translate]")).to_have_text("report.pdf")
    expect_arabic_here(page, "with a refused file")


def test_switching_the_language_asks_first_when_the_box_holds_a_message(page: Page) -> None:
    opened(page)
    page.fill("#prompt", "Do we encrypt backups?")
    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    page.click("#languageToggle")
    expect(page.locator("#prompt")).to_have_value("Do we encrypt backups?")
    assert asked == ["لم تُرسل رسالتك بعد، وستضيع. هل تريد تبديل اللغة رغم ذلك؟"]
    expect(page.locator("html")).to_have_attribute("dir", "rtl")

    page.fill("#prompt", "")
    page.click("#languageToggle")  # nothing to lose: no question, and the page is English again
    expect(page.locator("html")).to_have_attribute("dir", "ltr")
    expect(page.locator("#newChat")).to_have_text("New conversation")


def test_signed_out_the_page_is_arabic(page: Page) -> None:
    identity.ensure_team(TEAM)
    identity.set_access_code(TEAM, "BROWSER-TEST-CODE")
    identity.add_user("firstname.lastname@example.test")  # someone to sign in as: the page asks
    in_arabic(page)
    page.goto("/")
    expect(page.locator("#gate")).to_be_visible()
    expect(page.locator("#gate h2")).to_have_text("تسجيل الدخول")
    expect_arabic_here(page, "signed out")


# --- the conversation list -------------------------------------------------------------


def test_the_conversation_list_is_arabic_and_its_titles_are_content(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    titled = "Answer the vendor file"
    arabic = "هل نشفّر النسخ الاحتياطية؟"
    chat(titled, batch=a_questionnaire(tmp_path), product_id=availo.id)
    last_said(chat(arabic), ago(days=1))
    last_said(chat("Do we log access?"), ago(days=3))
    last_said(chat("Do we rotate keys?"), ago(days=20))
    titles = (titled, arabic, "Do we log access?", "Do we rotate keys?")

    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    expect(page.locator("#historyList .convo")).to_have_count(4)
    expect_arabic_here(page, "with conversations listed", names=titles)

    label = row_of(page, titled).locator(".label")
    expect(label).to_have_attribute("data-no-translate", "")
    expect(label).to_have_attribute("dir", "auto")  # an English title reads left to right
    expect(row_of(page, arabic).locator(".label")).to_have_attribute("dir", "rtl")
    expect(row_of(page, titled).locator(".file")).to_have_text("📎vendor.xlsx")
    # Dated as somebody would say it, in Arabic, with Western digits.
    expect(row_of(page, arabic).locator(".when")).to_have_text(re.compile(r"^أمس \d{1,2}:\d{2}"))
    for row in titles:
        when = row_of(page, row).locator(".when")
        said, exact = when.inner_text(), when.get_attribute("title") or ""
        assert _ARABIC.search(said) or re.fullmatch(r"[\d:\s\u200f]+[صم]?", said), said
        assert not _WORD.search(said) and not _EASTERN_DIGITS.search(said + exact), (said, exact)
        assert exact.startswith("آخر استخدام: "), exact
    kept = row_of(page, titled).locator(".kept")
    expect(kept).to_have_text(re.compile(r"^محفوظ حتى \d{1,2} [؀-ۿ]+ \d{4}$"))
    expect(row_of(page, titled).locator(".when")).to_have_attribute("title", re.compile(r" · محفوظ حتى \d"))

    forget = row_of(page, titled).locator(".forget")
    expect(forget).to_have_attribute("title", "حذف هذه المحادثة")
    expect(forget).to_have_attribute("aria-label", f"حذف «{titled}»")
    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    row_of(page, titled).hover()
    forget.click()
    expect(page.locator("#historyList .convo")).to_have_count(4)
    assert asked, "Delete asks first"
    question, gone, kept_file = asked[0].split("\n\n")
    assert re.fullmatch(f"حذف «{titled}» \\(.+\\)؟", question), question
    assert gone == "ستُحذف المحادثة ولا يمكن استعادتها."
    assert kept_file == "أما استبيانها، vendor.xlsx، وإجاباته فتبقى محفوظة؛ افتحه من مساحة العمل."


# --- a turn ------------------------------------------------------------------------------


STEPS = [
    "open_questionnaire('vendor.xlsx')",
    "answer_questions(in 'Questionnaire', not yet answered)",
    "answer_questions(1 chosen question(s))",
    "search_policies('backups')",
]
SOURCE = {
    "source_name": "Backup Policy.pdf",
    "source_type": "guideline",
    "locator": "Backup Policy.pdf §4.2",
    "snippet": "Backups shall be encrypted at rest.",
    "chunk": 0,
}


def test_a_reply_with_its_steps_and_sources_is_arabic_around_its_words(page: Page, tmp_path: Path) -> None:
    ui = {"steps": STEPS, "sources": [SOURCE], "at": "2026-11-01T09:00:00Z", "changed": True}
    chat("Answer the vendor file", "All four answered.", batch=a_questionnaire(tmp_path), ui=ui)

    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    page.locator("#historyList .convo").click()
    reply = page.locator("#thread .turn.assistant").last
    expect(reply.locator(".bubble")).to_have_text("All four answered.")
    expect_arabic_here(page, "with a reply and the answers beside it", names=("Answer the vendor file",))

    expect(page.locator("#thread .turn.you .role")).to_have_text("أنت")
    expect(reply.locator(".role")).to_contain_text("المساعد")
    expect(reply.locator(".role time")).to_have_text(re.compile(r"^\d{1,2} [؀-ۿ]+، \d{1,2}:\d{2}"))
    bubble = reply.locator(".bubble")
    expect(bubble).to_have_attribute("data-no-translate", "")
    expect(bubble).to_have_attribute("dir", "auto")  # an English reply reads left to right
    expect(reply.get_by_role("button", name="اعرض الإجابات ←")).to_be_visible()

    steps = reply.locator(".did")
    expect(steps.locator(".count")).to_have_text("4 خطوات")
    expect(steps.locator(".gist")).to_have_text("قرأ الملف · أجاب عن أسئلة ×2 · بحث في السياسات")
    steps.locator("summary").click()
    expect(steps.locator(".action")).to_have_text(["قرأ الملف", "أجاب عن أسئلة", "أجاب عن أسئلة", "بحث في السياسات"])
    expect(steps.locator(".scope").first).to_have_attribute("data-no-translate", "")
    # Each step's title is the call exactly as it was made: content.
    expect_arabic_here(page, "with the steps open", names=("Answer the vendor file", *STEPS))

    sources = reply.locator(".sources")
    expect(sources.locator("summary")).to_have_text("مصدر واحد — انقر لقراءة البنود")
    sources.locator("summary").click()
    sources.locator(".cite").click()
    panel = sources.locator(".cite-panel")
    expect(panel).to_be_visible()
    expect(panel.locator(".who")).to_have_attribute("data-no-translate", "")
    expect_arabic_here(page, "with a source open", names=("Answer the vendor file", *STEPS))


def test_a_turn_while_it_runs_and_after_it_is_arabic(page: Page, turns: Turns) -> None:
    chat("Do we log access?", "Yes, access is logged.")
    chat("Do we encrypt backups?", "Yes, with AES-256.")
    titles = ("Do we log access?", "Do we encrypt backups?")
    asked = "Answer the governance questions"
    turns.hold(asked)

    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    row_of(page, "Do we log access?").locator(".convo").click()
    page.fill("#prompt", asked)
    page.click("#send")
    working = page.locator("#thread .turn.working")
    expect(working.locator(".working-label")).to_have_text("أُجيب عن 1 من 4 — بقي 3", timeout=10_000)
    expect(working.locator(".progress-fill")).to_be_visible()
    expect_arabic_here(page, "while a turn runs", names=titles)

    # The assistant's own sentence about what it is doing, as the server says it.
    progress.note(turns.runs[asked], "Searching the policies…")
    expect(working.locator(".working-label")).to_have_text("جارٍ البحث في السياسات…", timeout=10_000)

    row_of(page, "Do we encrypt backups?").locator(".convo").click()
    expect(row_of(page, "Do we log access?").locator(".working-now")).to_have_text("جارٍ العمل…")
    expect_arabic_here(page, "with a turn running in another conversation", names=titles)

    turns.release(asked)
    expect(row_of(page, "Do we log access?").locator(".new-reply")).to_have_text("رد جديد", timeout=15_000)
    expect_arabic_here(page, "with a new reply in another conversation", names=titles)


def test_a_turn_that_fails_says_so_in_arabic(page: Page) -> None:
    def refuse(route) -> None:
        if route.request.method != "POST":
            route.continue_()
            return
        route.fulfill(status=500, json={"detail": SERVER_SAYS, "code": FAILED_CODE})

    page.route("**/api/chat", refuse)
    opened(page)
    page.select_option("#productPick", "general")
    page.fill("#prompt", "Do we encrypt backups?")
    page.click("#send")
    failed = page.locator("#thread .turn.assistant .bubble").last
    expect(failed).to_have_text(f"تعذّر ذلك: {code_says(page)}")
    expect_arabic_here(page, "after a turn failed")


def test_a_turn_that_fails_in_another_conversation_is_said_under_the_list(page: Page) -> None:
    chat("Do we log access?", "Yes, access is logged.")
    chat("Do we encrypt backups?", "Yes, with AES-256.")
    held: list = []

    def hold(route) -> None:
        if route.request.method != "POST":
            route.continue_()
            return
        held.append(route)

    page.route("**/api/chat", hold)
    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    row_of(page, "Do we log access?").locator(".convo").click()
    page.fill("#prompt", "Answer everything")
    page.click("#send")
    for _ in range(200):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "the message was never sent"
    row_of(page, "Do we encrypt backups?").locator(".convo").click()
    expect(page.locator("#thread")).to_contain_text("Yes, with AES-256.")
    held[0].fulfill(status=500, json={"detail": SERVER_SAYS, "code": FAILED_CODE})

    status = page.locator("#historyStatus")
    expect(status).to_have_text(f"تعذّرت الإجابة عن «Answer everything»: {code_says(page)}")
    expect(status.locator("[data-no-translate]")).to_have_text("Answer everything")
    expect_arabic_here(page, "with a failure under the list", names=("Do we log access?", "Do we encrypt backups?"))


def test_products_that_could_not_be_loaded_are_said_in_arabic(page: Page) -> None:
    page.route("**/api/products", lambda route: route.fulfill(status=503, json={"detail": "down"}))
    in_arabic(page)
    page.goto("/")
    expect(page.locator("#productNeededText")).to_have_text(
        "تعذّر تحميل منتجاتك. أعد تحميل الصفحة قبل الاختيار، ولا تختر «عام» إلا إن كانت هذه المحادثة تخص الشركة كلها."
    )
    expect_arabic_here(page, "with the products missing")


# --- the answers panel -----------------------------------------------------------------


def test_the_answers_panel_is_arabic_through_review_and_filling(page: Page, tmp_path: Path) -> None:
    user = identity.local_user()
    batch = a_questionnaire(tmp_path, answered=False)
    drafted, aside = [q for q in batch.form.questions if q.writable][:2]
    # As the model drafts one: approving it teaches the answer memory nothing, so nothing is embedded.
    batches.save_answers(
        batch.id,
        [AnsweredQuestion(question=Question(id=drafted.id, text=drafted.text), answer=WRITTEN, confidence=0.9)],
    )
    tools.set_questions(user, batch.id, [{"id": aside.id, "skip": True}])
    chat("Answer the vendor file", "One answered.", batch=batch)
    title = ("Answer the vendor file",)

    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    page.locator("#historyList .convo").click()
    pane = page.locator("#answersPane")
    expect(pane.locator(".answer")).to_have_count(1)
    pane.locator("#answerTabs button[data-tab='all']").click()  # where the set-aside one is listed too
    expect(page.locator("#answerTitle")).to_have_text("vendor.xlsx")
    expect(page.locator("#answerTitle [data-no-translate]")).to_have_text("vendor.xlsx")
    expect(pane.locator(".stat .label")).to_have_text(
        ["أسئلة", "أُجيب عنها هنا", "تحتاج إلى مراجعة", "مستبعدة من الملف"]
    )
    expect(pane.locator(".aside-head")).to_have_text("مستبعدة من الملف — لن تُكتب فيه (1)")
    expect(page.locator("#fillBtn")).to_have_text("املأ الملف")
    expect(page.locator("#closeAnswers")).to_have_attribute("title", "إخفاء هذه اللوحة")
    expect_arabic_here(page, "with the answers panel open", names=title)

    pane.locator(".aside-row").get_by_role("button", name="أدرجها في الملف مجدداً").click()
    expect(page.locator("#answersStatus")).to_have_text("أُعيد إلى الاستبيان. أصبح جزءاً منه مجدداً.")
    expect_arabic_here(page, "after bringing a question back", names=title)

    pane.locator(".answer button[data-card-action='approve']").click()
    expect(page.locator("#answersStatus")).to_have_text(
        "اعتُمدت. ستُكتب في الملف. لم تدخل ذاكرة الإجابات — فهي تحفظ ما كتبه شخص، ولم يغيّر أحد هذه الإجابة."
    )
    expect_arabic_here(page, "after approving an answer", names=title)

    page.click("#fillBtn")
    filled = page.locator("#thread .turn.assistant .bubble").last
    written = "vendor - answered.xlsx"  # the filled copy's name: content, in the page's own sentence
    expect(filled).to_have_text(f"كُتبت قيمة واحدة في {written} — ولم يُمسّ أي جزء آخر من الملف.")
    expect(filled.locator("[data-no-translate]")).to_have_text(written)
    expect(page.locator("#downloadBtn")).to_have_text("تنزيل")
    expect_arabic_here(page, "after filling the file", names=title)

    page.click("#closeAnswers")
    expect(page.locator("#toggleAnswers")).to_have_text("الإجابات ←")
    expect_arabic_here(page, "with the answers put away", names=(*title, written))


def test_a_questionnaire_with_nothing_answered_says_so_in_arabic(page: Page, tmp_path: Path) -> None:
    chat("Open vendor.xlsx", "It has 4 questions.", batch=a_questionnaire(tmp_path, answered=False))
    opened(page)
    page.locator("#historyList .convo").click()
    expect(page.locator("#answers .nothing")).to_have_text("عُثر على 4 أسئلة. اطلب من المساعد أن يجيب عن بعضها.")
    expect_arabic_here(page, "with nothing answered yet", names=("Open vendor.xlsx",))


def test_the_answers_panel_is_resized_from_its_edge_on_the_right(page: Page, tmp_path: Path) -> None:
    """In Arabic the panel is on the left: its edge narrows it dragged leftwards, and ArrowRight widens it."""
    chat("Open vendor.xlsx", "It has 4 questions.", batch=a_questionnaire(tmp_path))
    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    page.locator("#historyList .convo").click()
    pane = page.locator("#answersPane")
    expect(pane).to_be_visible()
    before = pane.bounding_box()
    assert before and before["x"] < 10, f"the panel is on the left: {before}"

    handle = page.locator("#paneResizer").bounding_box()
    assert handle
    x, y = handle["x"] + handle["width"] / 2, handle["y"] + 200
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 60, y, steps=6)
    page.mouse.up()
    after = pane.bounding_box()
    assert after and abs(after["width"] - (before["width"] - 60)) <= 2, (before, after)

    page.locator("#paneResizer").focus()
    page.keyboard.press("ArrowRight")
    wider = pane.bounding_box()
    assert wider and abs(wider["width"] - (after["width"] + 40)) <= 2, (after, wider)


# --- a deleted product's chat ----------------------------------------------------------


def test_a_deleted_products_chat_is_read_only_in_arabic(page: Page, tmp_path: Path, availo: products.Product) -> None:
    kept = a_questionnaire(tmp_path / "kept", product_id=availo.id)
    gone = a_questionnaire(tmp_path / "gone", product_id=availo.id)
    chat("Open vendor.xlsx", "It has 4 questions.", batch=kept, product_id=availo.id)
    # Its reply changed the answers: how the page knows there was a questionnaire (plan 033).
    ui = {"changed": True, "steps": ["open_questionnaire('vendor.xlsx')"]}
    last_said(chat("Answer the old file", "Done.", batch=gone, product_id=availo.id, ui=ui), ago(days=2))
    products.delete(identity.local_user(), TEAM, availo.id, "confirm")
    questionnaire.delete(identity.local_user(), gone.id)
    names = ("Availo", "Open vendor.xlsx", "Answer the old file")

    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    row_of(page, "Open vendor.xlsx").locator(".convo").click()
    note = page.locator("#composerNote")
    expect(note).to_have_text("حُذف Availo. هذه المحادثة محفوظة لتقرأها؛ ابدأ محادثة جديدة للمتابعة.")
    expect(note.locator("[data-no-translate]")).to_have_text("Availo")
    expect(page.locator("#prompt")).to_have_attribute("placeholder", "محفوظة للقراءة فقط — ابدأ محادثة جديدة للمتابعة")
    expect(page.locator("#productPick option:checked")).to_have_text("Availo (محذوف)")
    expect(page.locator("#productChip")).to_have_attribute(
        "title", "حُذف Availo. هذه المحادثة محفوظة للقراءة فقط؛ ابدأ محادثة جديدة للمتابعة."
    )
    expect(page.locator("#answersPane .answer")).to_have_count(1)
    expect_arabic_here(page, "in a deleted product's chat", names=names)

    # Its questionnaire deleted too: said once, after what the box says already.
    row_of(page, "Answer the old file").locator(".convo").click()
    expect(note).to_have_text(
        "حُذف Availo. هذه المحادثة محفوظة لتقرأها؛ ابدأ محادثة جديدة للمتابعة. وحُذف استبيانها أيضاً، مع إجاباته."
    )
    expect_arabic_here(page, "in a deleted product's chat without its questionnaire", names=names)


# --- on a phone ------------------------------------------------------------------------


def test_on_a_phone_nothing_scrolls_sideways_or_overlaps(page: Page, tmp_path: Path) -> None:
    chat("Open vendor.xlsx", "It has 4 questions.", batch=a_questionnaire(tmp_path))
    page.set_viewport_size({"width": 375, "height": 740})
    opened(page)
    no_sideways_scroll(page, "an empty chat at 375px")
    expect_arabic_here(page, "in an empty chat on a phone")

    # The message box: Send at the inline end (the left), the short "Attach" at the start, apart.
    inner, attach, send = (page.locator(s).bounding_box() for s in (".composer-inner", "#attachBtn", "#send"))
    assert inner and attach and send
    expect(page.locator("#attachBtn")).to_have_text("إرفاق", use_inner_text=True)
    assert inner["x"] >= 0 and inner["x"] + inner["width"] <= 375, inner
    assert send["x"] + send["width"] < attach["x"], f"Send {send} and Attach {attach} overlap or are not mirrored"
    assert inner["x"] <= send["x"] and attach["x"] + attach["width"] <= inner["x"] + inner["width"], (inner, attach)
    bar = page.evaluate(
        """() => [...document.querySelectorAll('.topbar > *')]
             .filter((el) => el.getClientRects().length)
             .map((el) => el.getBoundingClientRect())
             .filter((box) => box.left < -0.5 || box.right > window.innerWidth + 0.5).length"""
    )
    assert bar == 0, f"{bar} of the bar's controls are cut off"

    page.click("#toggleHistory")
    expect(page.locator("#history")).to_be_visible()
    no_sideways_scroll(page, "the list open at 375px")
    expect_arabic_here(page, "with the list open on a phone", names=("Open vendor.xlsx",))

    page.locator("#historyList .convo").click()
    expect(page.locator("#answersPane")).to_be_visible()
    no_sideways_scroll(page, "the answers open at 375px")
    expect_arabic_here(page, "with the answers open on a phone", names=("Open vendor.xlsx",))
