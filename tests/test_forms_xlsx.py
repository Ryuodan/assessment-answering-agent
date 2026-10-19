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
    path = shapes.build(
        tmp_path / "dv.xlsx",
        [
            shapes.SheetSpec(
                "Q",
                {
                    "A1": "S.No",
                    "B1": "Question",
                    "G1": "Implementation Status",
                    "A2": "1.0",
                    "B2": "Does your company have a cyber risk management framework?",
                    "A3": "2.0",
                    "B3": "Does your company assess cybersecurity risks regularly?",
                    "A4": "3.0",
                    "B4": "Are all policies signed off at least annually?",
                },
                validations=(("G2:G4", '"Not Applicable,Fully Implemented,Partially Implemented"'),),
            )
        ],
    )
    with Workbook(path) as workbook:
        assert workbook.vocabulary_for(workbook["Q"], "G") == [
            "Not Applicable",
            "Fully Implemented",
            "Partially Implemented",
        ]


def test_a_dropdown_pointing_at_a_hidden_sheet_resolves(tmp_path):
    """One workbook keeps its compliance levels on a hidden sheet and points
    fifteen validations at it."""
    path = shapes.status_and_comment(tmp_path / "isra.xlsx")
    with Workbook(path) as workbook:
        assert workbook.vocabulary_for(workbook["Human Resources"], "C") == [
            "Fully Compliant",
            "Partially Compliant",
            "Non Compliant",
            "Not Applicable",
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
    assert status.vocabulary == ["Fully Compliant", "Partially Compliant", "Non Compliant", "Not Applicable"]
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


# --- a form of one or two questions -------------------------------------------
#
# Three question rows were needed before a column counted as questions, which
# is what keeps a ratings legend out. It also kept out every two-question form,
# so the guarded reading had no floor under them: when the agent recorded
# nothing, the file opened with 0 questions (TD-043). A short form is read when
# its header row says so twice -- a column headed as the questions, and a
# column headed as somewhere to write.


def test_a_two_question_form_under_question_and_answer_headings_is_read(tmp_path):
    form = forms.detect(shapes.short_numbered(tmp_path / "short.xlsx"))
    [part] = form.parts

    assert [q.id for q in form.questions] == ["Security!2", "Security!3"]
    assert [q.targets[Role.ANSWER].id for q in form.questions] == ["Security!C2", "Security!C3"]
    assert part.kind == "questions"
    assert all(finding.confident for finding in part.findings)
    assert part.findings[0].because == "headings on row 1; questions in column B"


def test_a_short_arabic_form_is_read(tmp_path):
    path = shapes.build(
        tmp_path / "short-ar.xlsx",
        [
            shapes.SheetSpec(
                "الأمن",
                {
                    "A1": "رقم",
                    "B1": "السؤال",
                    "C1": "الإجابة",
                    "A2": "1",
                    "B2": "هل يتم تشفير البيانات أثناء التخزين؟",
                    "A3": "2",
                    "B3": "ما مدة الاحتفاظ بالنسخ الاحتياطية؟",
                },
            )
        ],
    )
    form = forms.detect(path)

    assert len(form.questions) == 2
    assert {q.language for q in form.questions} == {"ar"}
    assert [q.targets[Role.ANSWER].id for q in form.questions] == ["الأمن!C2", "الأمن!C3"]


def test_a_short_question_column_without_an_answer_heading_is_still_skipped(tmp_path):
    """A column headed as questions is not enough on its own: with nowhere
    headed for an answer, two rows of it are a list, not a form."""
    path = shapes.build(
        tmp_path / "list.xlsx",
        [
            shapes.SheetSpec(
                "Security",
                {
                    "A1": "#",
                    "B1": "Question",
                    "C1": "Domain",
                    "A2": "1",
                    "B2": "Is data encrypted at rest, and with which algorithm?",
                    "C2": "Cryptography",
                    "A3": "2",
                    "B3": "How long are backups retained?",
                    "C3": "Backup",
                },
            )
        ],
    )
    form = forms.detect(path)

    assert form.questions == []
    assert form.parts[0].kind == "no questions"


def test_a_short_form_without_a_numbering_column_is_still_a_reference_table(tmp_path):
    """Where the short form stops. Two rows of prose with no numbers beside
    them are what a ratings legend looks like, and reading them was left
    undecided (TD-043), so the headings alone do not make them a form."""
    form = forms.detect(shapes.short_unnumbered(tmp_path / "unnumbered.xlsx"))
    [part] = form.parts

    assert form.questions == []
    assert part.kind == "reference table"
    assert "no numbering column" in part.findings[0].because


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
            values[target.id] = target.vocabulary[0] if target.vocabulary else "Yes, and it is reviewed annually."
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


# --- a sheet Excel wrote ------------------------------------------------------
#
# Excel declares half a dozen namespaces on every worksheet and lists four of
# them in `mc:Ignorable`. Re-serialising the part renamed them ns1, ns2... and
# dropped the unused ones, leaving `mc:Ignorable` naming prefixes that no longer
# existed -- and Excel refused to open the filled file. The team's own Zain form
# was one of those.

EXCEL_SHEET = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="x14ac xr xr2 xr3" '
    'xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" '
    'xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" '
    'xmlns:xr2="http://schemas.microsoft.com/office/spreadsheetml/2015/revision2" '
    'xmlns:xr3="http://schemas.microsoft.com/office/spreadsheetml/2016/revision3" '
    'xr:uid="{00000000-0001-0000-0000-000000000000}">'
    '<dimension ref="A1:C5"/><sheetViews><sheetView workbookViewId="0"/></sheetViews>'
    '<sheetFormatPr defaultRowHeight="15" x14ac:dyDescent="0.25"/>'
    "<sheetData>"
    '<row r="1" spans="1:3" x14ac:dyDescent="0.25"><c r="A1" t="inlineStr"><is><t>S.No</t></is></c>'
    '<c r="B1" t="inlineStr"><is><t>Vendor Due Diligence Questions</t></is></c>'
    '<c r="C1" t="inlineStr"><is><t>Vendor Response</t></is></c></row>'
    '<row r="2" spans="1:3" x14ac:dyDescent="0.25"><c r="A2"><v>1</v></c>'
    '<c r="B2" t="inlineStr"><is><t>Does the vendor have documented information security policies?</t></is></c>'
    '<c r="C2" s="4"/></row>'
    '<row r="3" spans="1:3" x14ac:dyDescent="0.25"><c r="A3"><v>2</v></c>'
    '<c r="B3" t="inlineStr"><is><t>Does the vendor review those policies at least annually?</t></is></c></row>'
    '<row r="5" spans="1:3" x14ac:dyDescent="0.25"/>'
    "</sheetData>"
    '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
    '<extLst><ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}" '
    'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">'
    '<x14:dataValidations count="0" xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"/>'
    "</ext></extLst></worksheet>"
)


