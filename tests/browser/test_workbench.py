"""The workbench page (`/workbench`) in a real browser: signing in, reading and answering a questionnaire, the Access panel."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Error, Page, expect

from src import access_codes, batches, identity, products, tools
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

ALICE = "alice@example.test"
ADMIN = "admin@example.test"
CODE = "BROWSER-TEST-CODE"
ANSWER = "Yes, an approved policy is in place and reviewed annually."
TEAM = settings.default_team


@pytest.fixture
def answers_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(questions, language=None, run_id=None, **extra):
        return [AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", fake)


def test_a_person_signs_in_with_the_team_code(page: Page) -> None:
    identity.ensure_team(settings.default_team)
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)

    page.goto("/workbench")
    expect(page.locator("#authGate")).to_be_visible()
    page.fill("#authEmail", ALICE)
    page.fill("#authCode", CODE)
    page.click("#authSubmit")

    expect(page.locator("#authGate")).to_be_hidden()
    expect(page.locator("#whoamiEmail")).to_have_text(ALICE)
    expect(page.locator("#adminLink")).to_be_hidden()


def test_a_wrong_code_is_refused_on_the_page(page: Page) -> None:
    identity.ensure_team(settings.default_team)
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)

    page.goto("/workbench")
    page.fill("#authEmail", ALICE)
    page.fill("#authCode", "NOT-THE-CODE")
    page.click("#authSubmit")

    expect(page.locator("#authError")).to_be_visible()
    expect(page.locator("#authGate")).to_be_visible()


def test_the_access_panel_shows_a_code_generated_at_startup(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    """TD-029: the code generated on an upgrade is on the page for administrators, not in the log."""
    monkeypatch.setattr(settings, "admin_email", ADMIN)
    monkeypatch.setattr(settings, "admin_password", "browser-test-password")
    identity.bootstrap()  # what the next restart does
    generated = access_codes.waiting(settings.default_team)
    assert generated

    page.goto("/workbench")
    page.fill("#authEmail", ADMIN)
    page.fill("#authCode", "browser-test-password")
    page.click("#authSubmit")
    expect(page.locator("#adminLink")).to_be_visible()
    page.click("#adminLink")

    expect(page.get_by_text("Generated at startup:")).to_be_visible()
    expect(page.get_by_text(generated, exact=True)).to_be_visible()


def test_a_questionnaire_is_read_answered_and_shown_as_cards(page: Page, tmp_path: Path, answers_yes: None) -> None:
    workbook = shapes.simple(tmp_path / "vendor.xlsx")

    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(workbook))
    page.click("#extractBtn")
    # Each question is an editable box: the list can be corrected before anything is answered.
    listed = page.get_by_role("textbox", name="Type a question")
    expect(listed).to_have_count(4)
    expect(listed.first).to_have_value("Does the vendor have documented information security policies?")

    page.click("#answerBtn")
    expect(page.locator("#results").get_by_text(ANSWER).first).to_be_visible(timeout=15_000)
    expect(page.locator("#results").get_by_text(ANSWER)).to_have_count(4)


# --- filling holds back what nobody has confirmed (TD-052) ---------------------


@pytest.fixture
def answers_doubtfully(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=q,
                answer=ANSWER,
                confidence=0.3,
                needs_review=True,
                review_reasons=["the sources do not cover this directly"],
            )
            for q in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", fake)


def read_and_answer(page: Page, tmp_path: Path) -> Path:
    workbook = shapes.simple(tmp_path / "vendor.xlsx")
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(workbook))
    page.click("#extractBtn")
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)
    return workbook


def test_filling_from_the_workbench_holds_back_unconfirmed_answers(
    page: Page, tmp_path: Path, answers_doubtfully: None
) -> None:
    """The button's click event arrived as `includeUnreviewed`, so every fill
    from this page wrote the answers the gate holds back."""
    read_and_answer(page, tmp_path)

    with page.expect_request("**/fill") as sent:
        page.click("#fillFormBtn")
    assert sent.value.post_data_json == {"include_unreviewed": False}

    filled = page.locator("#formFilled")
    expect(filled).to_contain_text("4 answer(s) were held back")
    expect(filled).to_contain_text("Nothing was written: 4 answer(s) are held back")
    expect(filled.get_by_role("button", name="Write them in anyway")).to_be_visible()
    filled.get_by_text("Which, and why").click()
    reasons = filled.locator(".held-which li")
    expect(reasons).to_have_count(4)
    for row in reasons.all():
        expect(row).to_contain_text("flagged for review -- the sources do not cover this directly")
    expect(reasons.first).to_contain_text("Does the vendor have documented information security policies?")


def test_write_them_in_anyway_asks_first_then_writes_them(page: Page, tmp_path: Path, answers_doubtfully) -> None:
    from src import batches, tools
    from src.forms.reading import read

    read_and_answer(page, tmp_path)
    page.click("#fillFormBtn")
    filled = page.locator("#formFilled")
    anyway = filled.get_by_role("button", name="Write them in anyway")
    expect(anyway).to_be_visible()

    sent: list[dict] = []
    page.on("request", lambda request: sent.append(request.post_data_json) if request.url.endswith("/fill") else None)
    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    anyway.click()
    expect(anyway).to_be_visible()
    assert asked and "Write 4 unconfirmed answer(s) into the file?" in asked[0]
    assert "Which, and why" in asked[0]
    assert sent == [], "dismissed: nothing is sent"

    page.once("dialog", lambda dialog: dialog.accept())
    anyway.click()
    expect(filled).to_contain_text(
        "Wrote 4 value(s) into vendor - answered.xlsx, including 4 answer(s) nobody has confirmed"
    )
    [batch] = batches.recent(settings.default_team)
    opened = batches.load(batch["id"])
    # The answers it was shown, by id, since plan 029's review: the server writes those and no others.
    assert sent == [{"include_unreviewed": True, "unreviewed_ids": [q.id for q in opened.form.questions]}]
    expect(filled.get_by_role("button", name="Write them in anyway")).to_have_count(0)

    written = read(tools._filled_path(opened), "rules").form.questions
    assert [q.existing_answer for q in written] == [ANSWER] * 4


def test_write_them_in_anyway_writes_no_more_than_it_counted(page: Page, tmp_path: Path, answers_doubtfully) -> None:
    """Plan 029's review: the confirm counted the answers held at the last Fill,
    and the server wrote whatever was held at the click. Withdrawing an approval
    in between put a third answer in under "Write 2" and "including 2"."""
    from src import batches, tools
    from src.forms.reading import read

    read_and_answer(page, tmp_path)
    # Plan 029, 1.3: the review opens on "Needs review", which an approved
    # answer leaves; this test follows the cards themselves, so it shows All.
    page.locator("#reviewTabs").get_by_role("button", name=re.compile("^All")).click()
    cards = page.locator("#results .answer")
    for index in (0, 1):
        cards.nth(index).get_by_role("button", name="Approve", exact=True).click()
        expect(cards.nth(index).get_by_role("button", name="Approved ✓")).to_be_visible()
    page.click("#fillFormBtn")
    filled = page.locator("#formFilled")
    expect(filled).to_contain_text("2 answer(s) were held back")

    cards.first.get_by_role("button", name="Approved ✓").click()  # held again, after the list was made
    expect(page.locator("#answerStatus")).to_contain_text("It will be held back")

    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.accept()))
    filled.get_by_role("button", name="Write them in anyway").click()
    expect(filled).to_contain_text("Wrote 3 value(s) into vendor - answered.xlsx, including 2 answer(s) nobody")
    assert asked and "Write 2 unconfirmed answer(s)" in asked[0]
    expect(filled).to_contain_text("1 answer(s) were held back")

    [batch] = batches.recent(settings.default_team)
    written = read(tools._filled_path(batches.load(batch["id"])), "rules").form.questions
    assert [q.existing_answer for q in written] == ["", ANSWER, ANSWER, ANSWER]


def test_a_file_name_is_shown_as_text_never_as_markup(page: Page) -> None:
    """TD-021: what the server says about a file reaches the status line as text."""
    name = '<img src=x onerror="window.__pwned=1">.txt'

    page.goto("/workbench")
    page.set_input_files("#assessmentInput", files=[{"name": name, "mimeType": "text/plain", "buffer": b"x"}])
    page.click("#extractBtn")

    status = page.locator("#extractStatus")
    expect(status).to_contain_text("not supported")
    expect(status).to_contain_text("<img")
    assert status.locator("img").count() == 0
    assert page.evaluate("window.__pwned") is None


# --- a reload opens what was open; "Or pick up" lists every one (plan 029, 1.1) -----


@pytest.fixture
def availo(monkeypatch: pytest.MonkeyPatch) -> products.Product:
    made: dict[tuple[str, str], object] = {}

    def get_store(team_id=None, *, product_id=""):
        return made.setdefault((team_id or TEAM, product_id), bare_store(FakeVectorStore([])))

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo", color="#16a34a")


def test_a_reload_opens_the_questionnaire_that_was_open(
    page: Page, tmp_path: Path, answers_yes: None, availo: products.Product
) -> None:
    """After a reload the Workbench was empty, and on General."""
    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)
    [opened] = batches.recent(TEAM)
    expect(page).to_have_url(re.compile(r"/workbench\?q=" + opened["id"] + "$"))

    page.reload()

    expect(page.locator("#results .answer")).to_have_count(4)
    expect(page.locator("#closeForm")).to_be_visible()
    expect(page.locator("#formProduct")).to_have_value(availo.id)
    expect(page.locator("#formProduct")).to_be_disabled()
    expect(page.locator("#extractStatus")).to_contain_text("Reopened vendor.xlsx")


def test_close_takes_the_questionnaire_out_of_the_address(page: Page, tmp_path: Path) -> None:
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    questions = page.get_by_role("textbox", name="Type a question")
    expect(questions).to_have_count(4)
    expect(page).to_have_url(re.compile(r"\?q=\w+$"))

    page.click("#closeForm")
    expect(page).to_have_url(re.compile(r"/workbench$"))
    page.reload()

    expect(page.locator("#formRecent button", has_text="vendor.xlsx")).to_be_visible()
    expect(questions).to_have_count(0)
    expect(page.locator("#closeForm")).to_be_hidden()


def test_an_address_naming_someone_elses_questionnaire_opens_nothing(page: Page, tmp_path: Path) -> None:
    """A questionnaire is its uploader's: a link to Bob's opens nothing for anybody else, and says so."""
    from src.forms.reading import read

    path = shapes.simple(tmp_path / "bobs.xlsx")
    theirs = batches.create(identity.User(email="bob@example.test", team_id=TEAM), path, read(path, "rules").form)

    page.goto(f"/workbench?q={theirs.id}")

    expect(page.locator("#extractStatus")).to_contain_text(
        "The questionnaire in this address could not be opened: it is not one of yours"
    )
    expect(page).to_have_url(re.compile(r"/workbench$"))
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(0)
    expect(page.locator("#closeForm")).to_be_hidden()


def test_pick_up_lists_every_questionnaire_last_changed_first(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three were offered, by upload: the one worked on yesterday was not among them."""
    from datetime import datetime, timedelta, timezone
    from itertools import count

    user = identity.local_user()
    start, ticks = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc), count()
    with monkeypatch.context() as clocked:
        clocked.setattr(
            "src.batches.store.utcnow", lambda: (start + timedelta(minutes=next(ticks))).isoformat(timespec="seconds")
        )
        opened = {name: tools.open_form(user, shapes.simple(tmp_path / f"{name}.xlsx")) for name in "abcde"}
        for name in ("b", "d"):  # worked on later, in this order
            batch = opened[name]
            tools.set_answer(user, batch.id, batch.form.questions[0].id, "We do.")

    page.goto("/workbench")

    offered = page.locator("#formRecent button")
    expect(offered).to_have_count(5)
    expect(offered).to_contain_text(["d.xlsx", "b.xlsx", "e.xlsx", "c.xlsx", "a.xlsx"])
    expect(page.locator("#formRecent .recent-list")).to_be_visible()
    expect(offered.first).to_contain_text("(1 answered)")
    expect(offered.first).to_have_attribute("title", re.compile("^Last changed "))


