"""Reading questionnaire workbooks, and writing answers back into them.

Each fixture reproduces a layout from the real customer forms, which cannot be
committed. The names say which problem each one caused, so a failure points at
a shape rather than at a line number.

Measured against the eleven real workbooks, this finds 831 questions where
counting the printed item numbers by hand finds 824 -- everything, plus seven
extras a person unticks. Erring that way is deliberate: the confirmation step
can remove a row it was offered and cannot recover one it never saw.
"""

from __future__ import annotations

import zipfile

import pytest

from src import forms
from src.forms.model import Role
from src.forms.xlsx_package import Workbook, column_letters, column_number
from tests import forms_fixtures as shapes


@pytest.fixture
def simple(tmp_path):
    return shapes.simple(tmp_path / "simple.xlsx")


# --- the package reader ----------------------------------------------------


def test_column_letters_and_numbers_round_trip():
    for number in (1, 26, 27, 52, 53, 703):
        assert column_number(column_letters(number)) == number


def test_a_sheet_reads_back_its_cells(simple):
    with Workbook(simple) as workbook:
        sheet = workbook["Questionnaire"]
        assert sheet.value(1, "A") == "S.No"
        assert sheet.value(2, "B").startswith("Does the vendor have documented")
        assert sheet.rows == [1, 2, 3, 4, 5]
        assert sheet.columns == ["A", "B", "C"]


def test_an_inline_dropdown_resolves_to_its_words(tmp_path):
    path = shapes.build(tmp_path / "dv.xlsx", [shapes.SheetSpec("Q", {
        "A1": "S.No", "B1": "Question", "G1": "Implementation Status",
        "A2": "1.0", "B2": "Does your company have a cyber risk management framework?",
        "A3": "2.0", "B3": "Does your company assess cybersecurity risks regularly?",
        "A4": "3.0", "B4": "Are all policies signed off at least annually?",
    }, validations=(("G2:G4", '"Not Applicable,Fully Implemented,Partially Implemented"'),))])
    with Workbook(path) as workbook:
        assert workbook.vocabulary_for(workbook["Q"], "G") == [
            "Not Applicable", "Fully Implemented", "Partially Implemented"
        ]


def test_a_dropdown_pointing_at_a_hidden_sheet_resolves(tmp_path):
    """One workbook keeps its compliance levels on a hidden sheet and points
    fifteen validations at it."""
    path = shapes.status_and_comment(tmp_path / "isra.xlsx")
    with Workbook(path) as workbook:
        assert workbook.vocabulary_for(workbook["Human Resources"], "C") == [
            "Fully Compliant", "Partially Compliant", "Non Compliant", "Not Applicable"
        ]


def test_merged_cells_report_the_value_they_display(tmp_path):
    path = shapes.ownership_banner(tmp_path / "banner.xlsx")
    with Workbook(path) as workbook:
        sheet = workbook["General Information"]
        covered = workbook.merged_ranges(sheet)
        assert covered[(4, "E")] == (4, "D")
        assert covered[(4, "G")] == (4, "F")


def test_formula_cells_are_recognised(tmp_path):
    path = shapes.status_and_comment(tmp_path / "isra.xlsx")
    with Workbook(path) as workbook:
        assert (7, "C") in workbook["Score"].formulas


# --- detection -------------------------------------------------------------


def test_a_simple_questionnaire_is_read(simple):
    form = forms.detect(simple)
    assert [question.number for question in form.questions] == ["1.0", "2.0", "3.0", "4.0"]
    assert form.questions[0].targets[Role.ANSWER].id == "Questionnaire!C2"


def test_a_header_below_preamble_is_found(tmp_path):
    """A title, a vendor name and a date sit above the real headings."""
    form = forms.detect(shapes.header_below_preamble(tmp_path / "preamble.xlsx"))
    assert len(form.questions) == 4
    assert form.questions[0].targets[Role.ANSWER].id == "RA Questionarie!C9"


def test_a_column_addressed_to_the_other_party_is_never_written(tmp_path):
    """'Compliance (To be updated by BAB)'. Answering there would be worse than
    leaving the question blank."""
    form = forms.detect(shapes.header_below_preamble(tmp_path / "preamble.xlsx"))
    for question in form.questions:
        assert Role.THEIRS not in {target.role for target in question.writable}
        assert not any(target.id.startswith("RA Questionarie!D") for target in question.writable)


