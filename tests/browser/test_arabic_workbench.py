"""The Workbench in Arabic, right to left, in the states its English tests reach (plan 038).

Each test starts the browser in Arabic (`in_arabic`) and reads the page in each
state with `expect_arabic`: nothing on screen in English but names, files,
standards, formats and keys. Content is not interface: a question, an answer,
a file's, a sheet's or a product's name, and what the file or the reader said
are marked `data-no-translate`, in their own direction.

What `cards.js` draws on this page and the server's sentences (why an answer is
held back, `ar-server.js`) are read here too.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import (
    access_codes,
    batches,
    busy,
    identity,
    interface_language,
    knowledge,
    products,
    retention,
    service,
    tools,
    verification,
)
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.browser.arabic import english_on_screen, expect_arabic, in_arabic
from tests.browser.choosing import choose_general
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team
ANSWER = "Yes, an approved policy is in place and reviewed annually."
ADMIN = "admin@example.test"

# Content the page puts in attributes: the product's name in its badge's title,
# a question's place in the file ("Questionnaire!3") in its card's label.
IN_ATTRIBUTES = ("Availo", "Questionnaire")
# Why an answer is held, as the server writes it.
HELD = verification.UNGROUNDED


def arabic(page: Page, where: str, *, within: str = "body") -> None:
    expect_arabic(page, where, within=within, names=IN_ATTRIBUTES)


def fits(page: Page) -> None:
    """Nothing scrolls sideways."""
    wide = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert wide[0] <= wide[1], f"the page scrolls sideways: {wide[0]} wide in a window of {wide[1]}"


def press(page: Page, key: str, code: str) -> None:
    """A key as an Arabic keyboard sends it: its own letter, and the place it is on (`code`)."""
    page.evaluate(
        """([key, code]) => (document.activeElement || document.body).dispatchEvent(
             new KeyboardEvent("keydown", { key, code, bubbles: true, cancelable: true }))""",
        [key, code],
    )


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], knowledge.KnowledgeStore]:
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


@pytest.fixture
def availo(stores) -> products.Product:
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo", color="#16a34a")


@pytest.fixture
def answers_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(questions, language=None, run_id=None, **extra):
        return [AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


@pytest.fixture
def one_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every answer confident but the second, which is flagged."""

    async def answered(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=q,
                answer="Partly." if index == 1 else ANSWER,
                confidence=0.4 if index == 1 else 0.9,
                needs_review=index == 1,
                review_reasons=[HELD] if index == 1 else [],
            )
            for index, q in enumerate(questions)
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


@pytest.fixture
def mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """q1 confident; q2, q3 and q4 flagged."""

    async def answered(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False)
            if index == 0
            else AnsweredQuestion(
                question=q,
                answer=["", "Partly.", "Probably.", "Not yet."][index],
                confidence=0.3,
                needs_review=True,
                review_reasons=[HELD],
            )
            for index, q in enumerate(questions)
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


def read_as_general(page: Page, tmp_path: Path, name: str = "vendor.xlsx") -> Path:
    workbook = shapes.simple(tmp_path / name)
    page.goto("/workbench")
    choose_general(page)
    page.set_input_files("#assessmentInput", str(workbook))
    expect(page.locator("#questionList textarea")).to_have_count(4)
    return workbook


# --- before anything is loaded ---------------------------------------------------