# --- the same file again offers the questionnaire already open (plan 029, 1.2) ---


def test_opening_a_file_already_open_offers_to_open_it_or_start_fresh(
    page: Page, tmp_path: Path, answers_yes: None
) -> None:
    """The same file again made a second, empty questionnaire beside the one with the answers."""
    read_and_answer(page, tmp_path)
    page.click("#closeForm")
    page.click("#extractBtn")  # the same file, still chosen

    offer = page.locator("#alreadyOpen")
    expect(offer).to_contain_text("You already have vendor.xlsx")
    expect(offer).to_contain_text("4 of 4 answered")
    expect(page.locator("#extractStatus")).not_to_contain_text("Reading")
    offer.get_by_role("button", name="Open it").click()

    expect(page.locator("#results .answer")).to_have_count(4)
    expect(offer).to_be_hidden()
    assert len(batches.recent(TEAM)) == 1

    page.click("#closeForm")
    page.click("#extractBtn")
    offer.get_by_role("button", name="Start fresh (for General)").click()

    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)
    expect(page.locator("#results .answer")).to_have_count(0)
    expect(offer).to_be_hidden()
    assert [form["answered"] for form in batches.recent(TEAM)] == [0, 4]

    page.click("#closeForm")
    page.click("#extractBtn")
    expect(offer).to_contain_text("You already have 2 questionnaires read from vendor.xlsx")
    offer.get_by_role("button", name="Cancel").click()
    expect(offer).to_be_hidden()
    expect(page.locator("#extractStatus")).to_contain_text("Nothing was opened.")
    assert len(batches.recent(TEAM)) == 2


