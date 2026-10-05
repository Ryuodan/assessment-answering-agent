"""What a person downloads: the Word and PDF exports, and the flat text forms.

One fixed result -- a confident English answer with Markdown and a source
marker, a flagged one with review reasons, and an Arabic one -- rendered under
the default options and under everything-included. Pinned: the text of the
Word document (paragraphs and tables), the text of each PDF page as pdfplumber
reads it, and what the flat formatters make of each answer (`to_cell_text` is
what `fill` writes into a cell; `to_plain_text` serves flat outputs).

The CSV download is assembled in the browser (`src/static/index.html`), not
on the server, so it is not covered here (see TD-016).
"""

from __future__ import annotations

import io

import pdfplumber
import pytest
from docx import Document

from src.export_docx import render_docx
from src.export_pdf import ExportOptions, render_pdf
from src.formatting import to_cell_text, to_plain_text
from src.models import AnsweredQuestion, AssessmentResult, Evidence, Question, SourceType

EVIDENCE = Evidence(
    source_type=SourceType.GUIDELINE,
    source_name="Access Control Policy.pdf",
    snippet="3.4.2 All logical access of a leaver is revoked within 24 hours of the end of employment.",
    score=0.71,
)

RESULT = AssessmentResult(
    run_id="run-characterization",
    source_name="Vendor Security Review.xlsx",
    language="en",
    questions_found=3,
    answers=[
        AnsweredQuestion(
            question=Question(id="1", text="How quickly is a leaver's access revoked?", section="Access"),
            answer="**Within 24 hours.** All logical access is revoked within 24 hours of the end of "
            "employment【1†source】.\n\n- Privileged accounts: on the last working day\n- Other accounts: within 24 hours",
            rationale="Clause 3.4.2.",
            confidence=0.86,
            needs_review=False,
            evidence=[EVIDENCE],
            citations=["Access Control Policy.pdf §3.4.2"],
        ),
        AnsweredQuestion(
            question=Question(id="2", text="Do you hold ISO 27001 certification?", section="Certifications"),
            answer="The documentation does not state a certification.",
            rationale="No source mentions ISO 27001.",
            confidence=0.35,
            needs_review=True,
            review_reasons=["below the confidence threshold", "no supporting source"],
            confidence_reason="Nothing retrieved addresses certification.",
        ),
        AnsweredQuestion(
            question=Question(id="3", text="هل يتم مراجعة صلاحيات الوصول بشكل دوري؟", language="ar"),
            answer="نعم، تتم مراجعة صلاحيات المستخدمين كل ربع سنة من قبل مالك النظام.",
            confidence=0.8,
            needs_review=False,
            citations=["Access Control Policy.pdf §3.5.1"],
        ),
    ],
)

OPTIONS = {
    "default": ExportOptions(),
    "everything": ExportOptions(include_flagged=True, include_citations=True, include_reasoning=True),
}


@pytest.mark.parametrize("option_name", sorted(OPTIONS))
def test_word_export(option_name, snapshot):
    document = Document(io.BytesIO(render_docx(RESULT, OPTIONS[option_name])))
    snapshot(
        f"exports/docx-{option_name}",
        {
            "paragraphs": [paragraph.text for paragraph in document.paragraphs],
            "tables": [[[cell.text for cell in row.cells] for row in table.rows] for table in document.tables],
        },
    )


@pytest.mark.parametrize("option_name", sorted(OPTIONS))
def test_pdf_export(option_name, snapshot):
    with pdfplumber.open(io.BytesIO(render_pdf(RESULT, OPTIONS[option_name]))) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    snapshot(f"exports/pdf-{option_name}", {"pages": pages})


def test_flat_text_forms(snapshot):
    snapshot(
        "exports/flat-text",
        {
            answered.question.id: {"cell": to_cell_text(answered.answer), "plain": to_plain_text(answered.answer)}
            for answered in RESULT.answers
        },
    )
