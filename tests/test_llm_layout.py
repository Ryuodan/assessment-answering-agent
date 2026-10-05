"""The model-assisted fallback for sheets the rules cannot read.

Almost none of this is about the model. The model proposes a layout; what
matters is everything around that -- when it is asked at all, what is checked
before its answer is believed, what overrides it, and the guarantee that
turning it on can add a sheet but never damage one. So the model is stubbed
throughout and the tests are about the machinery, which is where the failures
that would reach a customer's spreadsheet actually live.
"""

from __future__ import annotations

import pytest

from src import forms
from src.forms import llm_layout
from src.forms.llm_layout import ColumnReading, SheetReading
from src.forms.model import Role
from src.forms.xlsx_package import Workbook
from tests import forms_fixtures as shapes


def reading(**overrides) -> SheetReading:
    """A correct reading of `two_row_header`, for a test to spoil one field of."""
    fields = {
        "is_questionnaire": True,
        "header_row": 5,
        "question_column": "B",
        "columns": [
            ColumnReading(column="A", role="number", because="reference codes"),
            ColumnReading(column="C", role="status", because="dropdown"),
            ColumnReading(column="D", role="answer", because="free text"),
        ],
        "reason": "Questions run down column B under the headings on row 5.",
    }
    fields.update(overrides)
    return SheetReading(**fields)


@pytest.fixture
def book(tmp_path):
    """The two-row header: real, and outside every rule."""
    with Workbook(shapes.two_row_header(tmp_path / "assessment.xlsx")) as workbook:
        yield workbook, workbook["Assessment"]


def stub(monkeypatch, result, *, seen: dict | None = None):
    """Answer every layout question with `result` (or raise, if it is an error)."""

    class Model:
        def invoke(self, messages):
            if seen is not None:
                seen.setdefault("calls", []).append(messages)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(llm_layout, "structured_llm", lambda *a, **k: Model())


# --- the rules really cannot read this shape -------------------------------


def test_the_rules_find_nothing_on_a_two_row_header(tmp_path):
    """The premise of the whole module. If this ever starts passing, the
    fallback has stopped being needed for this shape and the fixture should be
    replaced with one that still defeats the rules."""
    form = forms.detect(shapes.two_row_header(tmp_path / "a.xlsx"))
    assert form.questions == []
    assert form.parts[0].kind == "no questions"


# --- what a reading has to survive before it is believed -------------------


def test_a_good_reading_produces_questions_and_targets(book):
    workbook, sheet = book
    part, questions = llm_layout.apply(workbook, sheet, reading())

    assert [q.text for q in questions][:2] == [
        "Is there a documented information security policy?",
        "Is the policy reviewed and approved annually?",
    ]
    assert questions[0].number == "1.1"
    assert {role.value: target.id for role, target in questions[0].targets.items()} == {
        "status": "Assessment!C6",
        "answer": "Assessment!D6",
    }
    assert questions[0].targets[Role.STATUS].vocabulary == ["Yes", "No", "Partial"]


def test_a_sheet_the_model_says_is_not_a_questionnaire_is_left_alone(book):
    workbook, sheet = book
    assert llm_layout.apply(workbook, sheet, reading(is_questionnaire=False)) is None


def test_a_question_column_holding_nothing_is_refused(book):
    """Column Z exists in no spreadsheet here. A reading naming it is a reading
    of some other file, and believing it would produce a sheet of empty rows."""
    workbook, sheet = book
    assert llm_layout.apply(workbook, sheet, reading(question_column="Z")) is None


def test_a_header_row_that_does_not_exist_is_refused(book):
    workbook, sheet = book
    assert llm_layout.apply(workbook, sheet, reading(header_row=97)) is None


def test_a_header_row_below_every_question_is_refused(book):
    """Rows 6-10 hold the questions. A header on row 10 leaves nothing under
    it, and the sheet would come back empty rather than wrong -- but it would
    come back having spent a call, and saying it had read the sheet."""
    workbook, sheet = book
    assert llm_layout.apply(workbook, sheet, reading(header_row=10)) is None


def test_a_negative_header_row_is_refused(book):
    workbook, sheet = book
    assert llm_layout.apply(workbook, sheet, reading(header_row=-1)) is None


def test_a_column_letter_the_sheet_does_not_have_is_dropped(book):
    """Not fatal -- the rest of the reading may be perfectly good -- but it
    cannot become a target, because there is nothing there to write into."""
    workbook, sheet = book
    part, questions = llm_layout.apply(
        workbook,
        sheet,
        reading(
            columns=[
                ColumnReading(column="C", role="status", because="dropdown"),
                ColumnReading(column="ZZ", role="answer", because="invented"),
            ]
        ),
    )
    assert [t.id for t in questions[0].targets.values()] == ["Assessment!C6"]


