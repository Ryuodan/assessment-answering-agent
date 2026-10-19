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
    assert "NEEDS REVIEW" in text


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


@pytest.mark.parametrize(
    "options",
    [
        ExportOptions(),
        ExportOptions(include_flagged=True),
        ExportOptions(include_citations=False, include_reasoning=True),
        ExportOptions(include_flagged=True, include_citations=True, include_reasoning=True),
    ],
)
def test_every_option_combination_renders(options):
    assert render_pdf(_result(), options).startswith(b"%PDF-")


# --- markup rendering ------------------------------------------------------


def _with_answer(answer: str) -> AssessmentResult:
    return AssessmentResult(
        run_id="t",
        source_name="markup.pdf",
        language="en",
        questions_found=1,
        answers=[
            AnsweredQuestion(
                question=Question(id="1", text="What are the requirements?"),
                answer=answer,
                confidence=0.9,
                needs_review=False,
            )
        ],
    )


def test_bold_markers_do_not_reach_the_page():
    """The reported complaint: raw ** in the exported answer."""
    text = _text(render_pdf(_with_answer("Retention is **twelve (12) months** minimum.")))
    assert "**" not in text
    assert "twelve (12) months" in text


def test_bullets_are_rendered_as_a_list_not_as_hyphens():
    answer = "The controls are:\n- Encryption at rest\n- Multi-factor authentication"
    text = _text(render_pdf(_with_answer(answer)))
    assert "Encryption at rest" in text
    assert "- Encryption" not in text


def test_numbered_items_keep_their_numbers():
    answer = "Stages:\n1. Notify the regulator\n2. Contain the breach"
    text = _text(render_pdf(_with_answer(answer)))
    assert "Notify the regulator" in text
    assert "Contain the breach" in text


def test_a_heading_inside_an_answer_survives():
    text = _text(render_pdf(_with_answer("## Rotation\nKeys rotate annually.")))
    assert "Rotation" in text
    assert "##" not in text


def test_confidence_is_always_reported():
    """Reported as a badge now: the number alone told a reader nothing."""
    text = _text(render_pdf(_with_answer("Plain answer.")))
    assert "90%" in text
    assert "High confidence" in text


# --- Arabic layout ---------------------------------------------------------
#
# The reported failures, each pinned to the property that was violated rather
# than to a screenshot.

LONG_ARABIC_QUESTION = (
    "هل يشترط استضافة وتخزين البيانات داخل المملكة العربية السعودية؟ وما هي البنود "
    "التعاقدية الإلزامية المطلوب تضمينها في اتفاقيات مستوى الخدمة مع مزودي الخدمات "
    "السحابية والاستضافة؟"
)


def _arabic_result(question: str = LONG_ARABIC_QUESTION, answer: str = ARABIC_ANSWER):
    return AssessmentResult(
        run_id="t",
        source_name="تقييم.pdf",
        language="ar",
        questions_found=1,
        answers=[
            AnsweredQuestion(
                question=Question(id="26", text=question, language="ar"),
                answer=answer,
                confidence=0.8,
                needs_review=False,
            )
        ],
    )


def _recovered(pdf_bytes: bytes) -> str:
    return "\n".join(to_logical_order(line) for line in _text(pdf_bytes).splitlines())


def _words(pdf_bytes: bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return pdf.pages[0].extract_words()


def test_a_long_arabic_question_is_not_reordered_across_its_lines():
    """Bidi was applied before wrapping, so the sentence started on line two.

    Reordering a whole paragraph produces the single line a renderer would
    draw; wrapping that afterwards puts its tail at the top. The opening words
    have to survive as one contiguous run on the first line.
    """
    recovered = _recovered(render_pdf(_arabic_result()))

    assert "هل يشترط استضافة وتخزين البيانات" in recovered
    assert "والاستضافة؟" in recovered


def test_the_question_number_leads_the_question():
    """ "26." belongs against the first words, not stranded after the last."""
    recovered = _recovered(render_pdf(_arabic_result()))
    first = next(line for line in recovered.splitlines() if "يشترط" in line)

    assert first.strip().startswith(".26") or first.strip().startswith("26.")


def test_an_arabic_list_marker_sits_on_the_right():
    """ReportLab draws bulletText a fixed distance from the left, whatever the
    alignment, which put every number on the far side of its own list."""
    answer = "الشروط:\n1. موقع تخزين البيانات داخل المملكة\n2. تصنيف البيانات وتوسيمها"
    words = _words(render_pdf(_arabic_result(answer=answer)))

    markers = [w for w in words if w["text"] in ("1.", ".1", "2.", ".2")]
    assert markers, "no list markers were drawn"

    page_middle = 595 / 2
    assert all(word["x0"] > page_middle for word in markers)


def test_an_english_list_marker_stays_on_the_left():
    result = _with_answer("Controls:\n1. Encryption at rest\n2. Multi-factor authentication")
    words = _words(render_pdf(result))

    markers = [w for w in words if w["text"] in ("1.", "2.")]
    assert markers and all(word["x0"] < 595 / 2 for word in markers)


def test_english_quoted_inside_an_arabic_sentence_keeps_its_word_order():
    """Reordering an RTL line word by word mirrors any Latin clause inside it."""
    answer = "يجب تخزين البيانات (Data storage location must be within the Kingdom)."
    recovered = _recovered(render_pdf(_arabic_result(answer=answer)))

    assert "Data storage location must be within the Kingdom" in recovered


# --- glyph coverage --------------------------------------------------------


def test_a_hyphen_the_font_lacks_is_replaced_rather_than_boxed():
    """U+2011 is absent from Arial, so "Non-Disclosure" drew an empty box."""
    text = _text(render_pdf(_with_answer("Include a Non‑Disclosure clause.")))

    assert "Non-Disclosure" in text
    assert "‑" not in text


@pytest.mark.parametrize("character", ["‐", "‑", "‒"])
def test_every_exotic_hyphen_lands_as_an_ascii_one(character):
    text = _text(render_pdf(_with_answer(f"a{character}b")))
    assert "a-b" in text


def test_curly_quotes_are_normalised():
    text = _text(render_pdf(_with_answer("“quoted” and ‘single’")))
    assert '"quoted"' in text and "'single'" in text


def test_a_zero_width_character_is_dropped_not_drawn():
    text = _text(render_pdf(_with_answer("data​base")))
    assert "database" in text


# --- the sections a reviewer reads -----------------------------------------


def test_a_flag_without_deterministic_reasons_still_explains_itself():
    result = _result()
    result.answers[2].review_reasons = []
    text = _text(render_pdf(result, ExportOptions(include_flagged=True)))

    assert "confidence is below the review threshold" in text


def test_the_confidence_explanation_is_rendered_when_present():
    result = _result()
    result.answers[2].confidence_reason = "Nothing in the knowledge base matched this question."
    text = _text(render_pdf(result, ExportOptions(include_flagged=True)))

    assert "WHY THE CONFIDENCE IS LOW" in text
    assert "Nothing in the knowledge base matched this question." in text


def test_the_supporting_sections_are_labelled():
    text = _text(render_pdf(_result(), ExportOptions(include_reasoning=True)))
    assert "SOURCES" in text
    assert "REASONING" in text


def test_two_remembered_answers_of_one_name_are_listed_once():
    """As in the Word export: one line for a name two cited remembered answers share (plan 027)."""
    result = _result()
    result.answers[0].citations = ["Answer memory (2026-10-19)", "Answer memory (2026-10-19)"]

    assert _text(render_pdf(result)).count("Answer memory (2026-10-19)") == 1