def test_the_empty_workbench_is_arabic_and_right_to_left(page: Page, availo: products.Product) -> None:
    in_arabic(page)
    page.goto("/workbench")

    expect(page).to_have_title("مساحة العمل — الإجابة عن الاستبيانات")
    expect(page.locator("#stepList button")).to_have_text(
        ["1الاختيار والتحميل", "2تحقّق مما تم العثور عليه", "3الإجابة", "4المراجعة", "5املأ الملف ونزّله"]
    )
    expect(page.locator("#stepTitle")).to_have_text("استبيان جديد")
    expect(page.locator("#questionListTitle")).to_have_text("أو اكتب الأسئلة بنفسك")
    expect(page.locator("#dropFor")).to_have_text("اختر المنتج أولاً؛ وأي ملف تضعه الآن ينتظر اختياره.")
    expect(page.locator("#kbLineText")).to_have_text("الإجابات من 0 وثيقة مشتركة")
    arabic(page, "empty")

    page.click("#searchOpen")
    expect(page.locator("#searchDrawer")).to_have_class(re.compile(r"\bopen\b"))
    arabic(page, "the search drawer, empty", within="#searchDrawer")
    page.click("#searchClose")

    page.evaluate("document.getElementById('documentViewer').showModal()")
    arabic(page, "the document viewer", within="#documentViewer")


def test_a_file_waits_for_its_product_then_is_read_for_it(page: Page, tmp_path: Path, availo: products.Product) -> None:
    in_arabic(page)
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))

    waiting = page.locator("#readNeedsProduct")
    expect(waiting).to_have_text("vendor.xlsx بانتظار المنتج: اختر منتجاً في الأعلى، فيُقرأ فوراً.")
    expect(waiting.locator("[data-no-translate]")).to_have_attribute("dir", "auto")  # the file's name, its own way
    arabic(page, "a file waiting for the product")

    page.select_option("#formProduct", availo.id)
    expect(page.locator("#questionList textarea")).to_have_count(4)
    held = page.locator("#step1Held")
    expect(held).to_have_text("Availo · vendor.xlsx · 4 أسئلة في ورقة واحدة")
    expect(held.locator("[data-no-translate]")).to_have_text(["Availo", "vendor.xlsx"])
    expect(page.locator("#step2Held")).to_have_text("عُثر على 4 أسئلة في ورقة واحدة")
    expect(page.locator("#extractStatus")).to_have_text("عُثر على 4 أسئلة في vendor.xlsx.")
    arabic(page, "a questionnaire read for a product")

    page.click("#step1Toggle")
    expect(page.locator("#dropFor")).to_contain_text("أي ملف آخر يُفتح استبياناً جديداً لـAvailo")
    arabic(page, "step 1 opened again")


# --- reading, answering, reviewing and filling ------------------------------------


def test_a_questionnaire_is_read_answered_reviewed_and_filled_in_arabic(
    page: Page, tmp_path: Path, one_held: None, stores
) -> None:
    in_arabic(page)
    read_as_general(page, tmp_path)
    expect(page.locator("#step1Held")).to_have_text("عام · vendor.xlsx · 4 أسئلة في ورقة واحدة")
    expect(page.locator("#answerBtn")).to_have_text("أجب عن 4 أسئلة")
    arabic(page, "a questionnaire read")

    page.click("#step2Toggle")
    expect(page.locator("#formColumns select").first).to_be_visible()
    expect(page.locator("#worthCheckingHint em")).to_have_text("يُستحسن التحقق منه")
    arabic(page, "what was found, opened")

    page.locator("#answerOptions > summary").click()
    expect(page.locator("#languageSelect option")).to_have_text(
        ["الإجابة بلغة كل سؤال", "فرض الإنجليزية", "فرض العربية"]
    )
    arabic(page, "more options")

    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(1, timeout=15_000)  # opens on what needs review
    expect(page.locator("#reviewCounts")).to_have_text("ستُكتب في الملف: 3 · تحتاج إلى مراجعة: 1")
    expect(page.locator("#reviewDone")).to_have_text("تمت مراجعة 0 من 1")
    expect(page.locator("#reviewKeys kbd")).to_have_text(["↑", "↓", "J", "K", "A", "E", "Esc"])
    expect(page.locator("#resultsSummary .stat .label")).to_have_text(
        ["الأسئلة التي عُثر عليها", "أُجيب عنها", "تحتاج إلى مراجعة", "لغة الإجابات"]
    )
    expect(page.locator("#resultsSummary .stat .value").last).to_have_text("الإنجليزية")
    expect(page.locator("#step3Held")).to_have_text("أُجيب عن 4 من 4")
    arabic(page, "the review")

    with page.expect_download():
        page.click("#fillFormBtn")
    report = page.locator("#formFilled")
    expect(report).to_contain_text("جارٍ تنزيل vendor - answered.xlsx.")
    expect(report).to_contain_text("حُجزت إجابة واحدة للمراجعة")
    report.get_by_text("أيّها، ولماذا").click()
    expect(page.locator("#step5Held")).to_have_text("كُتبت 3 قيم في vendor - answered.xlsx · محجوزة للمراجعة: 1")
    arabic(page, "filled, with one held back")

    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    report.get_by_role("button", name="اكتبها في الملف على أي حال").click()
    assert asked and asked[0].startswith("هل تكتب في الملف إجابة واحدة غير معتمدة؟"), asked

    page.locator("#moreActions > summary").click()
    composer = page.locator("#composerInput")
    expect(composer).to_be_visible()
    # A textarea's own text is the person's; its placeholder is read by english_on_screen as well.
    expect(composer).to_have_attribute("placeholder", "اكتب سؤالاً واضغط Enter، أو انقر «إضافة إلى القائمة»")
    arabic(page, "more: the downloads, rewording and another question")