def test_a_word_file_written_as_prose_is_read_again_as_text(page: Page, tmp_path: Path, monkeypatch) -> None:
    """Plan 029's review: its first read leaves an empty questionnaire, and the second read offered
    that, "0 of 0 answered", where it used to read the questions again."""
    from docx import Document

    from src import service
    from src.models import Question

    async def text_of(path):
        return "1. Do you encrypt data at rest?\n2. How long are logs kept?"

    async def questions_in(text):
        return "en", [
            Question(id="1", text="Do you encrypt data at rest?"),
            Question(id="2", text="How long are logs kept?"),
        ]

    monkeypatch.setattr(service, "extracted_document_text", text_of)
    monkeypatch.setattr(service, "extract_questions", questions_in)
    prose = tmp_path / "questions.docx"
    document = Document()
    document.add_paragraph("1. Do you encrypt data at rest?")
    document.add_paragraph("2. How long are logs kept?")
    document.save(str(prose))

    for _ in range(2):
        page.goto("/workbench")
        page.set_input_files("#assessmentInput", str(prose))
        page.click("#extractBtn")
        expect(page.locator("#extractStatus")).to_contain_text("Found 2 question(s) in questions.docx")
        expect(page.locator("#alreadyOpen")).to_be_hidden()
        expect(page.get_by_role("textbox", name="Type a question")).to_have_count(2)


