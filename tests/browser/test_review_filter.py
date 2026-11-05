"""The review queue on the Workbench (plan 029, 1.3).

Reviewing a long questionnaire meant scrolling every card to find the few the
fill gate holds back, with Fill and its counts past the last one, and the whole
question list repeated above the cards. The answers are now in tabs by what
the gate says of them, the default is what needs a person, a bar keeps Fill and
the counts in reach, and the question list folds once there are answers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.browser.choosing import choose_general

pytestmark = pytest.mark.browser

ANSWER = "Yes, an approved policy is in place and reviewed annually."


@pytest.fixture
def mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """q1 confident; q2 flagged; q3 below the threshold with no flag; q4 failed. The rest of a longer file confident."""

    async def answered(questions, language=None, run_id=None, **extra):
        made = []
        for index, q in enumerate(questions):
            if index == 1:
                made.append(
                    AnsweredQuestion(
                        question=q,
                        answer="Partly.",
                        confidence=0.45,
                        needs_review=True,
                        review_reasons=["the sources disagree"],
                    )
                )
            elif index == 2:
                made.append(AnsweredQuestion(question=q, answer="Probably.", confidence=0.30, needs_review=False))
            elif index == 3 and len(questions) == 4:
                made.append(AnsweredQuestion(question=q, answer="", error="the model was unavailable"))
            else:
                made.append(AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False))
        return made

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


@pytest.fixture
def one_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every answer confident but the last, which is flagged."""

    async def answered(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=q,
                answer=ANSWER,
                confidence=0.9,
                needs_review=index == len(questions) - 1,
                review_reasons=["the sources disagree"] if index == len(questions) - 1 else [],
            )
            for index, q in enumerate(questions)
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


def answered(page: Page, workbook: Path, count: int) -> None:
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(workbook))
    choose_general(page)
    page.click("#extractBtn")
    expect(page.locator("#questionList .qrow")).to_have_count(count)
    page.click("#answerBtn")
    expect(page.locator("#reviewBar")).to_be_visible(timeout=15_000)


def tab(page: Page, name: str):
    return page.locator("#reviewTabs").get_by_role("button", name=re.compile("^" + re.escape(name) + " \\("))


def test_the_review_opens_on_the_answers_that_need_a_person(page: Page, tmp_path: Path, mixed: None) -> None:
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)

    expect(tab(page, "Needs review")).to_have_text("Needs review (3)")
    expect(tab(page, "Needs review")).to_have_attribute("aria-pressed", "true")
    expect(tab(page, "Will be written")).to_have_text("Will be written (1)")
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (0)")
    expect(tab(page, "Blank or set aside")).to_have_text("Blank or set aside (0)")
    expect(tab(page, "All")).to_have_text("All (4)")
    cards = page.locator("#results .answer")
    expect(cards).to_have_count(3)
    expect(cards.filter(has_text=ANSWER)).to_have_count(0)
    expect(page.locator("#reviewCounts")).to_have_text("1 will be written · 3 need review")

    tab(page, "All").click()
    expect(cards).to_have_count(4)
    expect(tab(page, "All")).to_have_attribute("aria-pressed", "true")


def test_choosing_a_tab_from_the_keyboard_keeps_the_keyboards_place(page: Page, tmp_path: Path, mixed: None) -> None:
    """Plan 029's review: the tabs are drawn again on each choice, and the focus fell to the page,
    so a screen reader said nothing and the next Tab began again at the first tab."""
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    tab(page, "All").focus()

    page.keyboard.press("Enter")

    expect(tab(page, "All")).to_have_attribute("aria-pressed", "true")
    expect(tab(page, "All")).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.locator("#fillFormBtn")).to_be_focused()


def test_a_low_score_with_no_flag_counts_as_needing_review(page: Page, tmp_path: Path, mixed: None) -> None:
    """The summary counted the "needs review" chip: an unflagged answer under the threshold was missed."""
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)

    expect(page.locator("#results .answer", has_text="Probably.")).to_be_visible()
    review = page.locator("#resultsSummary .stat", has_text="need review")
    expect(review.locator(".value")).to_have_text("3")


