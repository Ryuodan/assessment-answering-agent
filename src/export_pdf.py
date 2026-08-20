"""Render an answered assessment as a PDF.

Built server-side rather than in the browser because of Arabic. ReportLab draws
glyphs, not text runs: Arabic has to be shaped into contextual letter forms and
bidi-reordered before it is drawn, or it comes out as disconnected letters in
the wrong order. `arabic_reshaper` and the Unicode bidi algorithm do that here,
where they are already dependencies, instead of shipping an Arabic text engine
to the client.

What goes in the file is a deliberate default: answers the system was confident
about. A questionnaire returned to an assessor should not carry drafts the
system itself flagged for review, so those are excluded unless asked for — and
when they are included they are labelled, never silently mixed in.
"""

from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from src.formatting import parse
from src.models import AnsweredQuestion, AssessmentResult

logger = logging.getLogger(__name__)

_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")

# A font covering Latin and Arabic. Same candidate list as the demo generator:
# the app runs on Linux in production and on developer machines elsewhere.
_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu") / "DejaVuSans.ttf",
    Path("/Library/Fonts") / "Arial Unicode.ttf",
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
)

FONT = "Assessment"
FONT_BOLD = "Assessment-Bold"
_FONTS_READY = False


class ExportError(RuntimeError):
    """The PDF could not be produced."""


def _bold_variant(regular: Path) -> Path:
    for suffix in ("-Bold", "bd", " Bold"):
        candidate = regular.with_name(f"{regular.stem}{suffix}{regular.suffix}")
        if candidate.is_file():
            return candidate
    return regular


def _register_fonts() -> None:
    global _FONTS_READY
    if _FONTS_READY:
        return

    regular = next((path for path in _FONT_CANDIDATES if path.is_file()), None)
    if regular is None:
        raise ExportError(
            "No Latin+Arabic TrueType font is installed, so a PDF cannot be rendered. "
            "Install DejaVu Sans (fonts-dejavu on Debian/Ubuntu)."
        )

    pdfmetrics.registerFont(TTFont(FONT, str(regular)))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(_bold_variant(regular))))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD)
    _FONTS_READY = True


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def has_arabic(text: str) -> bool:
    return bool(_ARABIC.search(text))


def _shape(text: str) -> str:
    """Shape and reorder Arabic; leave Latin alone."""
    return get_display(arabic_reshaper.reshape(text)) if has_arabic(text) else text


def _render(text: str) -> str:
    """Escape for ReportLab's mini-markup, shaping Arabic where present."""
    lines = text.splitlines() or [""]
    return "<br/>".join(_escape(_shape(line)) for line in lines)


def _markup(block) -> str:
    """One parsed line as ReportLab markup, with its emphasis kept as bold.

    Shaping runs per span rather than per line: an Arabic sentence with a bold
    figure inside it is three runs, and each has to be shaped on its own before
    the tags go around it, or the tags end up inside the reordered text.
    """
    return "".join(
        f"<b>{_escape(_shape(span))}</b>" if bold else _escape(_shape(span))
        for span, bold in block.spans
    )


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName=FONT_BOLD, fontSize=18, leading=23),
        "subtitle": ParagraphStyle(
            "st", parent=base["Normal"], fontName=FONT, fontSize=9.5, leading=13,
            textColor=colors.HexColor("#5b6472"), spaceAfter=14,
        ),
        "question": ParagraphStyle(
            "q", parent=base["Normal"], fontName=FONT_BOLD, fontSize=10.5, leading=14, spaceBefore=12,
        ),
        "question_rtl": ParagraphStyle(
            "q_rtl", parent=base["Normal"], fontName=FONT_BOLD, fontSize=10.5, leading=15,
            alignment=TA_RIGHT, spaceBefore=12,
        ),
        "answer": ParagraphStyle(
            "a", parent=base["Normal"], fontName=FONT, fontSize=10, leading=14.5, spaceBefore=4,
        ),
        "answer_rtl": ParagraphStyle(
            "a_rtl", parent=base["Normal"], fontName=FONT, fontSize=10, leading=16,
            alignment=TA_RIGHT, spaceBefore=4,
        ),
        # `bulletFontName` matters: ReportLab draws the bullet in Helvetica
        # unless told otherwise, and Helvetica has no glyph for U+2022 in the
        # encoding used here — every bullet came out as an unmapped character.
        "bullet": ParagraphStyle(
            "b", parent=base["Normal"], fontName=FONT, fontSize=10, leading=14.5,
            leftIndent=14, bulletIndent=3, spaceBefore=2, bulletFontName=FONT, bulletFontSize=10,
        ),
        "bullet_rtl": ParagraphStyle(
            "b_rtl", parent=base["Normal"], fontName=FONT, fontSize=10, leading=16,
            alignment=TA_RIGHT, rightIndent=14, spaceBefore=2, bulletFontName=FONT, bulletFontSize=10,
        ),
        "answer_heading": ParagraphStyle(
            "ah", parent=base["Normal"], fontName=FONT_BOLD, fontSize=10, leading=14,
            spaceBefore=7, spaceAfter=1,
        ),
        "label": ParagraphStyle(
            "lbl", parent=base["Normal"], fontName=FONT_BOLD, fontSize=6.8, leading=9,
            textColor=colors.HexColor("#8a94a4"), spaceBefore=5,
        ),
        "meta": ParagraphStyle(
            "m", parent=base["Normal"], fontName=FONT, fontSize=8.5, leading=12,
            textColor=colors.HexColor("#5b6472"),
        ),
        "flag": ParagraphStyle(
            "f", parent=base["Normal"], fontName=FONT, fontSize=8.5, leading=12,
            textColor=colors.HexColor("#9a5b12"), backColor=colors.HexColor("#fdf4e3"),
            borderPadding=(5, 6, 5, 6), leftIndent=0,
        ),
    }