# --- a run carries on after a reload or a timeout, and is followed (plan 029, 1.4) ---


@pytest.fixture
def gated(monkeypatch: pytest.MonkeyPatch):
    """The real answering path over a stand-in for the per-question pipeline,
    one question at a time: the first is answered at once, the rest when `open()` is called."""
    import asyncio
    import threading
    from types import SimpleNamespace

    gate = threading.Event()
    calls: list[str] = []

    async def answer_one(question, language, *, run_id="", **_):
        calls.append(question.id)
        if len(calls) > 1:
            while not gate.is_set():
                await asyncio.sleep(0.05)
        return AnsweredQuestion(question=question, answer=ANSWER, confidence=0.9, needs_review=False)

    monkeypatch.setattr("src.service.answer_one_question", answer_one)
    monkeypatch.setattr(settings, "max_concurrent_questions", 1)
    yield SimpleNamespace(calls=calls, open=gate.set)
    gate.set()  # a run never outlives its test waiting


def wait_until(page: Page, condition, seconds: float = 10) -> None:
    for _ in range(int(seconds * 20)):
        if condition():
            return
        page.wait_for_timeout(50)
    raise AssertionError("waited too long")


def test_a_reload_while_answering_follows_the_run_and_answers_once(page: Page, tmp_path: Path, gated) -> None:
    """A reload mid-run showed 0 answered and Answer enabled: a second, paid run was one click away."""
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)
    page.click("#answerBtn")
    [opened] = batches.recent(TEAM)
    wait_until(page, lambda: len(batches.answers(opened["id"])) >= 1)  # saved as it finished

    page.reload()

    note = page.locator("#formReadOnly")
    expect(note).to_contain_text("Being answered on the server: 1 of 4 done")
    expect(page.locator("#answerBtn")).to_be_disabled()
    expect(page.locator("#fillFormBtn")).to_be_disabled()
    cards = page.locator("#results .answer")
    expect(cards).to_have_count(1)
    expect(cards.first.get_by_role("button", name="Approve")).to_have_count(0)
    expect(page.locator("#closeForm")).to_be_enabled()

    gated.open()
    expect(cards).to_have_count(4, timeout=15_000)
    expect(page.locator("#answerStatus")).to_contain_text("Finished: every question has an answer.")
    expect(note).to_be_hidden()
    expect(cards.first.get_by_role("button", name="Approve")).to_be_visible()
    expect(page.locator("#fillFormBtn")).to_be_enabled()
    assert len(gated.calls) == 4, "every question answered once"