def _excel_workbook(tmp_path, sheet_xml=EXCEL_SHEET):
    path = shapes.simple(tmp_path / "excel.xlsx")
    rebuilt = tmp_path / "excel-authored.xlsx"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as out:
        for item in source.infolist():
            data = sheet_xml.encode("utf-8") if item.filename == "xl/worksheets/sheet1.xml" else source.read(item)
            out.writestr(item, data)
    return rebuilt


def _sheet_text(path) -> str:
    with zipfile.ZipFile(path) as package:
        return package.read("xl/worksheets/sheet1.xml").decode("utf-8")


def test_an_excel_sheets_namespaces_survive_answering(tmp_path):
    import re as regex

    path = _excel_workbook(tmp_path)
    out = tmp_path / "answered.xlsx"
    forms.write(
        path,
        out,
        {
            "Questionnaire!C2": "Yes, reviewed annually.",
            "Questionnaire!C3": "Yes.",
            "Questionnaire!C4": "A row that was never there.",
            "Questionnaire!C5": "A row that was empty.",
        },
    )

    text = _sheet_text(out)
    root = regex.search(r"<worksheet[^>]*>", text).group(0)
    declared = set(regex.findall(r"xmlns:(\w+)=", root))
    ignorable = regex.search(r'mc:Ignorable="([^"]*)"', root).group(1).split()
    assert set(ignorable) <= declared, "Excel will not open a file whose mc:Ignorable names an undeclared prefix"
    assert root == regex.search(r"<worksheet[^>]*>", EXCEL_SHEET).group(0)

    with Workbook(out) as workbook:
        sheet = workbook["Questionnaire"]
        assert [sheet.value(row, "C") for row in (2, 3, 4, 5)] == [
            "Yes, reviewed annually.",
            "Yes.",
            "A row that was never there.",
            "A row that was empty.",
        ]


