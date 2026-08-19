"""PDF export of an answered assessment.

The default matters as much as the rendering: what goes back to an assessor
must not quietly include drafts the system flagged for review.
"""

from __future__ import annotations

import io

import pdfplumber
import pytest

from src.documents import to_logical_order
from src.export_pdf import ExportOptions, render_pdf, selected_answers
from src.models import AnsweredQuestion, AssessmentResult, Question

ARABIC_ANSWER = "يجب الاحتفاظ بسجلات الأحداث لمدة 12 شهرا على الأقل."


def _result() -> AssessmentResult:
    return AssessmentResult(
        run_id="test",
        source_name="vendor review.pdf",
        language="en",
        questions_found=3,
        answers=[
            AnsweredQuestion(
                question=Question(id="1", text="Do you encrypt data at rest?"),
                answer="Yes, AES-256 is applied to all stored data.",
                confidence=0.9,
                needs_review=False,
                citations=["T2 - Cryptography Policy.pdf §3.5.1"],
                rationale="Directly stated in the cryptography policy.",
            ),
            AnsweredQuestion(
                question=Question(id="2", text="ما هي مدة الاحتفاظ بسجلات الأحداث؟", language="ar"),
                answer=ARABIC_ANSWER,
                confidence=0.85,
                needs_review=False,
                citations=["T2 - Event Logs Policy.pdf §3.2"],
            ),
            AnsweredQuestion(
                question=Question(id="3", text="Are you FedRAMP authorized?"),
                answer="The sources do not cover FedRAMP.",
                confidence=0.2,
                needs_review=True,
                review_reasons=["the reviewer did not find the answer grounded"],
                rationale="Nothing in the knowledge base mentions FedRAMP.",
            ),
        ],
    )


def _text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# --- what is included ------------------------------------------------------


def test_flagged_answers_are_excluded_by_default():
    selected = selected_answers(_result(), ExportOptions())
    assert [answered.question.id for answered in selected] == ["1", "2"]


def test_flagged_answers_are_included_when_asked_for():
    selected = selected_answers(_result(), ExportOptions(include_flagged=True))
    assert [answered.question.id for answered in selected] == ["1", "2", "3"]


def test_the_default_file_says_what_it_left_out():
    text = _text(render_pdf(_result(), ExportOptions()))
    assert "2 of 3 answers" in text
    assert "1 flagged for review and omitted" in text
    assert "FedRAMP" not in text


def test_an_included_draft_is_labelled_as_flagged():
    """A draft may go in the file, but never unmarked."""
    text = _text(render_pdf(_result(), ExportOptions(include_flagged=True)))
    assert "FedRAMP" in text
    assert "Flagged for review" in text


def test_citations_are_on_by_default_and_can_be_turned_off():
    with_cites = _text(render_pdf(_result(), ExportOptions()))
    without = _text(render_pdf(_result(), ExportOptions(include_citations=False)))

    assert "§3.5.1" in with_cites
    assert "§3.5.1" not in without


def test_reasoning_is_off_by_default_and_can_be_turned_on():
    without = _text(render_pdf(_result(), ExportOptions()))
    with_reasoning = _text(render_pdf(_result(), ExportOptions(include_reasoning=True)))

    assert "Directly stated in the cryptography policy" not in without
    assert "Directly stated in the cryptography policy" in with_reasoning


def test_a_file_with_nothing_confident_still_renders_an_explanation():
    result = _result()
    for answered in result.answers:
        answered.needs_review = True

    text = _text(render_pdf(result, ExportOptions()))

    assert "No answer met the confidence threshold" in text


# --- Arabic ----------------------------------------------------------------


def test_arabic_survives_the_round_trip_through_the_pdf():
    """Shaped and reordered on the way in, recoverable on the way out.

    Reading the PDF back gives visual-order presentation forms, exactly like the
    Arabic source policies — so the extractor that handles those recovers the
    original sentence. That round trip is the real proof the text was not
    mangled, and it is what any downstream reader would have to do.
    """
    text = _text(render_pdf(_result(), ExportOptions()))

    recovered = "\n".join(to_logical_order(line) for line in text.splitlines())

    assert "يجب الاحتفاظ بسجلات الأحداث" in recovered
    assert "12" in recovered


def test_an_embedded_number_is_not_reversed_in_arabic_text():
    """The 12 -> 21 failure, guarded on the way out as well as the way in."""
    text = _text(render_pdf(_result(), ExportOptions()))
    recovered = "\n".join(to_logical_order(line) for line in text.splitlines())

    assert "12 شهرا" in recovered
    assert "21 شهرا" not in recovered


def test_latin_and_english_answers_are_untouched():
    text = _text(render_pdf(_result(), ExportOptions()))
    assert "Yes, AES-256 is applied to all stored data." in text


# --- structure -------------------------------------------------------------


def test_every_page_is_numbered():
    text = _text(render_pdf(_result(), ExportOptions(include_flagged=True)))
    assert "Page 1" in text


def test_the_document_is_a_valid_pdf():
    content = render_pdf(_result(), ExportOptions())
    assert content.startswith(b"%PDF-")
    assert len(content) > 1000


@pytest.mark.parametrize("options", [
    ExportOptions(),
    ExportOptions(include_flagged=True),
    ExportOptions(include_citations=False, include_reasoning=True),
    ExportOptions(include_flagged=True, include_citations=True, include_reasoning=True),
])
def test_every_option_combination_renders(options):
    assert render_pdf(_result(), options).startswith(b"%PDF-")
