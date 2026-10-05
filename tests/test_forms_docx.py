"""Reading Word questionnaires, and writing answers back into them.

Two shapes, and the prose one -- the one that looked hardest -- turned out
easier. On the real document 139 of 139 questions match on a bold `Q<n>` lead,
and its blank copy contains no answer paragraphs at all, so writing there is
insertion rather than filling. The table one is harder: a single logical table
arrives split across page breaks into twenty-two fragments, most with no header.

Fixtures are built here rather than committed, for the same reason as the
spreadsheets: the originals are other companies' confidential forms.
"""

from __future__ import annotations

import zipfile

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from src import forms
from src.forms.model import Role

ARABIC = "نعم، توجد سياسة استخدام مقبول موثقة ومعتمدة."


# --- fixtures ---------------------------------------------------------------


def _question(document, text: str) -> None:
    """A question the way the real document writes one: bold lead, then the rest."""
    paragraph = document.add_paragraph()
    lead = paragraph.add_run(text.split(":", 1)[0] + " : ")
    lead.bold = True
    lead.font.size = Pt(10)
    rest = paragraph.add_run(text.split(":", 1)[1].strip())
    rest.font.size = Pt(10)


def prose_form(path, *, answered: bool = False):
    """Sections, `Q<n>` questions, `Evidence Required` lines, optional answers."""
    document = Document()
    for section, questions in (
        (
            "Cybersecurity Governance :",
            [
                "Q1: Has your organization established and approved a Cybersecurity strategy?",
                "Q2: Has your organization defined Cybersecurity roles and responsibilities?",
                "Q3: Are Cybersecurity policies reviewed periodically?",
            ],
        ),
        (
            "Cybersecurity Compliance:",
            [
                "Q1: Has your organization defined Cybersecurity audit requirements?",
                "Q2: Has your organization undergone independent external audits?",
            ],
        ),
    ):
        heading = document.add_paragraph()
        run = heading.add_run(section)
        run.bold = True
        for text in questions:
            _question(document, text)
            if "roles" in text or "audit requirements" in text:
                document.add_paragraph("Evidence Required: – Organizational Chart.")
            if answered:
                answer = document.add_paragraph()
                label = answer.add_run("Answer :  ")
                label.bold = True
                answer.add_run("Yes, this is documented and approved.")
    document.save(str(path))
    return path


def table_form(path, *, fragments: bool = False, answered: bool = False):
    """`No. | Question | Answer`, optionally split into headerless continuations."""
    document = Document()
    document.add_paragraph("1. Company Information")

    def add(rows, header: bool):
        table = document.add_table(rows=0, cols=3)
        if header:
            cells = table.add_row().cells
            cells[0].text, cells[1].text, cells[2].text = "No.", "Question", "Answer"
        for number, question in rows:
            cells = table.add_row().cells
            cells[0].text = number
            cells[1].text = question
            cells[2].text = "Yes, we comply." if answered else ""
        return table

    first = [("1.", "Full legal name of company"), ("2.", "Company's address")]
    second = [("3.", "Contact email address"), ("4.", "Do you comply with the PDPL?")]
    add(first, header=True)
    add(second, header=not fragments)
    document.save(str(path))
    return path


@pytest.fixture
def prose(tmp_path):
    return prose_form(tmp_path / "prose.docx")


@pytest.fixture
def tables(tmp_path):
    return table_form(tmp_path / "tables.docx")


# --- prose ------------------------------------------------------------------


def test_prose_questions_are_found(prose):
    form = forms.detect(prose)
    assert [question.number for question in form.questions] == ["Q1", "Q2", "Q3", "Q1", "Q2"]
    assert form.format == "docx"


def test_numbering_restarts_are_kept_apart_by_section(prose):
    """Every section starts again at Q1, so the number alone is not an identity."""
    form = forms.detect(prose)
    assert len({question.id for question in form.questions}) == 5
    assert form.questions[0].section == "Cybersecurity Governance"
    assert form.questions[3].section == "Cybersecurity Compliance"


def test_a_blank_prose_form_has_no_answers_to_find(prose):
    """The blank copy of the real document contains zero answer paragraphs, so
    the answer is created rather than filled."""
    form = forms.detect(prose)
    assert form.answered_count == 0


def test_an_answered_prose_form_reads_its_answers_back(tmp_path):
    form = forms.detect(prose_form(tmp_path / "answered.docx", answered=True))
    assert form.answered_count == 5
    assert form.questions[0].targets[Role.ANSWER].existing == "Yes, this is documented and approved."


def test_an_answer_is_inserted_after_the_evidence_line(prose, tmp_path):
    """The answer belongs after the whole question block, not immediately after
    the question -- 'Evidence Required' sits between them."""
    form = forms.detect(prose)
    question = next(q for q in form.questions if "roles" in q.text)
    out = tmp_path / "out.docx"
    forms.write(prose, out, {question.targets[Role.ANSWER].id: "Yes, documented and approved."})

    texts = [p.text.strip() for p in Document(str(out)).paragraphs if p.text.strip()]
    evidence = next(i for i, t in enumerate(texts) if t.startswith("Evidence Required"))
    assert texts[evidence + 1].startswith("Answer :")