def test_a_timed_out_answer_request_is_followed_not_repeated(page: Page, tmp_path: Path, gated) -> None:
    """Past nginx's 15 minutes the page said "Request failed (504)" and offered Answer again, while the server carried on."""
    import threading

    import httpx

    def proxy_gives_up(route) -> None:
        sent = route.request
        threading.Thread(
            target=lambda: httpx.post(
                sent.url, content=sent.post_data_buffer, headers={"content-type": "application/json"}, timeout=60
            ),
            daemon=True,
        ).start()
        for _ in range(200):  # the run has started on the server
            if gated.calls:
                break
            threading.Event().wait(0.05)
        route.fulfill(status=504, content_type="text/html", body="<html>504 Gateway Time-out</html>")

    page.route("**/answer", proxy_gives_up)
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    page.click("#answerBtn")

    status = page.locator("#answerStatus")
    expect(status).to_contain_text("the answering carries on there")
    expect(page.locator("#answerBtn")).to_be_disabled()
    expect(page.locator("#formReadOnly")).to_contain_text("Being answered on the server")

    gated.open()
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)
    expect(status).to_contain_text("Finished: every question has an answer.")
    assert len(gated.calls) == 4, "every question answered once"


# --- leaving with unsaved work asks first (plan 029, 1.5) ------------------------


def leave(page: Page) -> list[str]:
    """Close the page as a person closing the tab would, and stay if asked. The kinds of dialog it raised."""
    asked: list[str] = []

    def stay(dialog) -> None:
        asked.append(dialog.type)
        dialog.dismiss()

    page.on("dialog", stay)
    page.close(run_before_unload=True)
    for _ in range(60):
        if asked or page.is_closed():
            break
        try:
            page.wait_for_timeout(50)
        except Error:  # it closed while waiting: nothing was asked
            break
    return asked


def test_leaving_with_an_edit_not_yet_saved_asks_first(page: Page, tmp_path: Path, answers_yes: None) -> None:
    """The editor saves when it is left, and closing the tab does not leave it."""
    read_and_answer(page, tmp_path)
    card = page.locator("#results .answer").first
    card.get_by_role("button", name="Edit", exact=True).click()
    card.locator("textarea").press_sequentially(" Reviewed in March.")

    assert leave(page) == ["beforeunload"]
    assert not page.is_closed()
    expect(card.locator("textarea")).to_have_value(ANSWER + " Reviewed in March.")


def test_typed_questions_ask_before_leaving(page: Page) -> None:
    """A question typed into the list is kept only by this page."""
    page.goto("/workbench")
    page.click("#addQuestionBtn")
    page.get_by_role("textbox", name="Type a question").last.press_sequentially("Do you test your backups?")

    assert leave(page) == ["beforeunload"]
    assert not page.is_closed()


def test_leaving_after_the_edit_is_saved_does_not_ask(page: Page, tmp_path: Path, answers_yes: None) -> None:
    read_and_answer(page, tmp_path)
    card = page.locator("#results .answer").first
    card.get_by_role("button", name="Edit", exact=True).click()
    card.locator("textarea").press_sequentially(" Reviewed in March.")
    card.get_by_role("button", name="Done editing").click()
    expect(page.locator("#answerStatus")).to_contain_text("Your edit is saved")

    assert leave(page) == []
    assert page.is_closed()


def test_a_questionnaire_with_everything_saved_leaves_quietly(page: Page, tmp_path: Path, answers_yes: None) -> None:
    read_and_answer(page, tmp_path)

    assert leave(page) == []
    assert page.is_closed()