def test_only_the_answered_cells_change(tmp_path):
    path = _excel_workbook(tmp_path)
    out = tmp_path / "answered.xlsx"
    forms.write(path, out, {"Questionnaire!C3": "Yes."})

    before, after = EXCEL_SHEET, _sheet_text(out)
    cell = '<c r="C3" t="inlineStr"><is><t xml:space="preserve">Yes.</t></is></c>'
    assert after == before.replace("annually?</t></is></c></row>", "annually?</t></is></c>" + cell + "</row>", 1), (
        "every byte but the answered cell is the file's own"
    )


def test_a_cell_keeps_its_style_when_answered(tmp_path):
    out = tmp_path / "answered.xlsx"
    forms.write(_excel_workbook(tmp_path), out, {"Questionnaire!C2": "Yes."})
    assert '<c r="C2" s="4" t="inlineStr">' in _sheet_text(out)


def test_text_that_xml_cannot_hold_is_made_safe(tmp_path):
    """A model's answer can carry a vertical tab or a form feed, which XML 1.0
    does not allow anywhere -- one of those made the whole part unreadable."""
    out = tmp_path / "answered.xlsx"
    forms.write(_excel_workbook(tmp_path), out, {"Questionnaire!C2": "Yes & <always>\x0b reviewed\x00."})

    with Workbook(out) as workbook:
        assert workbook["Questionnaire"].value(2, "C") == "Yes & <always> reviewed."


def test_a_sheet_written_with_a_namespace_prefix_is_answered_in_it(tmp_path):
    """Some generators write `<x:worksheet xmlns:x=...>` rather than a default namespace."""
    prefixed = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<x:sheetData><x:row r="1"><x:c r="B1" t="inlineStr"><x:is><x:t>Question</x:t></x:is></x:c>'
        '<x:c r="C1" t="inlineStr"><x:is><x:t>Response</x:t></x:is></x:c></x:row></x:sheetData>'
        "</x:worksheet>"
    )
    out = tmp_path / "answered.xlsx"
    forms.write(_excel_workbook(tmp_path, prefixed), out, {"Questionnaire!C2": "Yes."})

    assert '<x:row r="2"><x:c r="C2" t="inlineStr"><x:is><x:t xml:space="preserve">Yes.' in _sheet_text(out)
    with Workbook(out) as workbook:
        assert workbook["Questionnaire"].value(2, "C") == "Yes."


def test_an_empty_sheet_is_given_its_first_row(tmp_path):
    empty = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>'
    )
    out = tmp_path / "answered.xlsx"
    forms.write(_excel_workbook(tmp_path, empty), out, {"Questionnaire!C2": "Yes."})
    with Workbook(out) as workbook:
        assert workbook["Questionnaire"].value(2, "C") == "Yes."


def test_a_shape_the_splice_does_not_know_still_writes(tmp_path):
    """Rows without a reference are legal, and rare; the whole-part rewrite takes those."""
    unnumbered = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row><c r="B1" t="inlineStr"><is><t>Question</t></is></c></row></sheetData></worksheet>'
    )
    out = tmp_path / "answered.xlsx"
    forms.write(_excel_workbook(tmp_path, unnumbered), out, {"Questionnaire!C2": "Yes."})
    with Workbook(out) as workbook:
        assert workbook["Questionnaire"].value(2, "C") == "Yes."


# --- the invariant that matters --------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [
        shapes.simple,
        shapes.header_below_preamble,
        shapes.status_and_comment,
        shapes.ownership_banner,
        shapes.headless_numbered,
        shapes.legend_sheet,
        shapes.short_numbered,
    ],
)
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
    assert [sorted(t.id for t in q.writable) for q in second.questions] == [
        sorted(t.id for t in q.writable) for q in first.questions
    ]