def test_an_inserted_answer_imitates_the_house_format(prose, tmp_path):
    """A bold label and then the answer, in the question's own style -- built
    from the question, because a blank form has no answer to copy."""
    form = forms.detect(prose)
    out = tmp_path / "out.docx"
    forms.write(prose, out, {form.questions[0].targets[Role.ANSWER].id: "Yes, the strategy is approved."})

    answer = next(p for p in Document(str(out)).paragraphs if p.text.startswith("Answer :"))
    assert answer.runs[0].bold is True
    assert answer.runs[1].bold in (False, None)
    assert answer.runs[1].text == "Yes, the strategy is approved."


def test_answering_every_question_puts_each_one_in_its_own_place(prose, tmp_path):
    """Inserting shifts every later paragraph, so anchors are resolved first and
    applied from the end backwards."""
    form = forms.detect(prose)
    out = tmp_path / "out.docx"
    forms.write(
        prose,
        out,
        {
            question.targets[Role.ANSWER].id: f"Answer to {question.section} {question.number}."
            for question in form.questions
        },
    )

    texts = [p.text.strip() for p in Document(str(out)).paragraphs if p.text.strip()]
    for index, text in enumerate(texts):
        if text.startswith("Answer :"):
            # the nearest question above this answer is the one it belongs to
            question = next(t for t in reversed(texts[:index]) if t.startswith("Q"))
            number = question.split(":")[0].strip()
            assert number in text, f"{text!r} landed under {question!r}"


def test_an_existing_answer_is_rewritten_rather_than_duplicated(tmp_path):
    path = prose_form(tmp_path / "answered.docx", answered=True)
    form = forms.detect(path)
    out = tmp_path / "out.docx"
    report = forms.write(path, out, {form.questions[0].targets[Role.ANSWER].id: "A corrected answer."})

    assert report.replaced and not report.created
    texts = [p.text.strip() for p in Document(str(out)).paragraphs if p.text.startswith("Answer :")]
    assert texts.count("Answer :  A corrected answer.") == 1
    assert len(texts) == 5, "rewriting must not add a paragraph"


def test_an_arabic_answer_is_marked_right_to_left(prose, tmp_path):
    """Word lays Arabic out left-aligned with the punctuation in the wrong place
    unless the paragraph and its runs say they are right-to-left."""
    form = forms.detect(prose)
    out = tmp_path / "out.docx"
    forms.write(prose, out, {form.questions[0].targets[Role.ANSWER].id: ARABIC})

    answer = next(p for p in Document(str(out)).paragraphs if p.text.startswith("Answer :"))
    assert answer._p.find(qn("w:pPr")).find(qn("w:bidi")) is not None
    assert ARABIC in answer.text


@pytest.mark.parametrize("shape", ["prose", "tables"])
def test_filling_an_arabic_answer_twice_marks_it_right_to_left_once(shape, prose, tables, tmp_path):
    """Re-uploading a filled document and filling it again appended a second
    w:bidi to every answer paragraph. Word forgives it; the schema allows one."""
    path = prose if shape == "prose" else tables
    once, twice = tmp_path / "once.docx", tmp_path / "twice.docx"
    forms.write(path, once, {forms.detect(path).questions[0].targets[Role.ANSWER].id: ARABIC})
    forms.write(once, twice, {forms.detect(once).questions[0].targets[Role.ANSWER].id: ARABIC})

    body = Document(str(twice)).element.body
    for properties in body.iter(qn("w:pPr")):
        assert len(properties.findall(qn("w:bidi"))) <= 1
    for properties in body.iter(qn("w:rPr")):
        assert len(properties.findall(qn("w:rtl"))) <= 1


def test_question_ids_survive_being_answered(prose, tmp_path):
    """A positional id would move for every question the moment the first one
    was answered, because inserting shifts the paragraphs after it."""
    form = forms.detect(prose)
    out = tmp_path / "out.docx"
    forms.write(prose, out, {question.targets[Role.ANSWER].id: "Yes." for question in form.questions})
    assert [q.id for q in forms.detect(out).questions] == [q.id for q in form.questions]


# --- tables -----------------------------------------------------------------


def test_table_questions_are_found(tables):
    form = forms.detect(tables)
    assert [question.number for question in form.questions] == ["1.", "2.", "3.", "4."]
    assert form.questions[0].text == "Full legal name of company"


def test_a_headerless_continuation_is_stitched_to_the_table_before_it(tmp_path):
    """One real form splits a single logical table into twenty-two fragments,
    most of which begin mid-numbering with no header of their own."""
    path = table_form(tmp_path / "split.docx", fragments=True)
    form = forms.detect(path)
    assert [question.number for question in form.questions] == ["1.", "2.", "3.", "4."]


def test_a_table_answer_is_written_into_its_cell(tables, tmp_path):
    form = forms.detect(tables)
    out = tmp_path / "out.docx"
    forms.write(tables, out, {form.questions[0].targets[Role.ANSWER].id: "T2 Business Research."})

    assert Document(str(out)).tables[0].rows[1].cells[2].text == "T2 Business Research."