def test_approving_moves_an_answer_out_of_needs_review(page: Page, tmp_path: Path, mixed: None) -> None:
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    flagged = page.locator("#results .answer", has_text="Partly.")

    flagged.get_by_role("button", name="Approve", exact=True).click()

    expect(tab(page, "Needs review")).to_have_text("Needs review (2)")
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (1)")
    expect(tab(page, "Needs review")).to_have_attribute("aria-pressed", "true")  # the reviewer stays in the queue
    expect(flagged).to_have_count(0)
    expect(page.locator("#reviewStatus")).to_contain_text("Approved")
    tab(page, "Done by a person").click()
    expect(page.locator("#results .answer")).to_have_text([re.compile("Partly.")])


def test_editing_moves_an_answer_out_of_needs_review(page: Page, tmp_path: Path, mixed: None) -> None:
    """Plan 029's review: an edit is a person's and goes in, but the card stayed in Needs review,
    still "Not going into the file yet", and the bar's counts disagreed with what Fill writes."""
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    expect(page.locator("#reviewCounts")).to_have_text("1 will be written · 3 need review")
    flagged = page.locator("#results .answer", has_text="Partly.")

    flagged.get_by_role("button", name="Edit", exact=True).click()
    flagged.locator("textarea").fill("Partly: at the two main sites.")
    flagged.get_by_role("button", name="Done editing").click()

    expect(page.locator("#reviewStatus")).to_contain_text("Your edit is saved")
    expect(tab(page, "Needs review")).to_have_text("Needs review (2)")
    expect(tab(page, "Needs review")).to_have_attribute("aria-pressed", "true")
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (1)")
    expect(page.locator("#reviewCounts")).to_have_text("2 will be written · 2 need review")
    expect(page.locator("#results .answer", has_text="Partly")).to_have_count(0)
    tab(page, "Done by a person").click()
    edited = page.locator("#results .answer")
    expect(edited).to_have_text([re.compile("Partly: at the two main sites.")])
    expect(edited).not_to_contain_text("Not going into the file yet")


def test_an_edit_saved_while_another_card_is_edited_leaves_that_editor_open(
    page: Page, tmp_path: Path, mixed: None
) -> None:
    """An edit is saved when its editor is left, by the click that opens the next one: redrawn
    then, the cards would close the editor the person had just opened."""
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    first = page.locator("#results .answer", has_text="Partly.")
    second = page.locator("#results .answer", has_text="Probably.")
    first.get_by_role("button", name="Edit", exact=True).click()
    first.locator("textarea").fill("Partly: at the two main sites.")

    second.get_by_role("button", name="Edit", exact=True).click()  # leaving the first saves it
    second.locator("textarea").press_sequentially(" Not yet.")

    expect(page.locator("#reviewStatus")).to_contain_text("Your edit is saved")
    expect(second.locator("textarea")).to_be_visible()
    expect(second.locator("textarea")).to_be_focused()
    expect(second.locator("textarea")).to_have_value("Probably. Not yet.")
    expect(tab(page, "Needs review")).to_have_text("Needs review (2)")
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (1)")

    second.get_by_role("button", name="Done editing").click()  # nobody typing now: both cards move
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (2)")
    expect(page.locator("#results .answer")).to_have_count(1)  # the failed one is left


def test_approving_from_the_keyboard_goes_on_to_the_next_answer(page: Page, tmp_path: Path, mixed: None) -> None:
    """Drawn again, the cards dropped the keyboard's place: the next Tab started from the top of the page."""
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    approve = page.locator("#results .answer", has_text="Partly.").get_by_role("button", name="Approve", exact=True)
    approve.focus()
    page.keyboard.press("Enter")

    expect(tab(page, "Needs review")).to_have_text("Needs review (2)")
    expect(page.locator("#results .answer").first).to_be_focused()
    expect(page.locator("#results .answer").first).to_contain_text("Probably.")


