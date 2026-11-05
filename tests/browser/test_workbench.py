"""The workbench page (`/workbench`) in a real browser: signing in, reading and answering a questionnaire, the Access panel."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import access_codes, identity
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes

pytestmark = pytest.mark.browser

ALICE = "alice@example.test"
ADMIN = "admin@example.test"
CODE = "BROWSER-TEST-CODE"
ANSWER = "Yes, an approved policy is in place and reviewed annually."


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