@pytest.mark.parametrize("shape", ["prose", "tables"])
def test_a_character_xml_cannot_hold_does_not_cost_the_whole_file(shape, prose, tables, tmp_path):
    """A model's answer can carry a vertical tab or a form feed. python-docx
    refuses those outright, and one of them used to fail the entire fill -- every
    answer in the document, for one invisible character in one of them."""
    path = prose if shape == "prose" else tables
    form = forms.detect(path)
    target = form.questions[0].targets[Role.ANSWER].id
    out = tmp_path / "out.docx"

    report = forms.write(path, out, {target: "Yes,\x0b documented\x0c and\x00 approved."})

    assert report.written == 1
    assert "Yes, documented and approved." in "\n".join(
        [p.text for p in Document(str(out)).paragraphs]
        + [cell.text for table in Document(str(out)).tables for row in table.rows for cell in row.cells]
    )


def test_a_table_cell_is_a_rewrite_not_an_insertion(tmp_path):
    """The third shape 'blank' takes: the cell exists and holds an empty string."""
    path = table_form(tmp_path / "t.docx")
    form = forms.detect(path)
    report = forms.write(path, tmp_path / "out.docx", {form.questions[0].targets[Role.ANSWER].id: "Yes."})
    assert report.created and not report.replaced


def test_an_answered_table_cell_reports_a_replacement(tmp_path):
    path = table_form(tmp_path / "t.docx", answered=True)
    form = forms.detect(path)
    report = forms.write(
        path, tmp_path / "out.docx", {form.questions[0].targets[Role.ANSWER].id: "A corrected answer."}
    )
    assert report.replaced and not report.created


def test_writing_a_table_cell_does_not_leave_the_old_text_behind(tmp_path):
    path = table_form(tmp_path / "t.docx", answered=True)
    form = forms.detect(path)
    out = tmp_path / "out.docx"
    forms.write(path, out, {form.questions[0].targets[Role.ANSWER].id: "Replaced."})
    assert Document(str(out)).tables[0].rows[1].cells[2].text == "Replaced."


# --- both -------------------------------------------------------------------


def test_a_document_with_neither_shape_says_so(tmp_path):
    document = Document()
    document.add_paragraph("This is a covering letter, not a questionnaire.")
    path = tmp_path / "letter.docx"
    document.save(str(path))

    form = forms.detect(path)
    assert not form.questions
    assert form.warnings and "No questions were found" in form.warnings[0]


def test_every_package_part_survives(prose, tmp_path):
    form = forms.detect(prose)
    out = tmp_path / "out.docx"
    report = forms.write(prose, out, {question.targets[Role.ANSWER].id: "Yes." for question in form.questions})
    assert report.intact
    with zipfile.ZipFile(prose) as before, zipfile.ZipFile(out) as after:
        assert set(before.namelist()) == set(after.namelist())


def test_an_unknown_target_is_reported_rather_than_guessed(prose, tmp_path):
    report = forms.write(
        prose,
        tmp_path / "out.docx",
        {
            "para:9999": "x",
            "table:0/r0/c9": "y",
            "nonsense": "z",
        },
    )
    assert set(report.skipped) == {"para:9999", "table:0/r0/c9", "nonsense"}
    assert report.written == 0


def test_a_table_row_is_named_by_the_heading_above_its_table(tmp_path):
    """ "table 2, row 5" is a coordinate nothing in Word will show you. Table
    questionnaires mostly have no numbering column and no banner row, so the
    line above the table is the only thing that names the section."""
    path = tmp_path / "sections.docx"
    document = Document()
    document.add_paragraph("3. Technical Measures")
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "Question"
    table.cell(0, 1).text = "Answer"
    table.cell(1, 0).text = "Is data encrypted at rest?"
    table.cell(2, 0).text = "Are backups tested?"
    document.save(path)

    form = forms.detect(path)
    assert [q.location for q in form.questions] == [
        "3. Technical Measures, row 2",
        "3. Technical Measures, row 3",
    ]


def test_a_paragraph_of_guidance_is_not_mistaken_for_a_heading(tmp_path):
    """A heading is a short label. A wall of instructions above the table is
    not, and would have made an unreadable location."""
    path = tmp_path / "guidance.docx"
    document = Document()
    document.add_paragraph(
        "Please complete every row of the table below, attaching evidence where "
        "the question asks for it, and return the form within ten working days "
        "of receipt to the address given on the first page of this document."
    )
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Question"
    table.cell(0, 1).text = "Answer"
    table.cell(1, 0).text = "Is data encrypted at rest?"
    document.save(path)

    assert forms.detect(path).questions[0].location == "table 1, row 2"


def test_a_numbered_row_is_named_by_its_number(tmp_path):
    """Where the form prints its own numbers, those beat a row coordinate."""
    path = tmp_path / "numbered.docx"
    document = Document()
    table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).text = "No."
    table.cell(0, 1).text = "Question"
    table.cell(0, 2).text = "Answer"
    table.cell(1, 0).text = "3.2"
    table.cell(1, 1).text = "Is data encrypted at rest?"
    document.save(path)

    assert forms.detect(path).questions[0].location == "table 1, 3.2"