def test_an_answered_form_knows_it_is_answered(simple, tmp_path):
    form = forms.detect(simple)
    assert form.answered_count == 0
    out = tmp_path / "out.xlsx"
    forms.write(simple, out, _answer_everything(form))
    assert forms.detect(out).answered_count == 4


def test_an_evidence_column_left_blank_still_counts_as_answered(tmp_path):
    """Evidence is blank by default, and a question with an answer and no
    attachment is answered, not outstanding."""
    path = shapes.build(
        tmp_path / "ev.xlsx",
        [
            shapes.SheetSpec(
                "Q",
                {
                    "A1": "S.No",
                    "B1": "Question",
                    "C1": "Response",
                    "D1": "Evidence",
                    "A2": "1.0",
                    "B2": "Does the vendor have documented security policies?",
                    "C2": "Yes.",
                    "A3": "2.0",
                    "B3": "Does the vendor review those policies annually?",
                    "C3": "Yes.",
                    "A4": "3.0",
                    "B4": "Are staff bound by non-disclosure agreements?",
                    "C4": "Yes.",
                },
            )
        ],
    )
    form = forms.detect(path)
    assert form.answered_count == 3
    assert Role.EVIDENCE in form.questions[0].targets


def test_a_dropdown_column_with_nothing_in_it_is_still_found(tmp_path):
    """`Sheet.columns` only knows about columns holding a value, and an unused
    dropdown holds none. On a blank questionnaire that is the normal state of
    the status column -- so the one place the form most wants an answer was
    invisible, and only the prose column got written."""
    path = shapes.build(
        tmp_path / "blank-status.xlsx",
        [
            shapes.SheetSpec(
                "Questionnaire",
                {
                    "A1": "#",
                    "E1": "Security Control",
                    "F1": "Evidence Requirement",
                    "H1": "Comments by Third Party",
                    "A2": "1.0",
                    "E2": "Does your company have a cyber risk management framework?",
                    "A3": "2.0",
                    "E3": "Does your company assess cybersecurity risks regularly?",
                    "A4": "3.0",
                    "E4": "Are all information security policies signed off annually?",
                    # column G carries the dropdown and not one value
                },
                validations=(("G2:G4", '"Not Applicable,Fully Implemented,Not Implemented"'),),
            )
        ],
    )

    form = forms.detect(path)
    status = form.questions[0].targets[Role.STATUS]
    assert status.id == "Questionnaire!G2"
    assert status.vocabulary == ["Not Applicable", "Fully Implemented", "Not Implemented"]
    assert form.questions[0].targets[Role.ANSWER].id == "Questionnaire!H2"


def test_validated_columns_are_listed_even_when_empty(tmp_path):
    from src.forms.xlsx_package import Workbook

    path = shapes.build(
        tmp_path / "dv.xlsx",
        [
            shapes.SheetSpec(
                "Q",
                {
                    "A1": "S.No",
                    "B1": "Question",
                    "A2": "1.0",
                    "B2": "Does the vendor have documented information security policies?",
                    "A3": "2.0",
                    "B3": "Does the vendor review those policies at least annually?",
                    "A4": "3.0",
                    "B4": "Are staff bound by non-disclosure agreements?",
                },
                validations=(("D2:E4", '"Yes,No"'),),
            )
        ],
    )
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


# --- what six unseen questionnaires cost, and bought -----------------------
#
# Two shapes arrived later that no rule anticipated, and between them they
# account for every question the rules missed on that set. Both fixes are
# narrow and both are here, because the next unfamiliar file will not be one of
# these two.


def test_a_reference_column_headed_id_is_a_numbering_column(tmp_path):
    """`ID` is the commonest heading for the column holding `GE-01` or `GQ7`,
    and without it there is no numbering column at all."""
    form = forms.detect(shapes.reference_column_headed_id(tmp_path / "id.xlsx"))
    verdicts = {part.name: {f.subject: f.verdict for f in part.findings} for part in form.parts}
    # Per sheet: the two sheets both have a column A, and they are not the same
    # kind of column -- one is the ID, the other the security domain.
    assert verdicts["Vendor Info"]["column A"] == "number"
    assert verdicts["Questionnaire"]["column B"] == "number"
    assert verdicts["Questionnaire"]["column A"] == "context"