def _answer_body(answer: str, styles: dict) -> list:
    """The answer itself, with its list structure preserved."""
    rtl = has_arabic(answer)
    flow = []
    for block in parse(answer):
        markup = _markup(block)
        if block.kind == "bullet":
            style = styles["bullet_rtl" if rtl else "bullet"]
            flow.append(Paragraph(markup, style, bulletText="•"))
        elif block.kind == "number":
            style = styles["bullet_rtl" if rtl else "bullet"]
            flow.append(Paragraph(markup, style, bulletText=f"{block.marker}."))
        elif block.kind == "heading":
            flow.append(Paragraph(markup, styles["answer_heading"]))
        else:
            flow.append(Paragraph(markup, styles["answer_rtl" if rtl else "answer"]))
    return flow or [Paragraph(_escape("(no answer was produced)"), styles["answer"])]


def _label(text: str, styles: dict) -> Paragraph:
    return Paragraph(_escape(text.upper()), styles["label"])


def _answer_flow(answered: AnsweredQuestion, styles: dict, options: "ExportOptions") -> list:
    """The flowables for one question, kept together on a page where they fit."""
    question_text = answered.question.text
    confidence = f"{round(answered.confidence * 100)}% confidence"

    flow: list = [
        Paragraph(
            f"{_escape(answered.question.id)}.&nbsp;&nbsp;{_render(question_text)}",
            styles["question_rtl" if has_arabic(question_text) else "question"],
        ),
        HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#dfe3ea"),
                   spaceBefore=4, spaceAfter=7),
    ]
    flow.extend(_answer_body(answered.answer or "", styles))

    if answered.needs_review:
        reasons = "; ".join(answered.review_reasons) or "confidence below the review threshold"
        flow.append(Spacer(1, 5))
        flow.append(Paragraph(_escape(f"NEEDS REVIEW — {reasons}"), styles["flag"]))

    footnotes = []
    if options.include_citations and answered.citations:
        footnotes.append(("Sources", " · ".join(answered.citations)))
    if options.include_reasoning and answered.rationale:
        footnotes.append(("Reasoning", answered.rationale))
    footnotes.append(("Confidence", confidence))

    if footnotes:
        flow.append(Spacer(1, 5))
        for name, value in footnotes:
            flow.append(_label(name, styles))
            flow.append(Paragraph(_render(value), styles["meta"]))

    flow.append(Spacer(1, 16))
    return [KeepTogether(flow)]


class ExportOptions:
    """What to put in the file. Defaults are what you would send to an assessor."""

    def __init__(
        self,
        *,
        include_flagged: bool = False,
        include_citations: bool = True,
        include_reasoning: bool = False,
    ):
        self.include_flagged = include_flagged
        self.include_citations = include_citations
        self.include_reasoning = include_reasoning


def selected_answers(result: AssessmentResult, options: ExportOptions) -> list[AnsweredQuestion]:
    """The answers this export covers, in document order."""
    if options.include_flagged:
        return list(result.answers)
    return [answered for answered in result.answers if not answered.needs_review]


def render_pdf(result: AssessmentResult, options: ExportOptions | None = None) -> bytes:
    """Render `result` as a PDF and return the bytes."""
    options = options or ExportOptions()
    styles = _styles()
    answers = selected_answers(result, options)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=result.source_name,
        author="Assessment Answering Agent",
    )

    excluded = len(result.answers) - len(answers)
    subtitle = f"{len(answers)} of {len(result.answers)} answers"
    if excluded:
        subtitle += f" — {excluded} flagged for review and omitted"
    subtitle += ". Every answer is a draft and should be read before submission."

    flow: list = [
        Paragraph(_render(result.source_name), styles["title"]),
        Paragraph(_escape(subtitle), styles["subtitle"]),
    ]

    if not answers:
        flow.append(
            Paragraph(
                "No answer met the confidence threshold. Tick &#8220;answers flagged for review&#8221; "
                "to export the drafts anyway.",
                styles["answer"],
            )
        )
    for answered in answers:
        flow.extend(_answer_flow(answered, styles, options))

    document.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#8a94a4"))
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


__all__ = ["ExportError", "ExportOptions", "render_pdf", "selected_answers"]