def test_a_role_that_is_not_a_role_is_dropped(book):
    workbook, sheet = book
    spoiled = reading()
    # Past the Literal, as a model bypassing structured output would manage.
    object.__setattr__(spoiled.columns[2], "role", "freetext")
    part, questions = llm_layout.apply(workbook, sheet, spoiled)
    assert "answer" not in {role.value for role in questions[0].targets}


def test_lower_case_and_spaced_column_letters_are_understood(book):
    """Worth accepting rather than refusing: ' c ' is the right answer typed
    untidily, and refusing it would cost a whole sheet over whitespace."""
    workbook, sheet = book
    part, questions = llm_layout.apply(
        workbook,
        sheet,
        reading(
            question_column=" b ",
            columns=[ColumnReading(column="c", role="status", because="dropdown")],
        ),
    )
    assert questions[0].targets[Role.STATUS].id == "Assessment!C6"


def test_a_reading_that_yields_no_questions_is_discarded(book):
    """Column A holds '1.1', '1.2' -- read as questions, every row fails the
    shape test and nothing comes out. Better to leave the sheet skipped than to
    report a sheet that was read and found empty."""
    workbook, sheet = book
    assert llm_layout.apply(workbook, sheet, reading(question_column="A")) is None


# --- what the model is not allowed to overrule -----------------------------


def test_a_banner_saying_a_column_belongs_to_the_sender_beats_the_model(tmp_path):
    """The one mistake worse than leaving a question unanswered. 'To be Filled
    by Bank Albilad' is merged over F:G; a model that has not noticed it must
    not be able to hand us the assessing bank's own column."""
    with Workbook(shapes.ownership_banner(tmp_path / "banner.xlsx")) as workbook:
        sheet = workbook["General Information"]
        part, questions = llm_layout.apply(
            workbook,
            sheet,
            reading(
                header_row=5,
                question_column="B",
                columns=[
                    ColumnReading(column="A", role="number", because="GI.1.1 codes"),
                    ColumnReading(column="D", role="answer", because="ours"),
                    ColumnReading(column="F", role="answer", because="looks writable"),
                ],
            ),
        )
        written = {target.id[-2:-1] for question in questions for target in question.targets.values()}
        assert "F" not in written, "the bank's column was offered as somewhere to write"
        assert "D" in written


def test_everything_a_model_read_is_marked_for_checking(book):
    """It goes to the top of the confirmation panel with its reasoning, because
    a reading arrived at this way is a proposal, not a reading."""
    workbook, sheet = book
    part, _ = llm_layout.apply(workbook, sheet, reading())
    assert part.findings and not any(finding.confident for finding in part.findings)
    assert "read by the model" in part.findings[0].because


def test_an_assisted_sheet_gets_one_verdict_not_two(book):
    workbook, sheet = book
    part, _ = llm_layout.apply(workbook, sheet, reading())
    assert sum(1 for finding in part.findings if finding.subject == sheet.name) == 1
    assert "questions in column B" in part.findings[0].because, "it still says where it read"


# --- when the model is asked at all ----------------------------------------


def test_nothing_is_asked_unless_assistance_is_on(tmp_path, monkeypatch):
    seen: dict = {}
    stub(monkeypatch, reading(), seen=seen)
    forms.detect(shapes.two_row_header(tmp_path / "a.xlsx"), assist=False)
    assert seen == {}, "a call was made with assistance off"


def test_a_sheet_the_rules_lost_is_rescued(tmp_path, monkeypatch):
    stub(monkeypatch, reading())
    form = forms.detect(shapes.two_row_header(tmp_path / "a.xlsx"), assist=True)
    assert len(form.questions) == 5
    assert form.parts[0].kind == "questions"


def test_a_sheet_the_rules_read_is_not_asked_about(tmp_path, monkeypatch):
    """Assistance is a fallback. Paying for a second opinion on the sheets that
    already work would be most of the cost and all of the risk."""
    seen: dict = {}
    stub(monkeypatch, reading(), seen=seen)
    form = forms.detect(shapes.status_and_comment(tmp_path / "hr.xlsx"), assist=True)
    assert len(form.questions) == 4
    assert seen == {}


def test_hidden_and_near_empty_sheets_are_never_asked_about(tmp_path, monkeypatch):
    """A hidden sheet is hidden on purpose and six cells is not a
    questionnaire. Neither is a reading problem, so neither is worth a call --
    `status_and_comment` carries a hidden lookup sheet, which is the case."""
    seen: dict = {}
    stub(monkeypatch, reading(), seen=seen)
    forms.detect(shapes.status_and_comment(tmp_path / "hr.xlsx"), assist=True)
    assert seen == {}


