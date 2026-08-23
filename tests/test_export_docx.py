"""Word export of an answered assessment.

The PDF path has to reshape and reorder Arabic itself. Word does not: the text
is stored logically and marked right-to-left, and whatever opens the file lays
it out. So these tests check the marking rather than the glyphs — if `w:bidi`
is present the paragraph is correct, and if it is missing no amount of correct
text will render the way an Arabic reader expects.
"""

from __future__ import annotations

import io

import pytest
from docx import Document
from docx.oxml.ns import qn

from src.export_docx import render_docx
from src.export_pdf import ExportOptions
from src.models import AnsweredQuestion, AssessmentResult, Question

ARABIC_QUESTION = "هل يشترط استضافة وتخزين البيانات داخل المملكة العربية السعودية؟"
ARABIC_ANSWER = (
    "نعم، يجب تخزين البيانات داخل المملكة.\n"
    "1. **موقع تخزين البيانات داخل المملكة**\n"
    "2. تصنيف البيانات وتوسيمها قبل النقل"
)


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
                question=Question(id="26", text=ARABIC_QUESTION, language="ar"),
                answer=ARABIC_ANSWER,
                confidence=0.45,
                needs_review=True,
                confidence_reason="No single clause states this outright.",
                citations=["T2 - سياسة الحوسبة السحابية.pdf §3.4"],
            ),
            AnsweredQuestion(
                question=Question(id="3", text="Are you FedRAMP authorized?"),
                answer="The sources do not cover FedRAMP.",
                confidence=0.2,
                needs_review=True,
                review_reasons=["the reviewer did not find the answer grounded"],
            ),
        ],
    )


def _open(content: bytes) -> Document:
    return Document(io.BytesIO(content))


def _text(content: bytes) -> str:
    return "\n".join(p.text for p in _open(content).paragraphs)


def _is_rtl(paragraph) -> bool:
    properties = paragraph._p.pPr
    return properties is not None and properties.find(qn("w:bidi")) is not None


def _find(document: Document, needle: str):
    return next(p for p in document.paragraphs if needle in p.text)


# --- the file itself -------------------------------------------------------


def test_the_document_opens_as_a_word_file():
    content = render_docx(_result())
    assert content[:2] == b"PK"          # a .docx is a zip
    assert len(_open(content).paragraphs) > 5


def test_flagged_answers_are_excluded_by_default():
    text = _text(render_docx(_result()))
    assert "AES-256" in text
    assert "FedRAMP" not in text


def test_flagged_answers_are_included_when_asked_for():
    text = _text(render_docx(_result(), ExportOptions(include_flagged=True)))
    assert "FedRAMP" in text
    assert "NEEDS REVIEW" in text


def test_the_cover_note_says_what_was_left_out():
    text = _text(render_docx(_result()))
    assert "1 of 3 answers" in text
    assert "2 flagged for review and omitted" in text


def test_citations_are_on_by_default_and_can_be_turned_off():
    assert "§3.5.1" in _text(render_docx(_result()))
    assert "§3.5.1" not in _text(render_docx(_result(), ExportOptions(include_citations=False)))


def test_reasoning_is_off_by_default_and_can_be_turned_on():
    assert "cryptography policy" not in _text(render_docx(_result()))
    assert "cryptography policy" in _text(
        render_docx(_result(), ExportOptions(include_reasoning=True)))


def test_a_file_with_nothing_confident_still_renders_an_explanation():
    result = _result()
    for answered in result.answers:
        answered.needs_review = True
    assert "No answer met the confidence threshold" in _text(render_docx(result))


@pytest.mark.parametrize("options", [
    ExportOptions(),
    ExportOptions(include_flagged=True),
    ExportOptions(include_citations=False, include_reasoning=True),
    ExportOptions(include_flagged=True, include_citations=True, include_reasoning=True),
])
def test_every_option_combination_renders(options):
    assert render_docx(_result(), options)[:2] == b"PK"


# --- Arabic ----------------------------------------------------------------


def test_arabic_is_stored_as_readable_text_not_as_glyphs():
    """The advantage over the PDF: no reshaping, so the text stays searchable."""
    text = _text(render_docx(_result(), ExportOptions(include_flagged=True)))
    assert ARABIC_QUESTION in text


def test_an_arabic_question_is_marked_right_to_left():
    document = _open(render_docx(_result(), ExportOptions(include_flagged=True)))
    assert _is_rtl(_find(document, ARABIC_QUESTION))


def test_an_arabic_list_item_is_marked_right_to_left():
    """Alignment alone strands the marker on the wrong side; w:bidi moves it."""
    document = _open(render_docx(_result(), ExportOptions(include_flagged=True)))
    assert _is_rtl(_find(document, "تصنيف البيانات"))


def test_an_english_answer_is_not_marked_right_to_left():
    document = _open(render_docx(_result()))
    assert not _is_rtl(_find(document, "AES-256"))


# --- structure -------------------------------------------------------------


def test_list_markers_come_from_the_answer_not_from_word():
    """Word's own numbering runs on across questions; the drafter's does not."""
    document = _open(render_docx(_result(), ExportOptions(include_flagged=True)))
    item = _find(document, "تصنيف البيانات")
    assert item.text.startswith("2.")
    assert "List Number" not in item.style.name


def test_bold_in_an_answer_survives():
    document = _open(render_docx(_result(), ExportOptions(include_flagged=True)))
    item = _find(document, "موقع تخزين البيانات")
    assert any(run.bold and "موقع" in run.text for run in item.runs)


def test_the_confidence_is_always_stated_in_words_and_numbers():
    text = _text(render_docx(_result()))
    assert "High confidence" in text
    assert "90%" in text


def test_a_low_score_carries_its_explanation():
    text = _text(render_docx(_result(), ExportOptions(include_flagged=True)))
    assert "WHY THE CONFIDENCE IS LOW" in text
    assert "No single clause states this outright." in text


def test_a_flag_without_deterministic_reasons_still_says_something():
    """Question 26 is flagged only for its score, and must not be left blank."""
    text = _text(render_docx(_result(), ExportOptions(include_flagged=True)))
    assert "confidence is below the review threshold" in text