def test_arabic_questions_are_marked_arabic(tmp_path):
    form = forms.detect(shapes.header_below_preamble(tmp_path / "preamble.xlsx"))
    languages = {question.number: question.language for question in form.questions}
    assert languages["4.0"] == "ar"
    assert languages["1.0"] == "en"


def test_a_status_column_carries_the_files_own_vocabulary(tmp_path):
    form = forms.detect(shapes.status_and_comment(tmp_path / "isra.xlsx"))
    status = form.questions[0].targets[Role.STATUS]
    assert status.vocabulary == [
        "Fully Compliant", "Partially Compliant", "Non Compliant", "Not Applicable"
    ]
    assert form.questions[0].targets[Role.ANSWER].id.endswith("!D2")


def test_a_question_column_is_found_without_a_matching_heading(tmp_path):
    """Fifteen sheets head their questions 'HR Security', 'Physical Security'
    and so on. No word list anticipates those; the shape of the column does."""
    form = forms.detect(shapes.status_and_comment(tmp_path / "isra.xlsx"))
    assert len(form.questions) == 4


def test_a_banner_above_the_headings_assigns_ownership(tmp_path):
    """'To be Filled by Bank Albilad' merged across F:G. Read the headings alone
    and column F is a compliance dropdown like any other."""
    form = forms.detect(shapes.ownership_banner(tmp_path / "banner.xlsx"))
    written = {target.id.split("!")[1][0] for q in form.questions for target in q.writable}
    assert "F" not in written and "G" not in written
    assert "D" in written, "the vendor's own answer column must still be writable"


def test_the_primary_answer_column_wins_over_a_supplementary_one(tmp_path):
    """'Answer' in D and 'Additional Information to Support the Answer' in E."""
    form = forms.detect(shapes.ownership_banner(tmp_path / "banner.xlsx"))
    assert form.questions[0].targets[Role.ANSWER].id == "General Information!D6"


def test_short_questions_with_item_numbers_are_kept(tmp_path):
    """'Industry' is eight characters and a real question."""
    form = forms.detect(shapes.ownership_banner(tmp_path / "banner.xlsx"))
    assert "Industry" in [question.text for question in form.questions]


def test_a_headless_sheet_is_read_from_its_numbering(tmp_path):
    form = forms.detect(shapes.headless_numbered(tmp_path / "headless.xlsx"))
    numbers = [question.number for question in form.questions]
    assert "A.1" in numbers and "A.2" in numbers
    assert "Part 2:" not in [question.text for question in form.questions]


def test_a_headless_reading_is_offered_for_confirmation(tmp_path):
    """Inferred from shape alone, so every finding says it is a proposal."""
    form = forms.detect(shapes.headless_numbered(tmp_path / "headless.xlsx"))
    findings = [f for part in form.parts if part.used for f in part.findings]
    assert any(not finding.confident for finding in findings)


def test_a_question_mentioning_evidence_is_not_taken_for_a_heading(tmp_path):
    """'If "Yes", please provide the information below, and attach a copy...'
    scored as an evidence heading, and everything above it was discarded."""
    form = forms.detect(shapes.headless_numbered(tmp_path / "headless.xlsx"))
    assert len(form.questions) >= 5, "the rows above the 'attach' row must survive"


def test_a_ratings_legend_is_not_a_questionnaire(tmp_path):
    form = forms.detect(shapes.legend_sheet(tmp_path / "legend.xlsx"))
    used = [part.name for part in form.parts if part.used]
    assert used == ["Questions"]
    assert [part.kind for part in form.parts if part.name == "Compliance Levels"] == ["reference table"]


def test_a_hidden_sheet_is_skipped(tmp_path):
    form = forms.detect(shapes.status_and_comment(tmp_path / "isra.xlsx"))
    assert [part.kind for part in form.parts if part.name == "Score"] == ["hidden"]


def test_every_decision_carries_its_reason(tmp_path):
    form = forms.detect(shapes.header_below_preamble(tmp_path / "preamble.xlsx"))
    findings = [f for part in form.parts for f in part.findings]
    assert findings and all(finding.because for finding in findings)
    theirs = [f for f in findings if f.verdict == "theirs"]
    assert theirs and "BAB" in theirs[0].because


