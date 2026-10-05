"""Questionnaires arrive from other companies, over a public endpoint.

Nothing here is a normal file. These are the ones that turn up when the sender
is careless, the upload was truncated, or somebody is trying: what matters is
that each produces a sentence rather than a stack trace, and that none of them
can make the process do unbounded work.

The existing `test_hostile_input.py` covers the routes that existed before this.
This covers the parser those routes now feed.
"""

from __future__ import annotations

import time
import zipfile

import pytest
from docx import Document

from src import forms
from src.forms.xlsx_package import MAX_CELLS, MAX_PART_BYTES, Workbook
from tests import forms_fixtures as shapes


def _zip(path, parts: dict[str, str | bytes]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, payload in parts.items():
            package.writestr(name, payload)
    return path


# --- malformed workbooks ----------------------------------------------------


def test_a_file_that_is_not_a_zip_is_refused(tmp_path):
    path = tmp_path / "notes.xlsx"
    path.write_bytes(b"this was never a spreadsheet")
    with pytest.raises(forms.FormatError, match="not a readable"):
        forms.detect(path)


def test_a_truncated_upload_is_refused(tmp_path):
    good = shapes.simple(tmp_path / "good.xlsx")
    path = tmp_path / "half.xlsx"
    path.write_bytes(good.read_bytes()[:400])
    with pytest.raises(forms.FormatError, match="not a readable"):
        forms.detect(path)


def test_a_zip_without_a_workbook_part_is_refused(tmp_path):
    path = _zip(tmp_path / "empty.xlsx", {"hello.txt": "hi"})
    with pytest.raises(forms.FormatError, match="missing a part"):
        forms.detect(path)


def test_unparseable_xml_is_refused(tmp_path):
    path = _zip(
        tmp_path / "broken.xlsx",
        {
            "xl/workbook.xml": "<workbook><sheets><sheet",
            "xl/_rels/workbook.xml.rels": "<Relationships/>",
        },
    )
    with pytest.raises(forms.FormatError, match="could not be read"):
        forms.detect(path)


def test_a_workbook_listing_no_sheets_is_refused(tmp_path):
    path = _zip(
        tmp_path / "nosheets.xlsx",
        {
            "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
            "xl/_rels/workbook.xml.rels": "<Relationships/>",
        },
    )
    with pytest.raises(forms.FormatError, match="lists no sheets"):
        forms.detect(path)


def test_no_refusal_names_a_path_on_this_machine(tmp_path):
    """The message goes back to whoever uploaded the file. python-docx raises
    `PackageNotFoundError` carrying the full server path, which is exactly the
    leak the rest of this service already guards against."""
    for suffix in (".xlsx", ".docx"):
        path = tmp_path / f"broken{suffix}"
        path.write_bytes(b"not a package")
        with pytest.raises(forms.FormatError) as refused:
            forms.detect(path)
        message = str(refused.value)
        assert str(tmp_path) not in message
        assert message.startswith(f"broken{suffix}")


# --- hostile workbooks ------------------------------------------------------


def test_an_xml_entity_bomb_is_refused(tmp_path):
    """A few hundred bytes that expand to gigabytes if entities are resolved."""
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        + "".join(f'<!ENTITY lol{i} "{"&lol%d;" % (i - 1) * 10}">' for i in range(1, 10))
        + "]><workbook>&lol9;</workbook>"
    )
    path = _zip(
        tmp_path / "bomb.xlsx",
        {
            "xl/workbook.xml": bomb,
            "xl/_rels/workbook.xml.rels": "<Relationships/>",
        },
    )
    with pytest.raises(forms.FormatError):
        forms.detect(path)


@pytest.mark.parametrize("suffix", [".xlsx", ".docx"])
def test_a_zip_bomb_is_refused_before_it_is_expanded(tmp_path, suffix):
    """Turned away from the zip directory, so the 200 MB is never decompressed.

    Timed, because refusing it *after* expanding would pass a size assertion
    and still be the vulnerability.
    """
    inner = "xl/workbook.xml" if suffix == ".xlsx" else "word/document.xml"
    path = _zip(
        tmp_path / f"bomb{suffix}",
        {
            inner: "<x/>" + " " * (MAX_PART_BYTES + 1024),
            "xl/_rels/workbook.xml.rels": "<Relationships/>",
            "[Content_Types].xml": "<Types/>",
            "_rels/.rels": "<Relationships/>",
        },
    )
    start = time.perf_counter()
    with pytest.raises(forms.FormatError, match="past the"):
        forms.detect(path)
    assert time.perf_counter() - start < 2.0, "it was expanded before being refused"


def test_a_workbook_with_too_many_cells_is_refused(tmp_path):
    cells = {f"A{row}": "x" for row in range(1, MAX_CELLS + 2)}
    path = shapes.build(tmp_path / "huge.xlsx", [shapes.SheetSpec("Big", cells)])
    with pytest.raises(forms.FormatError, match="past the"):
        forms.detect(path)


