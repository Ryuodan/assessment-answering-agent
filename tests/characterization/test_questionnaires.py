"""Reading a customer's questionnaire, and writing answers back into it.

Every fixture questionnaire the suite builds (11 spreadsheets, 4 Word layouts)
is read by the rules reader, and the whole reading is pinned: questions,
targets, roles, vocabularies, findings, warnings. Then every writable target
is filled with a value derived from its id, and what lands in the file is
pinned cell by cell (paragraph by paragraph for Word), with the write report.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from src import forms
from src.forms.model import Role
from src.forms.xlsx_package import Workbook
from tests import forms_fixtures
from tests.test_forms_docx import prose_form, table_form

SPREADSHEETS = {
    builder.__name__: builder
    for builder in (
        forms_fixtures.simple,
        forms_fixtures.header_below_preamble,
        forms_fixtures.status_and_comment,
        forms_fixtures.ownership_banner,
        forms_fixtures.headless_numbered,
        forms_fixtures.legend_sheet,
        forms_fixtures.with_extra_parts,
        forms_fixtures.two_row_header,
        forms_fixtures.reference_column_headed_id,
        forms_fixtures.headless_typo_header,
        forms_fixtures.already_answered,
    )
}

WORD = {
    "prose": lambda path: prose_form(path),
    "prose_answered": lambda path: prose_form(path, answered=True),
    "table": lambda path: table_form(path),
    "table_fragments": lambda path: table_form(path, fragments=True),
}


def _open(kind: str, name: str, tmp_path: Path) -> Path:
    if kind == "xlsx":
        return Path(SPREADSHEETS[name](tmp_path / f"{name}.xlsx"))
    path = tmp_path / f"{name}.docx"
    WORD[name](path)
    return path


def _detect(path: Path) -> forms.DetectedForm:
    return forms.detect(path, assist=False) if path.suffix == ".xlsx" else forms.detect(path)


def _values(form: forms.DetectedForm) -> dict[str, str]:
    """A deterministic value for every writable target: the first allowed word
    for a status with a vocabulary, otherwise text naming the target."""
    values: dict[str, str] = {}
    for question in form.questions:
        for target in question.writable:
            if target.role is Role.STATUS and target.vocabulary:
                values[target.id] = target.vocabulary[0]
            else:
                values[target.id] = f"Answer for {target.id} ({target.role.value})"
    return values


def _cells(path: Path) -> dict[str, dict[str, str]]:
    workbook = Workbook(path)
    try:
        return {
            sheet.name: {
                f"{column}{row}": value
                for row in sheet.rows
                for column, value in sheet.row_values(row).items()
                if value
            }
            for sheet in workbook.sheets
        }
    finally:
        workbook.close()


def _word_text(path: Path) -> dict[str, list]:
    document = Document(str(path))
    return {
        "paragraphs": [p.text for p in document.paragraphs],
        "tables": [[[cell.text for cell in row.cells] for row in table.rows] for table in document.tables],
    }


CASES = [("xlsx", name) for name in SPREADSHEETS] + [("docx", name) for name in WORD]


@pytest.mark.parametrize(("kind", "name"), CASES, ids=[f"{k}-{n}" for k, n in CASES])
def test_reading(kind, name, tmp_path, default_settings, snapshot):
    form = _detect(_open(kind, name, tmp_path))
    snapshot(f"questionnaires/read-{kind}-{name}", form.model_dump(mode="json"))


@pytest.mark.parametrize(("kind", "name"), CASES, ids=[f"{k}-{n}" for k, n in CASES])
def test_filling(kind, name, tmp_path, default_settings, snapshot):
    source = _open(kind, name, tmp_path)
    form = _detect(source)
    values = _values(form)
    destination = tmp_path / f"filled-{source.name}"
    report = forms.write(source, destination, values)
    written = _cells(destination) if kind == "xlsx" else _word_text(destination)
    snapshot(
        f"questionnaires/fill-{kind}-{name}",
        {"values": values, "report": report.model_dump(mode="json"), "file": written},
    )