def test_a_model_that_finds_fewer_questions_does_not_win(tmp_path, monkeypatch):
    """The guarantee that makes this safe to turn on: assistance is monotone.
    Here the rules read a thin sheet and the model reads it worse, so the rules
    stand."""
    stub(monkeypatch, reading(question_column="A", header_row=5))
    strict = forms.detect(shapes.headless_numbered(tmp_path / "h.xlsx"))
    assisted = forms.detect(shapes.headless_numbered(tmp_path / "h.xlsx"), assist=True)
    assert len(assisted.questions) >= len(strict.questions)


def test_a_model_failure_leaves_the_rules_verdict_in_place(tmp_path, monkeypatch):
    """The endpoint is down, or the key is wrong. The sheet is skipped, exactly
    as it would have been without assistance -- an upload does not fail because
    a fallback did."""
    stub(monkeypatch, RuntimeError("no route to host"))
    form = forms.detect(shapes.two_row_header(tmp_path / "a.xlsx"), assist=True)
    assert form.questions == []
    assert form.parts[0].kind == "no questions"


def test_assistance_defaults_to_the_setting(tmp_path, monkeypatch):
    stub(monkeypatch, reading())

    from src.config import settings

    monkeypatch.setattr(settings, "detection_assist", True)
    assert len(forms.detect(shapes.two_row_header(tmp_path / "a.xlsx")).questions) == 5

    monkeypatch.setattr(settings, "detection_assist", False)
    assert forms.detect(shapes.two_row_header(tmp_path / "b.xlsx")).questions == []


def test_a_sheet_read_thinly_is_offered_for_a_second_reading(tmp_path, monkeypatch):
    """Seven questions on a sheet of 133 rows is a wrong column, not a short
    questionnaire, and it never reports itself as a failure -- so coverage, not
    just emptiness, has to trigger the fallback."""
    from src.forms import xlsx
    from src.forms.model import Finding, Part

    sheet_rows = list(range(1, 60))
    part = Part(
        name="S",
        kind="questions",
        questions=3,
        findings=[
            Finding(subject="S", verdict="3 questions", because="headings on row 1; questions in column B"),
        ],
    )

    class Fake:
        rows = sheet_rows

    assert xlsx._thin(Fake(), part, 1) is True
    part.questions = 40
    assert xlsx._thin(Fake(), part, 1) is False


def test_a_short_sheet_is_not_called_thin(tmp_path):
    """Four questions out of five rows is a short questionnaire, and asking
    about every small sheet would be a call per cover page."""
    from src.forms import xlsx
    from src.forms.model import Part

    class Fake:
        rows = [1, 2, 3, 4, 5]

    assert xlsx._thin(Fake(), Part(name="S", kind="questions", questions=1), 1) is False


# --- what the model is shown -----------------------------------------------


def test_the_grid_shows_the_sheets_own_row_and_column_labels(tmp_path):
    """So anything said about the sheet can be checked against it in Excel, and
    so a proposal names cells this package can resolve."""
    from src.forms import sheet_view

    with Workbook(shapes.header_below_preamble(tmp_path / "p.xlsx")) as workbook:
        sheet = workbook.sheets[0]
        drawn = sheet_view.grid(sheet)

    assert "row 1 |" in drawn
    assert "A: " in drawn


def test_a_dropdown_column_is_described_even_when_nothing_is_typed_in_it(tmp_path):
    """A blank questionnaire's status column is empty by definition, and it is
    the column the form most wants filled. Describing it only by its contents
    would leave the model nothing to recognise it by."""
    from src.forms import sheet_view

    with Workbook(shapes.status_and_comment(tmp_path / "hr.xlsx")) as workbook:
        described = sheet_view.columns(workbook, workbook["Human Resources"], below=1)

    assert "column C" in described
    assert "dropdown [Fully Compliant" in described


def test_the_grid_is_bounded_however_large_the_sheet(tmp_path):
    """Real questionnaires run to thousands of rows. The window is what makes
    the prompt a fixed cost per sheet rather than a function of the file."""
    from src.forms import sheet_view

    cells = {f"B{row}": f"Question number {row} about access control" for row in range(1, 900)}
    cells["A1"] = "#"
    path = shapes.build(tmp_path / "big.xlsx", [shapes.SheetSpec("Long", cells)])
    with Workbook(path) as workbook:
        drawn = sheet_view.grid(workbook["Long"])

    assert len(drawn.splitlines()) <= sheet_view.GRID_ROWS + 1
    assert "more row(s) below" in drawn


def test_a_long_cell_is_truncated_rather_than_wrapped(tmp_path):
    """Guidance paragraphs in these forms run to hundreds of characters and
    would bury the grid they sit in."""
    from src.forms import sheet_view

    path = shapes.build(
        tmp_path / "wordy.xlsx",
        [
            shapes.SheetSpec(
                "S",
                {
                    "A1": "Question",
                    "A2": "Explain in detail " * 40,
                },
            )
        ],
    )
    with Workbook(path) as workbook:
        drawn = sheet_view.grid(workbook["S"])

    assert max(len(line) for line in drawn.splitlines()) < 200
