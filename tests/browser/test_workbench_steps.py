"""The Workbench in steps, in a real browser (plan 033, part A).

It was one long scroll: with 120 questions at 1366x768, Answer sat 14,000
pixels down and Fill sixty screens. It is now five steps under a header that
says where the questionnaire is: choose and load, check what was found,
answer, review, fill and download. A step that is done folds to one line saying
what it holds, and opens again. Reading starts as soon as a file and a product
are both there; Answer is in a bar that stays in view; Fill and download is one
action; everything else that takes the answers out is under "More".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import batches, identity, knowledge, products
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.browser.choosing import choose_general
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team
ANSWER = "Yes, an approved policy is in place and reviewed annually."


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
                review_reasons=["the sources disagree"] if index == 1 else [],
            )
            for index, q in enumerate(questions)
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


@pytest.fixture
def availo(monkeypatch: pytest.MonkeyPatch) -> products.Product:
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        return made.setdefault((team_id or TEAM, product_id), bare_store(FakeVectorStore([])))

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo", color="#16a34a")


def forms_posted(page: Page) -> list[str]:
    """Every questionnaire the page sends to be read."""
    sent: list[str] = []
    page.on(
        "request",
        lambda request: (
            sent.append(request.url) if request.method == "POST" and request.url.endswith("/api/forms") else None
        ),
    )
    return sent


def step(page: Page, number: int):
    return page.locator(f"#stepList button[data-step='{number}']")


# --- the step header, and steps that fold ----------------------------------------


def test_the_header_says_where_the_questionnaire_is_and_a_done_step_folds_to_one_line(
    page: Page, tmp_path: Path, answers_yes: None
) -> None:
    page.goto("/workbench")
    expect(page.locator("#stepList button")).to_have_text(
        ["1Choose and load", "2Check what was found", "3Answer", "4Review", "5Fill and download"]
    )
    expect(step(page, 1)).to_have_attribute("aria-current", "step")
    expect(page.locator("#step1Body")).to_be_visible()
    for later in ("#step2", "#resultsCard", "#step5"):
        expect(page.locator(later)).to_be_hidden()
    expect(step(page, 4)).to_be_disabled()

    choose_general(page)
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))

    held = page.locator("#step1Held")
    expect(held).to_have_text("General · vendor.xlsx · 4 questions in 1 sheet")
    expect(page.locator("#step1Body")).to_be_hidden()
    expect(page.locator("#step1")).to_have_class(re.compile(r"\bfolded\b"))
    expect(step(page, 1)).to_have_class(re.compile(r"\bdone\b"))
    expect(step(page, 3)).to_have_attribute("aria-current", "step")
    expect(page.locator("#stepTitle")).to_have_text("vendor.xlsx")

    page.click("#step1Toggle")  # opened again, with what it holds
    expect(page.locator("#step1Body")).to_be_visible()
    expect(page.locator("#formProduct")).to_be_disabled()  # fixed for the questionnaire, as before
    page.click("#step1Toggle")
    expect(page.locator("#step1Body")).to_be_hidden()

    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)
    expect(step(page, 3)).to_have_class(re.compile(r"\bdone\b"))
    expect(step(page, 5)).to_have_attribute("aria-current", "step")  # nothing needs review
    expect(page.locator("#step3Held")).to_have_text("4 of 4 answered")
    expect(page.locator("#step5")).to_be_visible()

    step(page, 1).click()  # the header opens a step too
    expect(page.locator("#step1Body")).to_be_visible()


def test_step_2_is_folded_unless_a_reading_is_worth_checking(page: Page, tmp_path: Path) -> None:
    page.goto("/workbench")
    choose_general(page)
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    expect(page.locator("#step2Held")).to_have_text("Found 4 questions in 1 sheet")
    expect(page.locator("#step2Body")).to_be_hidden()
    page.click("#step2Toggle")
    expect(page.locator("#formPartsList")).to_contain_text("Questionnaire")
    expect(page.locator("#formColumns select").first).to_be_visible()  # the column checks stay
    page.click("#closeForm")

    choose_general(page)
    page.set_input_files("#assessmentInput", str(shapes.headless_numbered(tmp_path / "headless.xlsx")))
    expect(page.locator("#step2Held")).to_contain_text("worth checking")
    expect(page.locator("#step2Body")).to_be_visible()
    expect(page.locator("#formPartsList")).to_contain_text("worth checking —")
    expect(step(page, 2)).to_have_attribute("aria-current", "step")


# --- step 1: a product and a file in one place, read with no second click ---------


def test_a_file_is_read_as_soon_as_it_is_given_when_a_product_is_chosen(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    sent = forms_posted(page)
    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    expect(page.locator("#dropFor")).to_have_text("Read for Availo as soon as it is here.")

    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))

    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)
    assert len(sent) == 1, "read once, with no click"
    [opened] = batches.recent(TEAM)
    assert opened["product_id"] == availo.id


def test_a_file_given_before_the_product_waits_for_it_and_says_so(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    """The product is fixed when the questionnaire is made, so nothing is sent before one is chosen."""
    sent = forms_posted(page)
    page.goto("/workbench")
    expect(page.locator("#dropFor")).to_have_text("Choose the product first; a file given now waits for it.")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))

    waiting = page.locator("#readNeedsProduct")
    expect(waiting).to_have_text(
        "vendor.xlsx is waiting for the product: choose one above, and it is read straight away."
    )
    expect(page.locator("#assessmentChosen")).to_have_text("vendor.xlsx")
    expect(page.locator("#formProduct")).to_be_focused()
    expect(step(page, 1)).to_have_attribute("aria-current", "step")
    page.wait_for_timeout(300)
    assert sent == [] and batches.recent(TEAM) == []

    page.select_option("#formProduct", availo.id)
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)
    expect(waiting).to_be_hidden()
    assert len(sent) == 1
    assert batches.recent(TEAM)[0]["product_id"] == availo.id


def test_typing_questions_is_the_other_way_in(page: Page, answers_yes: None) -> None:
    page.goto("/workbench")
    expect(page.locator("#questionListTitle")).to_have_text("Or type the questions yourself")
    expect(page.locator("#step3 > .step-head")).to_be_hidden()  # under step 1, not a step with nothing in it
    expect(page.locator("#answerBar")).to_be_hidden()

    page.click("#addQuestionBtn")
    page.get_by_role("textbox", name="Type a question").last.fill("Do you encrypt backups?")
    expect(page.locator("#step3 > .step-head")).to_be_visible()
    expect(page.locator("#answerBtn")).to_have_text("Answer 1 question")
    expect(step(page, 2)).to_have_class(re.compile(r"\bskipped\b"))  # nothing was found to check

    choose_general(page)
    expect(page.locator("#step1Held")).to_have_text("General · 1 typed question")
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(1, timeout=15_000)
    # No file to fill: the downloads are the way out, so "More" is open.
    expect(page.locator("#exportPdf")).to_be_visible()
    expect(page.locator("#fillFormBtn")).to_be_hidden()


# --- step 3: one Answer button, in view, with the options under "More options" ----


def test_the_answer_bar_stays_in_view_over_a_long_list(page: Page, tmp_path: Path) -> None:
    """Measured before: with 120 questions at 1366x768, Answer was at y = 14,479."""
    page.set_viewport_size({"width": 1366, "height": 768})
    page.goto("/workbench")
    choose_general(page)
    page.set_input_files("#assessmentInput", str(shapes.numbered(tmp_path / "long.xlsx", 120)))
    expect(page.locator("#questionList .qrow")).to_have_count(120)

    answer = page.locator("#answerBtn")
    expect(answer).to_have_text("Answer 120 questions")
    expect(answer).to_be_in_viewport()
    page.locator("#questionList .qrow").nth(60).scroll_into_view_if_needed()
    expect(answer).to_be_in_viewport()
    box = answer.bounding_box()
    assert box and box["y"] + box["height"] <= 768, "on screen, at the bottom of the window"

    style = page.locator("#answerStyle")
    expect(style).to_be_hidden()  # under "More options"
    expect(page.locator("#languageSelect")).to_be_hidden()
    page.locator("#answerOptions > summary").click()
    expect(style).to_be_visible()
    expect(page.locator("#languageSelect")).to_be_visible()


# --- step 5: Fill and download, one action; the rest under "More" -----------------


def test_fill_and_download_is_one_action_and_says_what_was_written_and_held(
    page: Page, tmp_path: Path, one_held: None
) -> None:
    page.goto("/workbench")
    choose_general(page)
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(1, timeout=15_000)  # opens on Needs review
    fill = page.locator("#fillFormBtn")
    expect(fill).to_have_text("Fill and download")

    with page.expect_download() as downloaded:
        fill.click()
    assert downloaded.value.suggested_filename == "vendor - answered.xlsx"

    report = page.locator("#formFilled")
    expect(report).to_contain_text("Wrote 3 value(s) into vendor - answered.xlsx")
    expect(report).to_contain_text("vendor - answered.xlsx is downloading.")
    expect(report).to_contain_text("1 answer(s) were held back")
    report.get_by_text("Which, and why").click()
    expect(report.locator(".held-which li")).to_contain_text(["the sources disagree"])
    expect(report.get_by_role("button", name="Write them in anyway")).to_be_visible()
    expect(page.locator("#step5Held")).to_have_text("Wrote 3 values into vendor - answered.xlsx · 1 held back")

    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_download():
        report.get_by_role("button", name="Write them in anyway").click()
    expect(report).to_contain_text("Wrote 4 value(s) into vendor - answered.xlsx, including 1 answer(s) nobody")


def test_more_holds_the_other_downloads_the_rewording_and_another_question(
    page: Page, tmp_path: Path, answers_yes: None
) -> None:
    page.goto("/workbench")
    choose_general(page)
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)

    rest = (
        "#exportPdf",
        "#exportDocx",
        "#exportCsv",
        "#exportJson",
        "#pdfCitations",
        "#reviseInstruction",
        "#composerInput",
    )
    for control in rest:
        expect(page.locator(control), control).to_be_hidden()
    expect(page.locator("#fillFormBtn")).to_be_visible()

    page.locator("#moreActions > summary").click()
    for control in rest:
        expect(page.locator(control), control).to_be_visible()


# --- step 4: review from the keyboard ---------------------------------------------


@pytest.fixture
def mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """q1 confident; q2 flagged; q3 below the threshold; q4 flagged."""

    async def answered(questions, language=None, run_id=None, **extra):
        made = []
        for index, q in enumerate(questions):
            if index == 0:
                made.append(AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False))
            else:
                made.append(
                    AnsweredQuestion(
                        question=q,
                        answer=["", "Partly.", "Probably.", "Not yet."][index],
                        confidence=0.3,
                        needs_review=True,
                        review_reasons=["the sources disagree"],
                    )
                )
        return made

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


def answered_with_review(page: Page, tmp_path: Path) -> None:
    page.goto("/workbench")
    choose_general(page)
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(3, timeout=15_000)


def approvals(page: Page) -> list[str]:
    sent: list[str] = []
    page.on("request", lambda request: sent.append(request.url) if request.url.endswith("/approve") else None)
    return sent


def test_the_keys_move_between_cards_and_an_accept_goes_on_to_the_next_held_answer(
    page: Page, tmp_path: Path, mixed: None
) -> None:
    answered_with_review(page, tmp_path)
    cards = page.locator("#results .answer")
    review = page.locator("#reviewTabs").get_by_role("button", name=re.compile(r"^Needs review"))
    expect(review).to_have_attribute("aria-pressed", "true")  # opens on what needs a person
    expect(page.locator("#reviewKeys")).to_contain_text("A accepts")
    expect(page.locator("#reviewDone")).to_have_text("0 of 3 reviewed")
    expect(page.get_by_role("button", name=re.compile("approve all", re.IGNORECASE))).to_have_count(0)

    page.keyboard.press("j")  # from nowhere in particular: the first card
    expect(cards.nth(0)).to_be_focused()
    expect(cards.nth(0)).to_have_attribute("tabindex", "0")  # the one card that takes Tab
    page.keyboard.press("j")
    expect(cards.nth(1)).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(cards.nth(2)).to_be_focused()
    page.keyboard.press("k")
    expect(cards.nth(1)).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(cards.nth(0)).to_be_focused()
    expect(cards.nth(0)).to_contain_text("Partly.")
    expect(cards.nth(1)).to_have_attribute("tabindex", "-1")

    page.keyboard.press("a")

    expect(page.locator("#reviewDone")).to_have_text("1 of 3 reviewed")
    expect(cards).to_have_count(2)  # accepted, it leaves Needs review
    focused = page.locator("#results .answer:focus")
    expect(focused).to_contain_text("Probably.")
    expect(page.locator("#reviewStatus")).to_contain_text("Approved.")

    page.locator("#reviewTabs").get_by_role("button", name=re.compile(r"^All")).click()
    probably = page.locator("#results .answer", has_text="Probably.")
    probably.focus()
    page.keyboard.press("a")  # in All the accepted card stays, and the keyboard leaves it
    expect(probably.get_by_role("button", name="Approved ✓")).to_be_visible()
    expect(page.locator("#results .answer:focus")).to_contain_text("Not yet.")
    expect(page.locator("#reviewDone")).to_have_text("2 of 3 reviewed")


def test_e_edits_the_card_in_focus_and_esc_closes_the_editor_keeping_the_edit(
    page: Page, tmp_path: Path, mixed: None
) -> None:
    answered_with_review(page, tmp_path)
    sent = approvals(page)
    card = page.locator("#results .answer", has_text="Probably.")
    card.focus()

    page.keyboard.press("e")
    editor = card.locator("textarea")
    expect(editor).to_be_visible()
    expect(editor).to_be_focused()
    page.keyboard.type(" Just a key: j, k and a")  # typed into the editor, never taken as keys
    expect(editor).to_have_value("Probably. Just a key: j, k and a")
    assert sent == []

    page.keyboard.press("Escape")
    expect(page.locator("#reviewStatus")).to_contain_text("Your edit is saved")
    expect(page.locator("#results textarea:visible")).to_have_count(0)
    expect(page.locator("#results .answer:focus")).to_have_count(1)
    page.locator("#reviewTabs").get_by_role("button", name=re.compile(r"^Done by a person")).click()
    expect(page.locator("#results .answer")).to_contain_text(["Probably. Just a key: j, k and a"])


def test_the_keys_never_act_while_a_person_types_or_with_the_browsers_own_keys(
    page: Page, tmp_path: Path, mixed: None
) -> None:
    answered_with_review(page, tmp_path)
    sent = approvals(page)
    page.locator("#moreActions > summary").click()
    composer = page.locator("#composerInput")
    composer.focus()
    page.keyboard.type("jake")
    expect(composer).to_have_value("jake")
    expect(composer).to_be_focused()

    card = page.locator("#results .answer").first
    card.focus()
    page.keyboard.press("Control+a")  # the browser's select-all, not an accept
    page.keyboard.press("Alt+e")
    expect(card).to_be_focused()
    expect(card.locator("textarea")).to_be_hidden()
    page.wait_for_timeout(300)
    assert sent == []


# --- the cards, smaller ------------------------------------------------------------

LONG = (
    "Does the vendor maintain a documented brand-protection programme covering the monitoring of "
    "look-alike domains, social media impersonation, counterfeit goods and unauthorised use of the "
    "organisation's trademarks across every market in which it operates, with named owners, an "
    "escalation route to legal, and evidence of takedowns completed in the last twelve months?"
)


def test_a_card_folds_a_long_question_to_two_lines_with_its_controls_and_sources_in_one_row(page: Page) -> None:
    page.set_viewport_size({"width": 900, "height": 800})
    page.goto("/workbench")
    page.evaluate(
        """(question) => {
             const card = Cards.render({
               question: { id: "7", text: question, question_type: "free_text" }, answer: "Yes.",
               confidence: 0.9, needs_review: false, review_reasons: [], length: "full",
               citations: ["Policy.pdf §2"], evidence: [{ source_type: "guideline", source_name: "Policy.pdf",
                 locator: "Policy.pdf §2", snippet: "We monitor look-alike domains.", score: 0.8 }],
             }, 0);
             card.id = "probe";
             document.querySelector("main").prepend(card);
           }""",
        LONG,
    )
    card = page.locator("#probe")
    question = card.locator(".qtext")
    lines = question.evaluate("el => Math.round(el.clientHeight / parseFloat(getComputedStyle(el).lineHeight))")
    assert lines == 2, f"the question shows {lines} lines"
    more = card.get_by_role("button", name="show the whole question")
    expect(more).to_be_visible()
    more.click()
    assert question.evaluate("el => el.scrollHeight <= el.clientHeight + 1"), "the whole question, once asked for"

    controls = card.locator(".card-controls > button:visible")
    expect(controls).to_have_text(["Approve", "Edit", "Leave blank"])
    tops = {round(box["y"]) for box in (button.bounding_box() for button in controls.all()) if box}
    assert len(tops) == 1, f"the controls are in one row: {tops}"

    sources = card.locator(".cites")
    expect(sources.locator(".cites-label")).to_have_text("Sources")
    chip = sources.locator(".cite")
    label_box, chip_box = sources.locator(".cites-label").bounding_box(), chip.bounding_box()
    assert label_box and chip_box and abs(label_box["y"] - chip_box["y"]) < chip_box["height"], "one row"
    chip.click()
    expect(card.locator(".cite-panel")).to_contain_text("We monitor look-alike domains.")
