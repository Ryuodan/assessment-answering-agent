"""Understanding a questionnaire in a Word document.

Two shapes turn up, and the prose one -- the one that looked hardest -- is the
easier of them:

* **Prose.** No tables at all: a section heading, then `Q1 :` ... `Q6 :`, each
  sometimes followed by `Evidence Required:`, and the answer goes in a paragraph
  that **does not exist yet**. Measured on the real document, 139 of 139
  questions matched on a bold `Q<n>` lead, and the blank copy of the same file
  contains zero answer paragraphs. So writing here is insertion, and the
  formatting has to be constructed rather than copied from a neighbour.

* **Tables.** `No. | Question | Answer`, except that one logical table is split
  across page breaks into many `<w:tbl>` elements, most of which begin
  mid-numbering with no header of their own. Twenty-two tables in the sample are
  really about eight, and stitching the fragments back together is the work.

Anchors are paragraph indices in the document as it was read. Inserting shifts
every index after it, so `write` resolves all of them first and then edits from
the end of the document backwards.
"""

from __future__ import annotations

import copy
import os
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.forms.model import DetectedForm, Finding, FormQuestion, Part, Role, Target, WriteReport
from src.forms.xlsx_package import MAX_PART_BYTES, FormatError

_QUESTION = re.compile(r"^\s*Q\s*(\d+)\s*[:.\-]?\s", re.I)
_ANSWER = re.compile(r"^\s*(?:Answer|Response|الإجابة)\s*[:.\-]?", re.I)
_EVIDENCE = re.compile(r"^\s*Evidence\s*Required", re.I)
_SECTION = re.compile(r"^[^:]{3,90}:\s*$")
_ARABIC = re.compile(r"[؀-ۿ]")

_HEADER_QUESTION = ("question", "requirement", "inquiry", "control", "سؤال")
_HEADER_ANSWER = ("answer", "response", "comment", "remark", "إجابة")
_HEADER_NUMBER = ("no.", "no", "#", "s.no", "s#")

ANSWER_LABEL = "Answer :  "
"""What the sample document prints before every answer, kept verbatim."""