def test_the_review_keys_work_on_an_arabic_keyboard(page: Page, tmp_path: Path, mixed: None, stores) -> None:
    """On an Arabic layout J types "ت", K "ن" and A "ش": the key's place says which it is."""
    in_arabic(page)
    read_as_general(page, tmp_path)
    page.click("#answerBtn")
    cards = page.locator("#results .answer")
    expect(cards).to_have_count(3, timeout=15_000)

    press(page, "ت", "KeyJ")  # from nowhere in particular: the first card
    expect(cards.nth(0)).to_be_focused()
    press(page, "ت", "KeyJ")
    expect(cards.nth(1)).to_be_focused()
    press(page, "ن", "KeyK")
    expect(cards.nth(0)).to_be_focused()

    press(page, "ش", "KeyA")  # accepts the card in focus, and goes on to the next one held
    expect(page.locator("#reviewDone")).to_have_text("تمت مراجعة 1 من 3")
    expect(cards).to_have_count(2)
    expect(page.locator("#reviewStatus")).to_contain_text("اعتُمدت.")


def test_setting_a_row_aside_is_an_action_and_what_it_is_then_a_state(
    page: Page, tmp_path: Path, mixed: None, stores
) -> None:
    """The button says what it does, استبعاد من الملف; the row then says what it is, مستبعدة من الملف."""
    in_arabic(page)
    read_as_general(page, tmp_path)
    page.click("#answerBtn")
    expect(page.locator("#reviewBar")).to_be_visible(timeout=15_000)
    page.locator("#questionListSummary").click()  # the folded list, where a row is set aside
    row = page.locator("#questionList .qrow").first
    row.get_by_role("button", name="استبعاد من الملف", exact=True).click()

    expect(page.locator("#answerStatus")).to_have_text("استُبعد من الملف. لن يُكتب شيء في ذلك الصف.")
    expect(row.get_by_role("button", name="تضمين", exact=True)).to_be_visible()
    expect(row).to_contain_text("· مستبعدة من الملف")
    tabs = page.locator("#reviewTabs")
    expect(tabs.get_by_role("button", name=re.compile(r"^فارغة أو مستبعدة من الملف \("))).to_have_text(
        "فارغة أو مستبعدة من الملف (1)"
    )
    arabic(page, "a row set aside")


# --- typing the questions ---------------------------------------------------------