def test_an_unreadable_file_says_so(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not a questionnaire")
    with pytest.raises(forms.UnsupportedForm, match="not a form"):
        forms.detect(path)


# --- writing ---------------------------------------------------------------


def _answer_everything(form) -> dict[str, str]:
    values = {}
    for question in form.questions:
        for target in question.writable:
            if target.role is Role.EVIDENCE:
                continue
            values[target.id] = (
                target.vocabulary[0] if target.vocabulary else "Yes, and it is reviewed annually."
            )
    return values


def test_answers_land_where_detection_said_they_would(simple, tmp_path):
    form = forms.detect(simple)
    out = tmp_path / "answered.xlsx"
    forms.write(simple, out, _answer_everything(form))

    with Workbook(out) as workbook:
        assert workbook["Questionnaire"].value(2, "C") == "Yes, and it is reviewed annually."


def test_writing_creates_cells_that_were_never_there(simple, tmp_path):
    """The ordinary case: in a blank template the answer cell is absent from the
    XML entirely, not present and empty."""
    form = forms.detect(simple)
    report = forms.write(simple, tmp_path / "out.xlsx", _answer_everything(form))
    assert len(report.created) == 4 and not report.replaced


def test_writing_over_an_answer_is_reported_as_a_replacement(simple, tmp_path):
    form = forms.detect(simple)
    once = tmp_path / "once.xlsx"
    forms.write(simple, once, _answer_everything(form))

    report = forms.write(once, tmp_path / "twice.xlsx", _answer_everything(forms.detect(once)))
    assert len(report.replaced) == 4 and not report.created


def test_every_package_part_survives(tmp_path):
    """The guarantee that decided against a spreadsheet library: a load-and-save
    through openpyxl dropped sixteen drawings from one real workbook and every
    cell comment from another."""
    path = shapes.with_extra_parts(tmp_path / "rich.xlsx")
    form = forms.detect(path)
    out = tmp_path / "rich-out.xlsx"
    report = forms.write(path, out, _answer_everything(form))

    assert report.intact
    with zipfile.ZipFile(path) as before, zipfile.ZipFile(out) as after:
        assert set(before.namelist()) == set(after.namelist())
        for name in before.namelist():
            if name.startswith("xl/worksheets/"):
                continue
            assert before.read(name) == after.read(name), f"{name} was rewritten"


def test_a_formula_cell_is_refused(tmp_path):
    """One workbook scores itself from 93 formulas on a hidden sheet. A value
    dropped into one would look filled in and be wrong."""
    path = shapes.status_and_comment(tmp_path / "isra.xlsx")
    report = forms.write(path, tmp_path / "out.xlsx", {"Score!C7": "overwritten"})
    assert report.written == 0
    assert report.skipped == {"Score!C7": "That cell holds a formula."}


def test_writing_to_a_sheet_that_is_not_there_is_reported(simple, tmp_path):
    report = forms.write(simple, tmp_path / "out.xlsx", {"No Such Sheet!C2": "x"})
    assert "No sheet" in report.skipped["No Such Sheet!C2"]


def test_a_malformed_target_is_reported_rather_than_guessed(simple, tmp_path):
    report = forms.write(simple, tmp_path / "out.xlsx", {"Questionnaire!banana": "x", "nope": "y"})
    assert set(report.skipped) == {"Questionnaire!banana", "nope"}
    assert report.written == 0


def test_arabic_answers_round_trip(simple, tmp_path):
    out = tmp_path / "arabic.xlsx"
    forms.write(simple, out, {"Questionnaire!C2": "نعم، لدينا سياسة معتمدة ومراجعة سنوياً."})
    with Workbook(out) as workbook:
        assert workbook["Questionnaire"].value(2, "C") == "نعم، لدينا سياسة معتمدة ومراجعة سنوياً."


def test_written_text_is_marked_space_preserving(simple, tmp_path):
    """Checked in the XML, not through the reader, which trims for detection.

    Excel discards leading and trailing whitespace unless the run says
    otherwise, so an answer indented for readability would come back reflowed.
    """
    out = tmp_path / "spaces.xlsx"
    forms.write(simple, out, {"Questionnaire!C2": "  padded  "})
    with zipfile.ZipFile(out) as package:
        sheet = package.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert 'xml:space="preserve"' in sheet
    assert "  padded  " in sheet


# --- the invariant that matters --------------------------------------------


@pytest.mark.parametrize("shape", [
    shapes.simple,
    shapes.header_below_preamble,
    shapes.status_and_comment,
    shapes.ownership_banner,
    shapes.headless_numbered,
    shapes.legend_sheet,
])
def test_detection_is_unchanged_by_answering(shape, tmp_path):
    """Detect, answer, detect again: the same questions and the same targets.

    This is not decoration. Filling the answer column made it the column with
    the most prose -- many real questions are as short as 'Company Name:' -- so
    re-opening a half-finished workbook moved the questions into the answer
    column and every target with them. A half-finished file is an ordinary
    upload, so the reading has to survive its own output.
    """
    path = shape(tmp_path / "before.xlsx")
    first = forms.detect(path)
    out = tmp_path / "after.xlsx"
    forms.write(path, out, _answer_everything(first))
    second = forms.detect(out)

    assert [q.id for q in second.questions] == [q.id for q in first.questions]
    assert [sorted(t.id for t in q.writable) for q in second.questions] == \
           [sorted(t.id for t in q.writable) for q in first.questions]


def test_an_answered_form_knows_it_is_answered(simple, tmp_path):
    form = forms.detect(simple)
    assert form.answered_count == 0
    out = tmp_path / "out.xlsx"
    forms.write(simple, out, _answer_everything(form))
    assert forms.detect(out).answered_count == 4


def test_an_evidence_column_left_blank_still_counts_as_answered(tmp_path):
    """Evidence is blank by default, and a question with an answer and no
    attachment is answered, not outstanding."""
    path = shapes.build(tmp_path / "ev.xlsx", [shapes.SheetSpec("Q", {
        "A1": "S.No", "B1": "Question", "C1": "Response", "D1": "Evidence",
        "A2": "1.0", "B2": "Does the vendor have documented security policies?", "C2": "Yes.",
        "A3": "2.0", "B3": "Does the vendor review those policies annually?", "C3": "Yes.",
        "A4": "3.0", "B4": "Are staff bound by non-disclosure agreements?", "C4": "Yes.",
    })])
    form = forms.detect(path)
    assert form.answered_count == 3
    assert Role.EVIDENCE in form.questions[0].targets


def test_a_dropdown_column_with_nothing_in_it_is_still_found(tmp_path):
    """`Sheet.columns` only knows about columns holding a value, and an unused
    dropdown holds none. On a blank questionnaire that is the normal state of
    the status column -- so the one place the form most wants an answer was
    invisible, and only the prose column got written."""
    path = shapes.build(tmp_path / "blank-status.xlsx", [shapes.SheetSpec("Questionnaire", {
        "A1": "#", "E1": "Security Control", "F1": "Evidence Requirement",
        "H1": "Comments by Third Party",
        "A2": "1.0", "E2": "Does your company have a cyber risk management framework?",
        "A3": "2.0", "E3": "Does your company assess cybersecurity risks regularly?",
        "A4": "3.0", "E4": "Are all information security policies signed off annually?",
        # column G carries the dropdown and not one value
    }, validations=(("G2:G4", '"Not Applicable,Fully Implemented,Not Implemented"'),))])

    form = forms.detect(path)
    status = form.questions[0].targets[Role.STATUS]
    assert status.id == "Questionnaire!G2"
    assert status.vocabulary == ["Not Applicable", "Fully Implemented", "Not Implemented"]
    assert form.questions[0].targets[Role.ANSWER].id == "Questionnaire!H2"


def test_validated_columns_are_listed_even_when_empty(tmp_path):
    from src.forms.xlsx_package import Workbook

    path = shapes.build(tmp_path / "dv.xlsx", [shapes.SheetSpec("Q", {
        "A1": "S.No", "B1": "Question",
        "A2": "1.0", "B2": "Does the vendor have documented information security policies?",
        "A3": "2.0", "B3": "Does the vendor review those policies at least annually?",
        "A4": "3.0", "B4": "Are staff bound by non-disclosure agreements?",
    }, validations=(("D2:E4", '"Yes,No"'),))])
    with Workbook(path) as workbook:
        assert workbook.validated_columns(workbook["Q"]) == {"D", "E"}


def test_a_column_reason_names_its_heading_once(tmp_path):
    """The reason is read by somebody checking a column was taken for the right
    thing. "'HR Security': 'HR Security': the column holding..." reads like a
    bug in the tool doing the checking."""
    form = forms.detect(shapes.status_and_comment(tmp_path / "hr.xlsx"))
    findings = [finding for part in form.parts for finding in part.findings]
    assert findings, "the fixture should report on its columns"
    for finding in findings:
        if not finding.subject.startswith("column "):
            continue
        heading, _, rest = finding.because.partition(": ")
        if heading.startswith("'"):
            assert heading not in rest, f"heading repeated in: {finding.because}"