def _language(text: str) -> str:
    arabic = len(_ARABIC.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "ar" if arabic > latin else "en"


def _is_rtl(text: str) -> bool:
    return _language(text) == "ar"


def _blocks(document) -> list[tuple[str, object]]:
    """Paragraphs and tables in the order they appear, which python-docx hides."""
    out: list[tuple[str, object]] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            out.append(("p", Paragraph(child, document)))
        elif child.tag == qn("w:tbl"):
            out.append(("tbl", Table(child, document)))
    return out


def _paragraph_index(document) -> list[Paragraph]:
    return document.paragraphs


# --- prose questionnaires ---------------------------------------------------


def _detect_prose(document, form: DetectedForm) -> list[FormQuestion]:
    """Questions written as paragraphs, with answers to be inserted after them."""
    paragraphs = _paragraph_index(document)
    questions: list[FormQuestion] = []
    section = ""

    for index, paragraph in enumerate(paragraphs):
        text = paragraph.text.strip()
        if not text:
            continue
        if _SECTION.match(text) and not _QUESTION.match(text):
            section = text.rstrip(": ").strip()
            continue
        match = _QUESTION.match(text)
        if not match:
            continue

        # The answer belongs after the whole question block: the question, any
        # 'Evidence Required' line, and any continuation paragraph, but before
        # the next question or section.
        anchor = index
        existing = ""
        for ahead in range(index + 1, len(paragraphs)):
            following = paragraphs[ahead].text.strip()
            if _QUESTION.match(following) or (_SECTION.match(following) and following):
                break
            if _ANSWER.match(following):
                existing = _ANSWER.sub("", following).strip()
                anchor = ahead
                break
            if following or _EVIDENCE.match(following):
                anchor = ahead

        # Identify the question by what it is, not where it sits. Inserting an
        # answer shifts the index of every paragraph after it, so a positional
        # id would move for all 139 questions the moment the first one was
        # answered. Numbering restarts in each section, so the section is part
        # of it. Targets stay positional -- they have to, that is how a
        # paragraph is found -- but they are resolved within a single write.
        number = f"Q{match.group(1)}"
        questions.append(FormQuestion(
            id=f"{section}/{number}" if section else f"{number}@{index}",
            number=number,
            text=_QUESTION.sub("", text).strip(),
            section=section,
            language=_language(text),
            targets={Role.ANSWER: Target(
                id=f"para:{anchor}",
                role=Role.ANSWER,
                label="Answer",
                existing=existing,
            )},
            # Named the way the document names it. "paragraph 142" is a number
            # nothing in Word will show you; the section and the printed
            # question number are what a person scrolls to find.
            location=f"{section}, {number}" if section else f"{number} (paragraph {index + 1})",
        ))
    return questions


def _insert_answer(document, anchor: Paragraph, text: str, *, replace: bool) -> None:
    """Put an answer after `anchor`, or rewrite `anchor` if it is already one.

    A blank copy of the form has no answer paragraphs at all, so there is no
    sibling to copy formatting from. The shell comes from the *question*
    instead, which carries the same style and the same bold-lead shape -- which
    also means this works whether or not anything has been answered before.
    """
    if replace:
        target = anchor
        for run in list(target.runs):
            run._element.getparent().remove(run._element)
    else:
        shell = copy.deepcopy(anchor._p)
        for run in shell.findall(qn("w:r")):
            shell.remove(run)          # keep the paragraph properties, drop the words
        anchor._p.addnext(shell)
        target = Paragraph(shell, anchor._parent)

    model = anchor.runs[0]._element if anchor.runs else None
    for chunk, bold in ((ANSWER_LABEL, True), (text, False)):
        if model is not None:
            target._p.append(copy.deepcopy(model))
            run = target.runs[-1]
        else:
            run = target.add_run()
        run.text = chunk
        run.bold = bold

    if _is_rtl(text):
        # Word lays Arabic out left-aligned with the punctuation in the wrong
        # place unless the paragraph and its runs say they are right-to-left.
        properties = target._p.get_or_add_pPr()
        properties.append(properties.makeelement(qn("w:bidi"), {}))
        for run in target.runs:
            run_properties = run._element.get_or_add_rPr()
            run_properties.append(run_properties.makeelement(qn("w:rtl"), {}))


# --- table questionnaires ---------------------------------------------------


def _header_columns(row) -> dict[str, int] | None:
    """Which column is which, from a table's first row -- or None if it is data."""
    labels = [" ".join(cell.text.split()).lower() for cell in row.cells]
    found: dict[str, int] = {}
    for index, label in enumerate(labels):
        if not label:
            continue
        if any(word in label for word in _HEADER_QUESTION) and "question" not in found:
            found["question"] = index
        elif any(word in label for word in _HEADER_ANSWER) and "answer" not in found:
            found["answer"] = index
        elif label in _HEADER_NUMBER and "number" not in found:
            found["number"] = index
    return found if "question" in found and "answer" in found else None


def _headings_above_tables(document) -> dict[int, str]:
    """The last real line of text before each table, by table index.

    A table questionnaire usually has no numbering column and no banner row, so
    the only thing left to name a row by was "table 2, row 5" -- a coordinate
    nothing in Word will show you. The line above the table is what the document
    itself calls that section, and it is what a person scrolls to find.

    Read from the body in document order, which is the only place the two kinds
    of element are interleaved; `document.tables` and `document.paragraphs` are
    each flattened and cannot be zipped back together.
    """
    headings: dict[int, str] = {}
    index = 0
    last = ""
    for element in document.element.body.iterchildren():
        if element.tag == qn("w:p"):
            text = " ".join(Paragraph(element, document).text.split())
            # A one-line label, not a paragraph of guidance.
            if text and len(text) <= 90:
                last = text.rstrip(":")
        elif element.tag == qn("w:tbl"):
            headings[index] = last
            index += 1
            last = ""
    return headings


def _detect_tables(document, form: DetectedForm) -> list[FormQuestion]:
    """Questions in tables, stitching fragments split across page breaks."""
    questions: list[FormQuestion] = []
    columns: dict[str, int] | None = None
    width = 0
    section = ""
    above = _headings_above_tables(document)

    for table_index, table in enumerate(document.tables):
        if not table.rows:
            continue
        rows = list(table.rows)
        header = _header_columns(rows[0])
        if header is not None:
            columns, width = header, len(table.columns)
            first = 1
        elif columns is not None and len(table.columns) == width:
            # A continuation: same shape, no header of its own. One sample
            # splits a single logical table into twenty-two of these.
            first = 0
        else:
            continue

        for actual in range(first, len(rows)):
            cells = rows[actual].cells
            if columns["question"] >= len(cells) or columns["answer"] >= len(cells):
                continue
            text = " ".join(cells[columns["question"]].text.split())
            if not text:
                continue
            # A row whose cells all say the same thing is a section banner
            # merged across the table's width.
            if len({" ".join(cell.text.split()) for cell in cells}) == 1:
                section = text
                continue
            # A second header row. One form heads its answer columns 'Response'
            # and then 'Yes | No' underneath, and the second row read as the
            # first question.
            if _header_columns(rows[actual]) is not None:
                continue

            number = ""
            if "number" in columns and columns["number"] < len(cells):
                number = " ".join(cells[columns["number"]].text.split())

            answer_cell = cells[columns["answer"]]
            questions.append(FormQuestion(
                id=f"table:{table_index}/r{actual}",
                number=number,
                text=text,
                section=section,
                language=_language(text),
                targets={Role.ANSWER: Target(
                    id=f"table:{table_index}/r{actual}/c{columns['answer']}",
                    role=Role.ANSWER,
                    label="Answer",
                    existing=" ".join(answer_cell.text.split()),
                )},
                location=_table_location(
                    section or above.get(table_index, ""), number, table_index, actual
                ),
            ))
    return questions


def _table_location(section: str, number: str, table_index: int, row: int) -> str:
    """Name a row the way the document names it, falling back to coordinates."""
    where = f"row {row + 1}"
    if section and number:
        return f"{section}, {number}"
    if section:
        return f"{section}, {where}"
    if number:
        return f"table {table_index + 1}, {number}"
    return f"table {table_index + 1}, {where}"


# --- the interface ----------------------------------------------------------


def _open(path: Path):
    """Open a document, or say why it cannot be read.

    Nothing from the underlying error reaches the message. python-docx raises
    `PackageNotFoundError` carrying the **full server path** of the file, and
    these documents arrive from other companies over a public endpoint -- the
    one thing an unreadable upload must not do is describe our filesystem to
    whoever sent it.
    """
    _guard_size(path)
    try:
        return Document(str(path))
    except Exception as error:                 # PackageNotFoundError, KeyError, lxml errors
        raise FormatError(f"{path.name} is not a readable .docx file.") from error


def _guard_size(path: Path) -> None:
    """Refuse a part that would decompress to more than we will hold.

    Read from the zip directory, so a bomb is turned away before expanding.
    """
    try:
        with zipfile.ZipFile(path) as package:
            oversized = [item for item in package.infolist() if item.file_size > MAX_PART_BYTES]
    except (zipfile.BadZipFile, OSError) as error:
        raise FormatError(f"{path.name} is not a readable .docx file.") from error
    if oversized:
        raise FormatError(
            f"{path.name} contains a part of {oversized[0].file_size / 1024 / 1024:,.0f} MB, "
            f"past the {MAX_PART_BYTES // 1024 // 1024} MB this reads."
        )


def detect(path: str | Path) -> DetectedForm:
    """Read a Word questionnaire and report what can be answered in it."""
    path = Path(path)
    document = _open(path)
    form = DetectedForm(source_name=path.name, format="docx")

    prose = _detect_prose(document, form)
    tables = _detect_tables(document, form)

    if prose:
        form.questions.extend(prose)
        form.parts.append(Part(
            name="document body", kind="questions", questions=len(prose),
            findings=[Finding(
                subject="document body",
                verdict=f"{len(prose)} questions",
                because="paragraphs beginning 'Q<n>', each answered in a paragraph after it",
            )],
        ))
    if tables:
        form.questions.extend(tables)
        form.parts.append(Part(
            name="tables", kind="questions", questions=len(tables),
            findings=[Finding(
                subject="tables",
                verdict=f"{len(tables)} questions",
                because=f"{len(document.tables)} table(s), stitched where a header was missing",
            )],
        ))
    if not form.questions:
        form.warnings.append(
            "No questions were found: no paragraphs beginning 'Q<n>', and no table "
            "with a question and an answer column."
        )
    return form


def write(path: str | Path, destination: str | Path, values: dict[str, str]) -> WriteReport:
    """Write answers into a copy of the document.

    Paragraph edits are applied from the end backwards. Inserting a paragraph
    shifts the index of everything after it, so resolving anchors as we go would
    put the second answer in the wrong place and every later one further adrift.
    """
    path, destination = Path(path), Path(destination)
    parts_before = _part_count(path)      # before the source can be replaced
    document = _open(path)
    paragraphs = _paragraph_index(document)

    created: list[str] = []
    replaced: list[str] = []
    skipped: dict[str, str] = {}

    paragraph_edits: list[tuple[int, str, str]] = []
    for target_id, text in values.items():
        if target_id.startswith("para:"):
            try:
                index = int(target_id.split(":", 1)[1])
            except ValueError:
                skipped[target_id] = "Not a paragraph reference."
                continue
            if index >= len(paragraphs):
                skipped[target_id] = "That paragraph is not in the document."
                continue
            paragraph_edits.append((index, target_id, text))
        elif target_id.startswith("table:"):
            _write_table_cell(document, target_id, text, created, replaced, skipped)
        else:
            skipped[target_id] = "Not a target this document understands."

    for index, target_id, text in sorted(paragraph_edits, reverse=True):
        anchor = paragraphs[index]
        replace = bool(_ANSWER.match(anchor.text.strip()))
        _insert_answer(document, anchor, text, replace=replace)
        (replaced if replace else created).append(target_id)

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Saved beside the destination and moved into place, for the same two
    # reasons as the workbook side: `write(path, path)` would otherwise
    # truncate the file it is reading, and a crash halfway through would leave
    # half a document where the questionnaire used to be.
    temporary = destination.with_name(destination.name + ".partial")
    try:
        document.save(str(temporary))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    return WriteReport(
        path=str(destination),
        created=sorted(created),
        replaced=sorted(replaced),
        skipped=skipped,
        parts_before=parts_before,
        parts_after=_part_count(destination),
    )


def _write_table_cell(
    document,
    target_id: str,
    text: str,
    created: list[str],
    replaced: list[str],
    skipped: dict[str, str],
) -> None:
    try:
        _, rest = target_id.split(":", 1)
        table_part, row_part, cell_part = rest.split("/")
        table_index = int(table_part)
        row_index = int(row_part[1:])
        cell_index = int(cell_part[1:])
    except (ValueError, IndexError):
        skipped[target_id] = "Not a table reference."
        return

    try:
        cell = document.tables[table_index].rows[row_index].cells[cell_index]
    except IndexError:
        skipped[target_id] = "That cell is not in the document."
        return

    had = bool(cell.text.strip())
    # A table cell always has at least one paragraph, so this is a rewrite
    # rather than an insertion -- the third of the three shapes 'blank' takes.
    paragraph = cell.paragraphs[0]
    for run in list(paragraph.runs):
        run._element.getparent().remove(run._element)
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    run = paragraph.add_run()
    run.text = text
    if _is_rtl(text):
        properties = paragraph._p.get_or_add_pPr()
        properties.append(properties.makeelement(qn("w:bidi"), {}))
        run_properties = run._element.get_or_add_rPr()
        run_properties.append(run_properties.makeelement(qn("w:rtl"), {}))

    (replaced if had else created).append(target_id)


def _part_count(path: Path) -> int:
    with zipfile.ZipFile(path) as package:
        return len(package.namelist())