def test_short_questions_are_found_once_their_numbers_are(tmp_path):
    """This is what the numbering column buys. Without it a question has to end
    in a question mark or run past fifty characters, and `Organisation name`,
    `Email address` and `Do you maintain an incident register` do neither."""
    form = forms.detect(shapes.reference_column_headed_id(tmp_path / "id.xlsx"))
    found = {question.text for question in form.questions}
    assert "Organisation name" in found
    assert "Email address" in found
    assert "Do you maintain an incident register" in found


def test_a_short_reference_heading_is_matched_whole_and_never_inside_a_word(tmp_path):
    """`id` sits inside `Identity and Access Management` and `no` inside
    `Notes`. Matching these as substrings would put a whole domain column, or
    the comment column, into the numbering role."""
    from src.forms.xlsx import Role, _role_for

    assert _role_for("ID", has_dropdown=False)[0] is Role.NUMBER
    assert _role_for("Ref", has_dropdown=False)[0] is Role.NUMBER
    assert _role_for("Identity and Access Management", has_dropdown=False)[0] is not Role.NUMBER
    assert _role_for("Notes", has_dropdown=False)[0] is not Role.NUMBER


def test_a_headless_sheet_survives_its_own_answers(tmp_path):
    """A header row one typo from being recognised -- `Queations | Answer` --
    so the sheet is read headless. Blank, the questions are the only prose on
    it. Filled, the answer column holds more, and it used to take their place:
    32 questions written, re-opened as 0.
    """
    path = shapes.headless_typo_header(tmp_path / "typo.xlsx")
    before = forms.detect(path)
    assert len(before.questions) == 10

    answered = tmp_path / "answered.xlsx"
    forms.write(
        path,
        answered,
        {
            target.id: "Yes. An approved policy is in place and reviewed annually."
            for question in before.questions
            for target in question.writable
        },
    )
    after = forms.detect(answered)
    assert [q.id for q in after.questions] == [q.id for q in before.questions]
    assert after.questions[0].text == before.questions[0].text


def test_a_column_labelled_as_the_answer_is_never_read_as_the_questions(tmp_path):
    """Excluded rather than penalised: an answer can be arbitrarily longer than
    the question it answers, so any score a penalty produces can be beaten."""
    from src.forms.xlsx import _find_headless_layout
    from src.forms.xlsx_package import Workbook

    cells = {"A1": "Queations", "B1": "Answer"}
    for row in range(2, 12):
        cells[f"A{row}"] = f"A reasonably long question about control number {row}?"
        cells[f"B{row}"] = "A considerably longer answer than the question it is answering, twice over."
    path = shapes.build(tmp_path / "wordy.xlsx", [shapes.SheetSpec("S", cells)])

    with Workbook(path) as workbook:
        layout = _find_headless_layout(workbook["S"])
    assert layout is not None and layout.question_column == "A"


def test_a_sentence_in_the_first_row_is_data_and_not_a_label(tmp_path):
    """The exclusion reads the top row as labels, so it has to know when the top
    row is not labels at all. A cell of `LONG_TEXT` or more is prose."""
    from src.forms.xlsx import _find_headless_layout
    from src.forms.xlsx_package import Workbook

    cells = {}
    for row in range(1, 12):
        cells[f"A{row}"] = f"Does the organisation maintain a documented control for area {row}?"
    path = shapes.build(tmp_path / "prose.xlsx", [shapes.SheetSpec("S", cells)])

    with Workbook(path) as workbook:
        layout = _find_headless_layout(workbook["S"])
    assert layout is not None and layout.question_column == "A", (
        "a question beginning with a recognised word is still a question"
    )


# --- the instruction column -------------------------------------------------
#
# A questionnaire's author fills one column in before sending it: "List accounts
# if applicable", "Provide screenshot or policy doc". It is the only column
# guaranteed to be complete on every row, which is exactly what made it look
# like the answer column to a rule that counted cells -- and promoting it made
# every question read as already answered, so the overwrite guard then protected
# the author's instructions from being replaced by our answer.