def test_typed_questions_wait_for_a_product(page: Page, availo: products.Product) -> None:
    in_arabic(page)
    page.goto("/workbench")
    page.click("#addQuestionBtn")
    box = page.locator("#questionList textarea").last
    expect(box).to_have_attribute("placeholder", "اكتب سؤالاً…")
    box.fill("Do you encrypt backups?")
    expect(box).to_have_attribute("dir", "ltr")  # an English question reads left to right
    expect(page.locator("#answerBtn")).to_have_text("أجب عن سؤال واحد")
    expect(page.locator("#answerNeedsProduct")).to_contain_text("اختر المنتج أولاً.")
    expect(page.locator("#step1Held")).to_have_text("لم يُختر منتج · سؤال واحد مكتوب")
    arabic(page, "a typed question waiting for a product")

    page.locator("#answerOptions > summary").click()
    arabic(page, "a typed question, more options")


# --- "Or pick up", the offer of a file already open, and closing --------------------


def test_or_pick_up_and_deleting_from_it_are_arabic(page: Page, tmp_path: Path, availo: products.Product) -> None:
    user = identity.local_user()
    other = tools.open_form(user, shapes.simple(tmp_path / "other.xlsx"))
    vendor = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))
    tools.set_answer(user, vendor.id, vendor.form.questions[0].id, "We do.")

    in_arabic(page)
    page.goto("/workbench")
    row = page.locator("#formRecent .recent-item", has_text="vendor.xlsx")
    expect(row.locator("button.pick-up")).to_contain_text("vendor.xlsx (أُجيب عن 1)")
    [listed] = [form for form in batches.recent(TEAM) if form["id"] == vendor.id]
    day = retention.kept_until(listed["used_at"])
    assert day, "kept for RETENTION_DAYS (180) by default"
    kept = page.evaluate(
        "(day) => { const [y, m, d] = day.split('-').map(Number);"
        " return new Date(y, m - 1, d).toLocaleDateString('ar-u-ca-gregory-nu-latn',"
        " { day: 'numeric', month: 'long', year: 'numeric' }); }",
        day,
    )
    expect(row.locator(".recent-kept")).to_have_text("محفوظ حتى " + kept)
    assert re.search(r"\d", kept) and not re.search("[٠-٩]", kept), f"Gregorian, in Western digits: {kept}"
    used = row.locator(".recent-when")
    expect(used).to_have_text(re.compile(r"^استُخدم \S"))
    assert not re.search("[٠-٩]", used.inner_text()), "Western digits"
    arabic(page, "or pick up")

    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    row.get_by_role("button", name="حذف vendor.xlsx").click()
    assert asked and asked[0].startswith("هل تحذف «vendor.xlsx»؟"), asked
    assert "تُحذف معه إجابته الوحيدة" in asked[0] and "لا يمكن التراجع عن ذلك." in asked[0]

    page.once("dialog", lambda dialog: dialog.accept())
    row.get_by_role("button", name="حذف vendor.xlsx").click()
    expect(page.locator("#extractStatus")).to_have_text("حُذف vendor.xlsx مع إجابته الوحيدة.")
    arabic(page, "deleted")
    assert batches.load(other.id) is not None


def test_a_file_already_open_is_offered_and_closing_says_where_it_went(
    page: Page, tmp_path: Path, answers_yes: None, stores
) -> None:
    in_arabic(page)
    workbook = read_as_general(page, tmp_path)
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)
    expect(page.locator("#step4Held")).to_have_text("4 إجابات · لا شيء يحتاج إلى مراجعة")
    expect(page.locator("#keptUntil")).to_have_text(re.compile(r"^محفوظ حتى \d"))

    page.click("#closeForm")
    expect(page.locator("#extractStatus")).to_have_text("أُغلق vendor.xlsx. ويبقى في «أو تابِع من حيث توقفت» أدناه.")
    arabic(page, "closed")

    choose_general(page)
    page.set_input_files("#assessmentInput", str(workbook))
    offer = page.locator("#alreadyOpen")
    expect(offer).to_contain_text("لديك vendor.xlsx من قبل")
    expect(offer).to_contain_text("أُجيب عن 4 من 4")
    expect(offer.get_by_role("button", name="ابدأ من جديد (لـعام)")).to_be_visible()
    arabic(page, "the offer of a file already open")

    offer.get_by_role("button", name="إلغاء").click()
    expect(page.locator("#extractStatus")).to_have_text("لم يُفتح شيء.")


