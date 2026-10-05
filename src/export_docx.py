"""Render an answered assessment as a Word document.

The obvious sibling of `export_pdf`, and the better format for Arabic. Word
carries text rather than glyphs: shaping and the bidi algorithm are applied by
whatever opens the file, so an Arabic paragraph only has to be *marked* as
right-to-left instead of being reshaped, reordered and hand-wrapped the way a
PDF demands. Numbered lists put their markers on the correct side by
themselves, and the text stays selectable, searchable and — the reason people
ask for it — editable, so a reviewer can finish the questionnaire in the file
the agent produced rather than retyping it.

The export options and the selection rule are shared with the PDF path, so both
formats answer "what goes back to an assessor" the same way.
"""

from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from src.forms.xlsx_package import xml_safe
from src.export_pdf import ExportOptions, cover_note, has_arabic, selected_answers
from src.formatting import parse
from src.models import AnsweredQuestion, AssessmentResult

# The same palette as the PDF, so the two exports look like one system.
INK = RGBColor(0x14, 0x18, 0x1F)
INK_SOFT = RGBColor(0x4A, 0x53, 0x61)
ACCENT = RGBColor(0x2C, 0x5C, 0xE6)
VIOLET = RGBColor(0x6D, 0x3F, 0xD4)
OK = RGBColor(0x0F, 0x7A, 0x4D)
WARN = RGBColor(0x9A, 0x62, 0x06)
ERR = RGBColor(0xB4, 0x23, 0x18)

HEADER_SHADE = "F5F7FA"

FONT_NAME = "Segoe UI"


def confidence_words(confidence: float) -> tuple[RGBColor, str]:
    """Colour and wording for a score, matching the PDF's bands."""
    if confidence >= 0.75:
        return OK, "High confidence"
    if confidence > 0.6:
        return WARN, "Moderate confidence"
    return ERR, "Low confidence"


# ---------------------------------------------------------------------------
# Low-level Word plumbing
# ---------------------------------------------------------------------------


def _element(paragraph, tag: str):
    """Fetch or create a child of the paragraph's properties element."""
    properties = paragraph._p.get_or_add_pPr()
    existing = properties.find(qn(tag))
    if existing is None:
        existing = properties.makeelement(qn(tag), {})
        properties.append(existing)
    return existing


def _set_rtl(paragraph, rtl: bool) -> None:
    """Mark a paragraph right-to-left.

    `w:bidi` is what makes Word lay the paragraph out from the right — list
    markers, punctuation and line breaking all follow from it. Alignment alone
    would only push a left-to-right paragraph against the right margin, which
    is what produces Arabic lists with their numbers stranded on the far side.
    """
    if not rtl:
        return
    _element(paragraph, "w:bidi")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _shade(paragraph, colour: str) -> None:
    shading = _element(paragraph, "w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), colour)


def _run(
    paragraph,
    text: str,
    *,
    bold: bool = False,
    size: float = 10.5,
    colour: RGBColor | None = None,
    italic: bool = False,
):
    # A model's text can carry a character XML may not hold, and python-docx
    # refuses the whole document over one. Every word in the file passes here.
    text = xml_safe(text)
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    run.font.name = FONT_NAME
    if colour is not None:
        run.font.color.rgb = colour
    if has_arabic(text):
        # Without w:rtl the characters are stored correctly but Word may still
        # measure them as a left-to-right run inside a mixed paragraph.
        properties = run._r.get_or_add_rPr()
        properties.append(properties.makeelement(qn("w:rtl"), {}))
    return run


def _spacing(paragraph, before: float = 0, after: float = 0, line: float = 1.15) -> None:
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = line


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def _label(document, text: str, colour: RGBColor) -> None:
    paragraph = document.add_paragraph()
    _spacing(paragraph, before=7, after=1)
    _run(paragraph, text.upper(), bold=True, size=7.5, colour=colour)


def _body_line(document, text: str, *, size: float = 9, colour: RGBColor = INK_SOFT) -> None:
    paragraph = document.add_paragraph()
    _spacing(paragraph, after=1)
    _set_rtl(paragraph, has_arabic(text))
    _run(paragraph, text, size=size, colour=colour)


def _question_header(document, answered: AnsweredQuestion) -> None:
    text = answered.question.text
    rtl = has_arabic(text)

    paragraph = document.add_paragraph()
    _spacing(paragraph, before=12, after=4)
    _set_rtl(paragraph, rtl)
    _shade(paragraph, HEADER_SHADE)
    _run(paragraph, f"{answered.question.id}.  ", bold=True, size=10.5, colour=ACCENT)
    _run(paragraph, text, bold=True, size=10.5, colour=INK)


def _answer_body(document, answer: str) -> None:
    """The answer, with its list structure kept and its own numbering kept too.

    Word's built-in List Number style numbers continuously down the document,
    so the second question's list would carry on from where the first one
    stopped. The markers the drafter wrote are the ones that match the clauses
    it cites, so they are written as literal text and Word is not asked to
    invent its own.
    """
    rtl = has_arabic(answer)
    for block in parse(answer):
        paragraph = document.add_paragraph()
        _spacing(paragraph, after=2, line=1.2)
        _set_rtl(paragraph, rtl)

        if block.kind in ("bullet", "number"):
            marker = "•" if block.kind == "bullet" else f"{block.marker}."
            indent = Pt(16)
            if rtl:
                paragraph.paragraph_format.right_indent = indent
            else:
                paragraph.paragraph_format.left_indent = indent
            _run(paragraph, f"{marker}  ", bold=True, size=10, colour=ACCENT)

        heading = block.kind == "heading"
        for text, bold in block.spans:
            _run(paragraph, text, bold=bold or heading, size=10, colour=INK)


def _answer(document, answered: AnsweredQuestion, options: ExportOptions) -> None:
    _question_header(document, answered)
    _answer_body(document, answered.answer or "(no answer was produced)")

    if answered.needs_review:
        _label(document, "Needs review", WARN)
        reasons = answered.review_reasons or ["confidence is below the review threshold"]
        _body_line(document, "; ".join(reasons))

    if answered.confidence_reason:
        _label(document, "Why the confidence is low", ERR)
        _body_line(document, answered.confidence_reason)

    if options.include_citations and answered.citations:
        _label(document, "Sources", ACCENT)
        for citation in answered.citations:
            _body_line(document, f"•  {citation}")

    if options.include_reasoning and answered.rationale:
        _label(document, "Reasoning", VIOLET)
        _body_line(document, answered.rationale)

    colour, word = confidence_words(answered.confidence)
    paragraph = document.add_paragraph()
    _spacing(paragraph, before=8, after=14)
    _run(paragraph, f"{word} — {round(answered.confidence * 100)}%", bold=True, size=9.5, colour=colour)


def render_docx(result: AssessmentResult, options: ExportOptions | None = None) -> bytes:
    """Render `result` as a .docx file and return the bytes."""
    options = options or ExportOptions()
    answers = selected_answers(result, options)

    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = Pt(10)

    title = document.add_paragraph()
    _spacing(title, after=2)
    _set_rtl(title, has_arabic(result.source_name))
    _run(title, result.source_name, bold=True, size=18, colour=INK)

    subtitle = document.add_paragraph()
    _spacing(subtitle, after=12)
    _run(subtitle, cover_note(result, answers), size=9.5, colour=INK_SOFT)

    if not answers:
        _body_line(
            document,
            "No answer met the confidence threshold. Tick “answers flagged for review” to export the drafts anyway.",
            size=10,
            colour=INK,
        )

    for answered in answers:
        _answer(document, answered, options)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


__all__ = ["confidence_words", "render_docx"]