def test_a_large_but_legitimate_sheet_stays_fast(tmp_path):
    """Detection reads rows inside nested loops. Recomputing the row list each
    time made this quadratic: 4,000 rows took a second and 30,000 took nearly
    three minutes, which is a denial of service with no attacker required."""
    cells = {"A1": "S.No", "B1": "Question", "C1": "Response"}
    for row in range(2, 8002):
        cells[f"A{row}"] = f"{row}.0"
        cells[f"B{row}"] = "Does the vendor maintain documented information security policies?"
    path = shapes.build(tmp_path / "big.xlsx", [shapes.SheetSpec("Big", cells)])

    start = time.perf_counter()
    form = forms.detect(path)
    elapsed = time.perf_counter() - start
    assert len(form.questions) == 8000
    assert elapsed < 5.0, f"8,000 rows took {elapsed:.1f}s"


def test_a_sheet_name_that_looks_like_a_path_is_harmless(tmp_path):
    """Sheet names reach target ids and come back from the interface. They never
    reach the filesystem, and this proves the id survives the round trip."""
    path = shapes.build(
        tmp_path / "traversal.xlsx",
        [
            shapes.SheetSpec(
                "../../../etc/passwd",
                {
                    "A1": "S.No",
                    "B1": "Question",
                    "C1": "Response",
                    "A2": "1.0",
                    "B2": "Does the vendor have documented information security policies?",
                    "A3": "2.0",
                    "B3": "Does the vendor review those policies at least annually?",
                    "A4": "3.0",
                    "B4": "Are staff bound by non-disclosure agreements?",
                },
            )
        ],
    )
    form = forms.detect(path)
    target = form.questions[0].writable[0]
    assert target.id == "../../../etc/passwd!C2"

    out = tmp_path / "out.xlsx"
    forms.write(path, out, {target.id: "Yes."})
    assert not (tmp_path / "etc").exists()
    with Workbook(out) as workbook:
        assert workbook["../../../etc/passwd"].value(2, "C") == "Yes."


def test_a_sheet_name_containing_a_bang_still_round_trips(tmp_path):
    """Target ids are 'sheet!ref', so a '!' in the name is a parsing hazard."""
    path = shapes.build(
        tmp_path / "bang.xlsx",
        [
            shapes.SheetSpec(
                "Q! Section",
                {
                    "A1": "S.No",
                    "B1": "Question",
                    "C1": "Response",
                    "A2": "1.0",
                    "B2": "Does the vendor have documented information security policies?",
                    "A3": "2.0",
                    "B3": "Does the vendor review those policies at least annually?",
                    "A4": "3.0",
                    "B4": "Are staff bound by non-disclosure agreements?",
                },
            )
        ],
    )
    form = forms.detect(path)
    target = form.questions[0].writable[0].id
    assert target == "Q! Section!C2"

    report = forms.write(path, tmp_path / "out.xlsx", {target: "Yes."})
    assert report.written == 1 and not report.skipped


# --- malformed documents ----------------------------------------------------


@pytest.mark.parametrize("payload", [b"not a package", b"", b"PK\x03\x04 truncated"])
def test_an_unreadable_document_is_refused(tmp_path, payload):
    path = tmp_path / "broken.docx"
    path.write_bytes(payload)
    with pytest.raises(forms.FormatError, match="not a readable"):
        forms.detect(path)


def test_a_document_with_no_questions_is_not_an_error(tmp_path):
    """An ordinary covering letter. Nothing to answer is a result, not a fault."""
    document = Document()
    document.add_paragraph("Please find our completed assessment attached.")
    path = tmp_path / "letter.docx"
    document.save(str(path))

    form = forms.detect(path)
    assert form.questions == [] and form.warnings


def test_writing_to_an_unreadable_file_is_refused(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a spreadsheet")
    with pytest.raises(forms.FormatError):
        forms.write(path, tmp_path / "out.xlsx", {"Sheet1!A1": "x"})


# --- writing safely ---------------------------------------------------------


def test_answering_a_workbook_in_place_does_not_destroy_it(tmp_path):
    """`write(path, path)` is the obvious call for 'answer this file', and it
    truncated the source while still reading it -- the questionnaire was gone
    and the error was a raw BadZipFile."""
    path = shapes.simple(tmp_path / "in-place.xlsx")
    form = forms.detect(path)
    report = forms.write(path, path, {q.writable[0].id: "Yes." for q in form.questions})

    assert report.written == 4 and report.intact
    again = forms.detect(path)
    assert len(again.questions) == 4 and again.answered_count == 4


def test_answering_a_document_in_place_does_not_destroy_it(tmp_path):
    from tests.test_forms_docx import prose_form

    path = prose_form(tmp_path / "in-place.docx")
    form = forms.detect(path)
    report = forms.write(path, path, {q.writable[0].id: "Yes." for q in form.questions})

    assert report.written == 5
    assert forms.detect(path).answered_count == 5


@pytest.mark.parametrize("shape", [shapes.simple, shapes.status_and_comment])
def test_a_write_leaves_no_half_finished_file_behind(tmp_path, shape):
    """Built beside the destination and moved into place, so a crash halfway
    leaves the old file rather than a corrupt new one."""
    path = shape(tmp_path / "source.xlsx")
    out = tmp_path / "out.xlsx"
    form = forms.detect(path)
    forms.write(path, out, {q.writable[0].id: "Yes." for q in form.questions})

    assert not list(tmp_path.glob("*.partial"))
