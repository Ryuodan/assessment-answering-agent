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
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate

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


def _render(text: str) -> str:
    """Escape for ReportLab's mini-markup, shaping Arabic where present."""
    if not has_arabic(text):
        return _escape(text)
    # Line by line: reordering must be applied per rendered line, and paragraph
    # breaks are the only line boundaries known before layout.
    lines = [get_display(arabic_reshaper.reshape(line)) for line in text.splitlines() or [""]]
    return "<br/>".join(_escape(line) for line in lines)


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
        "meta": ParagraphStyle(
            "m", parent=base["Normal"], fontName=FONT, fontSize=8.5, leading=12,
            textColor=colors.HexColor("#5b6472"), spaceBefore=3,
        ),
        "flag": ParagraphStyle(
            "f", parent=base["Normal"], fontName=FONT, fontSize=8.5, leading=12,
            textColor=colors.HexColor("#a2601a"), spaceBefore=3,
        ),
    }


def _answer_flow(answered: AnsweredQuestion, styles: dict, options: "ExportOptions") -> list:
    """The flowables for one question, kept on one page where they fit."""
    question_text = answered.question.text
    answer_text = answered.answer or "(no answer was produced)"

    flow = [
        Paragraph(
            f"{_escape(answered.question.id)}. {_render(question_text)}",
            styles["question_rtl" if has_arabic(question_text) else "question"],
        ),
        Paragraph(_render(answer_text), styles["answer_rtl" if has_arabic(answer_text) else "answer"]),
    ]

    if answered.needs_review:
        reasons = "; ".join(answered.review_reasons) or "below the confidence threshold"
        flow.append(Paragraph(f"Flagged for review — {_escape(reasons)}", styles["flag"]))

    if options.include_citations and answered.citations:
        flow.append(Paragraph("Sources: " + _escape(" · ".join(answered.citations)), styles["meta"]))

    if options.include_reasoning and answered.rationale:
        flow.append(Paragraph("Reasoning: " + _render(answered.rationale), styles["meta"]))

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