def test_a_question_asked_beside_an_answered_questionnaire_stays_in_view(
    page: Page, tmp_path: Path, mixed: None
) -> None:
    """Plan 029's review: after every run the review went back to Needs review, where a typed
    question's confident answer has no place. The person's All was overridden and the answer hidden."""
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    tab(page, "All").click()
    expect(page.locator("#results .answer")).to_have_count(4)

    page.fill("#composerInput", "Do you run penetration tests every year?")
    page.click("#composerAdd")
    page.click("#composerAnswer")

    expect(tab(page, "All")).to_have_text("All (5)")
    expect(tab(page, "All")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#results .answer", has_text="penetration")).to_have_count(1)

    tab(page, "Needs review").click()  # asked from Needs review, it is shown too
    page.fill("#composerInput", "Do you train every new joiner?")
    page.click("#composerAdd")
    page.click("#composerAnswer")
    expect(tab(page, "All")).to_have_text("All (6)")
    expect(tab(page, "All")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#results .answer", has_text="new joiner")).to_have_count(1)


def test_a_run_of_the_file_and_a_typed_question_says_where_the_typed_answer_is(
    page: Page, tmp_path: Path, mixed: None
) -> None:
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    choose_general(page)
    page.click("#extractBtn")
    expect(page.locator("#questionList .qrow")).to_have_count(4)
    page.click("#addQuestionBtn")
    page.locator("#questionList textarea").last.press_sequentially("Do you run penetration tests every year?")

    page.click("#answerBtn")

    expect(tab(page, "Needs review")).to_have_attribute("aria-pressed", "true", timeout=15_000)
    expect(page.locator("#answerStatus")).to_contain_text(
        "The answers to 1 you typed beside the file are under All: they are not rows in it."
    )
    tab(page, "All").click()
    expect(page.locator("#results .answer", has_text="penetration")).to_have_count(1)


def test_set_aside_and_blank_answers_have_their_own_tab(page: Page, tmp_path: Path, mixed: None) -> None:
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    page.locator("#results .answer", has_text="Probably.").get_by_role("button", name="Leave blank").click()
    expect(tab(page, "Blank or set aside")).to_have_text("Blank or set aside (1)")
    page.locator("#questionListSummary").click()  # the folded list, where a row is set aside
    page.locator("#questionList .qrow").first.get_by_role("button", name="Set aside").click()

    expect(tab(page, "Blank or set aside")).to_have_text("Blank or set aside (2)")
    tab(page, "Blank or set aside").click()
    shown = page.locator("#results")
    expect(shown.locator(".answer")).to_have_count(1)
    expect(shown.locator(".qrow")).to_have_count(1)
    expect(shown.locator(".qrow").get_by_role("button", name="Include")).to_be_visible()
    expect(tab(page, "All")).to_have_text("All (3)")


def test_fill_and_the_counts_stay_in_view_while_scrolling(page: Page, tmp_path: Path, one_held: None) -> None:
    answered(page, shapes.numbered(tmp_path / "long.xlsx", 40), 40)
    tab(page, "All").click()
    cards = page.locator("#results .answer")
    expect(cards).to_have_count(40)

    cards.last.scroll_into_view_if_needed()

    expect(page.locator("#reviewBar")).to_be_in_viewport()
    expect(page.locator("#fillFormBtn")).to_be_in_viewport()
    expect(page.locator("#reviewCounts")).to_have_text("39 will be written · 1 need review")
    box = page.locator("#reviewBar").bounding_box()
    header = page.locator(".topbar").bounding_box()
    assert box and header and box["y"] >= header["y"] + header["height"] - 1, "below the page header, not under it"


UNCOVERED = """(element) => {
  const box = element.getBoundingClientRect();
  const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  return Boolean(hit) && (hit === element || element.contains(hit));
}"""
"""True when a click at the element's middle reaches it: on screen, and behind nothing that sticks."""


def test_fills_report_from_far_down_the_list_is_not_behind_the_bar(page: Page, tmp_path: Path, one_held: None) -> None:
    """Plan 029's review: scrolled into view as such, the report landed under the page header and
    the sticky bar, and neither "Write them in anyway" nor the download could be seen or clicked."""
    page.set_viewport_size({"width": 1366, "height": 768})
    answered(page, shapes.numbered(tmp_path / "long.xlsx", 40), 40)
    tab(page, "All").click()
    cards = page.locator("#results .answer")
    expect(cards).to_have_count(40)
    cards.last.scroll_into_view_if_needed()

    page.click("#fillFormBtn")

    filled = page.locator("#formFilled")
    expect(filled).to_contain_text("1 answer(s) were held back")
    for shown in (
        filled.locator(".held-note"),
        filled.get_by_role("button", name="Write them in anyway"),
        filled.get_by_role("button", name="Download the filled file"),
    ):
        expect(shown).to_be_visible()
        page.wait_for_function(UNCOVERED, arg=shown.element_handle(), timeout=5_000)


@pytest.fixture
def slow_rewording(monkeypatch: pytest.MonkeyPatch):
    """The wording instruction's pass after a run, held until `set()`."""
    import asyncio
    import threading

    gate = threading.Event()

    async def reword(answered, instruction, language=None, *, note=""):
        while not gate.is_set():
            await asyncio.sleep(0.05)
        return answered.model_copy(update={"answer": "Yes."})

    monkeypatch.setattr("src.tools.rewrite.rewrite", reword)
    yield gate
    gate.set()  # a rewording never outlives its test waiting


def test_fill_waits_while_the_run_is_reworded(page: Page, tmp_path: Path, one_held: None, slow_rewording) -> None:
    """Plan 029's review: drawing the answers before the rewording pass enabled Fill, and a fill
    could go out with the wording about to change."""
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    choose_general(page)
    page.click("#extractBtn")
    expect(page.locator("#questionList .qrow")).to_have_count(4)
    page.fill("#answerStyle", "Shorter.")
    page.click("#answerBtn")

    expect(page.locator("#reviewBar")).to_be_visible(timeout=15_000)
    expect(page.locator("#answerStatus")).to_contain_text("Reword")
    expect(page.locator("#fillFormBtn")).to_be_disabled()

    slow_rewording.set()
    expect(page.locator("#answerStatus")).to_contain_text("Reworded 4 answer(s).")
    expect(page.locator("#fillFormBtn")).to_be_enabled()


def test_writing_held_answers_in_anyway_is_offered_only_after_fill(page: Page, tmp_path: Path, mixed: None) -> None:
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    expect(page.locator("#reviewBar").get_by_role("button", name=re.compile("anyway"))).to_have_count(0)

    page.click("#fillFormBtn")

    filled = page.locator("#formFilled")
    expect(filled).to_contain_text("2 answer(s) were held back")  # the failed one has no text to hold
    expect(filled.get_by_role("button", name="Write them in anyway")).to_be_visible()
    expect(page.locator("#reviewBar").get_by_role("button", name=re.compile("anyway"))).to_have_count(0)
    tab(page, "All").click()
    filled.get_by_role("button", name="Show them").click()
    expect(tab(page, "Needs review")).to_have_attribute("aria-pressed", "true")


def test_the_question_list_folds_once_answers_exist(page: Page, tmp_path: Path, one_held: None) -> None:
    answered(page, shapes.numbered(tmp_path / "long.xlsx", 40), 40)
    tab(page, "All").click()
    rows = page.locator("#questionList .qrow")
    expect(rows.first).to_be_hidden()
    expect(page.locator("#questionListSummary")).to_have_text("Show the 40 questions (40 answered, 0 waiting)")
    folded = page.locator("#results .answer").first.bounding_box()

    page.locator("#questionListSummary").click()
    expect(rows.first).to_be_visible()
    unfolded = page.locator("#results .answer").first.bounding_box()
    assert folded and unfolded and unfolded["y"] - folded["y"] >= 1000

    page.locator("#questionListSummary").click()
    expect(rows.first).to_be_hidden()
    page.click("#addQuestionBtn")
    expect(rows.first).to_be_visible()
    expect(page.locator("#questionList textarea").last).to_be_focused()


def test_answers_the_file_arrived_with_leave_the_list_open(page: Page, tmp_path: Path) -> None:
    """They have no card to review, so the list stays where the work is: "Answer it again" lives there."""
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.already_answered(tmp_path / "last year.xlsx")))
    choose_general(page)
    page.click("#extractBtn")

    rows = page.locator("#questionList .qrow")
    expect(rows.first).to_be_visible()
    expect(rows.first.get_by_role("button", name="Answer it again")).to_be_visible()
    expect(page.locator("#reviewBar")).to_be_hidden()