# --- what is said about the questionnaire as a whole ------------------------------


def test_a_deleted_products_questionnaire_and_a_run_on_the_server_are_said_in_arabic(
    page: Page, tmp_path: Path, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = identity.local_user()
    kept = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    tools.set_answer(user, kept.id, kept.form.questions[0].id, "Yes, every backup is encrypted.")
    products.delete(user, TEAM, availo.id, "confirm")

    in_arabic(page)
    page.goto(f"/workbench?q={kept.id}")
    note = page.locator("#formReadOnly")
    expect(note).to_contain_text("هذا الاستبيان محفوظ لتُقرأ إجاباته")
    expect(note.locator("[data-no-translate]")).to_have_text("Availo")
    expect(page.locator("#formProduct option:checked")).to_have_text("Availo (محذوف)")
    expect(page.locator("#questionListHint")).to_contain_text("محفوظ للقراءة فقط")
    arabic(page, "a deleted product's questionnaire")

    running = tools.open_form(user, shapes.simple(tmp_path / "other.xlsx"))
    monkeypatch.setitem(busy._HELD, running.id, busy._Hold(run_id="elsewhere", started_at="2026-11-07T09:00:00+00:00"))
    page.goto(f"/workbench?q={running.id}")
    expect(note).to_contain_text("تجري الإجابة على الخادم، وبدأ في")
    expect(page.locator("#answerStatus")).to_contain_text("تجري الإجابة على الخادم…")
    arabic(page, "being answered on the server")


def test_an_address_that_opens_nothing_and_a_file_with_no_questions_say_why(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    in_arabic(page)
    page.goto("/workbench?q=abcdef1234567890")
    expect(page.locator("#extractStatus")).to_have_text(
        "تعذّر فتح الاستبيان الوارد في هذا العنوان: فهو ليس من استبياناتك، أو لم يعد موجوداً."
    )
    arabic(page, "an address naming nothing of yours")

    user = identity.local_user()
    notes = shapes.build(tmp_path / "notes.xlsx", [shapes.SheetSpec("Security", {"A1": "Security review notes"})])
    path = service.save_upload("notes.xlsx", notes.read_bytes(), TEAM, owner=user.email)
    tools.open_form(user, path, strategy="rules")
    page.goto("/workbench")
    page.locator("#formRecent button", has_text="notes.xlsx").click()
    status = page.locator("#extractStatus")
    expect(status).to_contain_text("لم تُقرأ أي أسئلة من notes.xlsx.")
    expect(status).to_contain_text("تحقّق مما تم العثور عليه أدناه، أو افتح الملف مجدداً.")
    expect(page.locator("#formPartsList .pcount")).to_have_text(["فارغة"])
    arabic(page, "a file with no questions")


# --- the search drawer --------------------------------------------------------------


def test_the_search_drawer_is_arabic_with_results_and_without(
    page: Page, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    found: list[dict] = [
        {
            "source_name": "Availo standard.pdf",
            "source_type": "guideline",
            "locator": "Availo standard.pdf §1",
            "snippet": "What Availo standard.pdf says about MFA.",
            "score": 0.8,
            "is_lexical": False,
            "product_id": availo.id,
        },
        {
            "source_name": "Access.pdf",
            "source_type": "prior_answer",
            "locator": "Access.pdf §2",
            "snippet": "MFA is required.",
            "score": 1.0,
            "is_lexical": True,
            "product_id": "",
        },
    ]

    async def search(query, **options):
        return {"query": query, "mode": "hybrid", "results": found if query == "MFA" else [], "documents": []}

    monkeypatch.setattr("src.api.service.search_knowledge", search)
    in_arabic(page)
    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    page.click("#searchOpen")
    expect(page.locator("#searchScope option:checked")).to_have_text("Availo والسياسات المشتركة")

    page.fill("#searchInput", "MFA")
    page.press("#searchInput", "Enter")
    hits = page.locator("#searchResults .search-hit")
    expect(hits).to_have_count(2)
    expect(page.locator("#searchStatus")).to_have_text("مقطعان")
    expect(hits.first.locator(".badge")).to_have_text("التشابه 0.80")
    expect(hits.last.locator(".badge")).to_have_text("مطابقة حرفية")
    expect(hits.last.locator(".tag.prior_answer")).to_have_text("إجابة سابقة")
    arabic(page, "search results", within="#searchDrawer")

    page.fill("#searchInput", "nothing")
    page.press("#searchInput", "Enter")
    expect(page.locator("#searchResults .search-empty")).to_have_text(
        "لم يطابق ذلك أي شيء في وثائق Availo أو في السياسات المشتركة."
    )
    arabic(page, "a search that found nothing", within="#searchDrawer")


# --- the administrators' drawer -------------------------------------------------------


def test_the_access_panel_is_arabic(page: Page, monkeypatch: pytest.MonkeyPatch, stores) -> None:
    monkeypatch.setattr(settings, "admin_email", ADMIN)
    monkeypatch.setattr(settings, "admin_password", "browser-test-password")
    identity.bootstrap()
    generated = access_codes.waiting(TEAM)
    assert generated
    in_arabic(page, person=False)
    interface_language.choose(ADMIN, "ar")

    page.goto("/workbench")
    expect(page.locator("#authGate")).to_be_visible()
    arabic(page, "signing in", within="#authGate")
    page.fill("#authEmail", ADMIN)
    page.fill("#authCode", "browser-test-password")
    page.click("#authSubmit")
    expect(page.locator("#adminLink")).to_have_text("الصلاحيات")
    page.click("#adminLink")

    drawer = page.locator("#adminDrawer")
    expect(drawer.get_by_text("أُنشئ عند التشغيل:")).to_be_visible()
    expect(drawer.get_by_text(generated, exact=True)).to_be_visible()
    expect(drawer.locator("#adminUsers")).to_contain_text("أنت")
    arabic(page, "the access panel", within="#adminDrawer")

    page.fill("#adminNewEmail", "alice@example.test")
    page.click("#adminAddUser")
    expect(page.locator("#adminDone")).to_have_text("تمت إضافة alice@example.test.")
    expect(drawer.locator("#adminUsers tr", has_text="alice@example.test")).to_contain_text("نشط")
    arabic(page, "a person added", within="#adminDrawer")

    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    drawer.locator("#adminUsers tr", has_text="alice@example.test").get_by_role("button", name="إزالة").click()
    assert asked and asked[0].startswith("هل تزيل alice@example.test؟"), asked

    page.click("#adminAddTeam")  # no id given
    expect(page.locator("#adminError")).to_have_text("أدخل معرّف الفريق.")
    arabic(page, "an error in the access panel", within="#adminDrawer")


# --- a phone's width, and a wide window ------------------------------------------------


@pytest.mark.parametrize("width", [375, 1280])
def test_nothing_scrolls_sideways_in_arabic(page: Page, tmp_path: Path, one_held: None, stores, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 812})
    in_arabic(page)
    page.goto("/workbench")
    fits(page)

    read_as_general(page, tmp_path)
    page.click("#step2Toggle")
    fits(page)
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(1, timeout=15_000)
    fits(page)
    with page.expect_download():
        page.click("#fillFormBtn")
    expect(page.locator("#formFilled")).to_be_visible()
    page.locator("#moreActions > summary").click()
    fits(page)
    assert not english_on_screen(page, names=IN_ATTRIBUTES)

    page.click("#searchOpen")
    fits(page)