def test_the_instruction_column_is_not_promoted_to_the_answer(tmp_path):
    """The shape of `Vendors annual Review 1.xlsx`: a verdict dropdown, a column
    of instructions, and the real prose one column further right under a heading
    that reads as context."""
    path = shapes.build(
        tmp_path / "instructions.xlsx",
        [
            shapes.SheetSpec(
                "Review",
                {
                    "A1": "#",
                    "B1": "Question",
                    "C1": "Response",
                    "D1": "Details / Evidence",
                    "E1": "Document Reference",
                    "A2": "1",
                    "B2": "Are user accounts reviewed periodically?",
                    "C2": "Yes",
                    "D2": "List accounts if applicable",
                    "E2": "T2 reviews user accounts quarterly and records the outcome.",
                    "A3": "2",
                    "B3": "Is MFA enforced?",
                    "C3": "Yes",
                    "D3": "Provide screenshot or policy doc",
                    "E3": "T2 enforces multi-factor authentication on all remote access.",
                    "A4": "3",
                    "B4": "Are privileged accounts separated?",
                    "C4": "Yes",
                    "D4": "Provide offboarding evidence",
                    "E4": "Administrative accounts are separate from day-to-day accounts.",
                },
                validations=(("C2:C4", '"Yes,No,N/A"'),),
            )
        ],
    )

    form = forms.detect(path)
    answers = [q.existing_answer for q in form.questions]
    assert all("T2" in a or "Administrative" in a for a in answers), answers
    assert not any("Provide screenshot" in a or "List accounts" in a for a in answers), (
        "the author's instructions were read as our answers"
    )


def test_an_evidence_column_is_still_promoted_when_it_holds_the_answers(tmp_path):
    """The promotion exists for a reason and must survive: plenty of forms word
    their only free-text column as a request for evidence and then answer in
    it."""
    path = shapes.build(
        tmp_path / "evidence.xlsx",
        [
            shapes.SheetSpec(
                "Q",
                {
                    "A1": "#",
                    "B1": "Question",
                    "C1": "Compliance",
                    "D1": "Evidence",
                    "A2": "1",
                    "B2": "Do you encrypt backups?",
                    "C2": "Yes",
                    "D2": "Backups are encrypted with AES-256 at rest and in transit.",
                    "A3": "2",
                    "B3": "Are logs retained?",
                    "C3": "Yes",
                    "D3": "Security event logs are retained for twelve months.",
                    "A4": "3",
                    "B4": "Is access reviewed?",
                    "C4": "Yes",
                    "D4": "Access rights are reviewed every quarter by the owner.",
                },
                validations=(("C2:C4", '"Yes,No"'),),
            )
        ],
    )

    form = forms.detect(path)
    assert all(
        "encrypt" in q.existing_answer or "retained" in q.existing_answer or "reviewed" in q.existing_answer
        for q in form.questions
    )


def test_the_promotion_says_when_the_column_it_chose_looks_instructional(tmp_path):
    """Where there is no better candidate the column is still used -- an answer
    the person can correct beats no answer -- but the finding says why it is
    worth a look."""
    path = shapes.build(
        tmp_path / "only.xlsx",
        [
            shapes.SheetSpec(
                "Q",
                {
                    "A1": "#",
                    "B1": "Question",
                    "C1": "Compliance",
                    "D1": "Evidence",
                    "A2": "1",
                    "B2": "Do you encrypt backups?",
                    "C2": "Yes",
                    "D2": "Provide the policy",
                    "A3": "2",
                    "B3": "Are logs retained?",
                    "C3": "Yes",
                    "D3": "Provide the retention schedule",
                    "A4": "3",
                    "B4": "Is access reviewed?",
                    "C4": "Yes",
                    "D4": "Provide the review record",
                },
                validations=(("C2:C4", '"Yes,No"'),),
            )
        ],
    )

    form = forms.detect(path)
    said = " ".join(f.because for part in form.parts for f in part.findings)
    assert "instructions" in said, said[:300]
