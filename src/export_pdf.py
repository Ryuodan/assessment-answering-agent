"""Render an answered assessment as a PDF.

Built server-side rather than in the browser because of Arabic. ReportLab draws
glyphs, not text runs: Arabic has to be shaped into contextual letter forms and
bidi-reordered before it is drawn, or it comes out as disconnected letters in
the wrong order. `arabic_reshaper` and the Unicode bidi algorithm do that here,
where they are already dependencies, instead of shipping an Arabic text engine
to the client.

The order of those two steps against line-breaking is the whole difficulty, and
getting it wrong is what produced the reported bug — see `_lay_out` below.

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
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.formatting import parse
from src.models import AnsweredQuestion, AssessmentResult

logger = logging.getLogger(__name__)

_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")

# --- geometry --------------------------------------------------------------

_MARGIN = 20 * mm
CONTENT_WIDTH = A4[0] - 2 * _MARGIN

# A section block spends this much on its colour bar and the gap after it.
_BAR_WIDTH = 3
_BAR_GAP = 8
_SECTION_WIDTH = CONTENT_WIDTH - _BAR_WIDTH - _BAR_GAP

# Width of the column a list marker sits in, on whichever side the script runs.
_MARKER_WIDTH = 22

# --- palette ---------------------------------------------------------------
# Kept in one place so the file reads as one document rather than as a set of
# independently coloured fragments.

INK = colors.HexColor("#14181f")
INK_SOFT = colors.HexColor("#4a5361")
INK_FAINT = colors.HexColor("#7b8595")
RULE = colors.HexColor("#dfe3ea")

ACCENT = colors.HexColor("#2c5ce6")  # sources
ACCENT_BG = colors.HexColor("#eef3ff")
VIOLET = colors.HexColor("#6d3fd4")  # reasoning
VIOLET_BG = colors.HexColor("#f3eeff")
OK = colors.HexColor("#0f7a4d")
OK_BG = colors.HexColor("#e6f5ed")
WARN = colors.HexColor("#9a6206")
WARN_BG = colors.HexColor("#fdf3e0")
ERR = colors.HexColor("#b42318")
ERR_BG = colors.HexColor("#fdecea")
HEADER_BG = colors.HexColor("#f5f7fa")

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
_COVERAGE: set[int] | None = None


class ExportError(RuntimeError):
    """The PDF could not be produced."""


def _bold_variant(regular: Path) -> Path:
    for suffix in ("-Bold", "bd", " Bold"):
        candidate = regular.with_name(f"{regular.stem}{suffix}{regular.suffix}")
        if candidate.is_file():
            return candidate
    return regular


def _register_fonts() -> None:
    global _FONTS_READY, _COVERAGE
    if _FONTS_READY:
        return

    regular = next((path for path in _FONT_CANDIDATES if path.is_file()), None)
    if regular is None:
        raise ExportError(
            "No Latin+Arabic TrueType font is installed, so a PDF cannot be rendered. "
            "Install DejaVu Sans (fonts-dejavu on Debian/Ubuntu)."
        )

    face = TTFont(FONT, str(regular))
    pdfmetrics.registerFont(face)
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(_bold_variant(regular))))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD)
    _COVERAGE = set(face.face.charToGlyph)
    _FONTS_READY = True


# ---------------------------------------------------------------------------
# Characters the font cannot draw
# ---------------------------------------------------------------------------

# Typographic punctuation the drafting model emits freely and Arial does not
# carry. U+2011 is the one that was reported: "Non-Disclosure" written with a
# non-breaking hyphen drew an empty box in the middle of the word, because a
# missing glyph is substituted with .notdef rather than reported as an error.
# Mapping to the ASCII equivalent loses nothing a reader would notice.
_PUNCTUATION = {
    0x2010: "-",
    0x2011: "-",
    0x2012: "-",
    0x2043: "-",
    0x2018: "'",
    0x2019: "'",
    0x201A: "'",
    0x201B: "'",
    0x201C: '"',
    0x201D: '"',
    0x201E: '"',
    0x201F: '"',
    0x2032: "'",
    0x2033: '"',
    0x00A0: " ",
    0x202F: " ",
    0x2007: " ",
    0x2009: " ",
    0x200A: " ",
    0x00AD: "",
    0x200B: "",
    0x200C: "",
    0x200D: "",
    0xFEFF: "",
    0x2066: "",
    0x2067: "",
    0x2068: "",
    0x2069: "",  # bidi isolates
}


def _sanitize(text: str) -> str:
    """Replace characters the chosen font has no glyph for.

    The explicit table covers what the model actually writes. The coverage
    sweep after it is the backstop: any remaining unmapped codepoint would
    otherwise be drawn as a hollow box, which looks like corruption in an
    answer that is in fact correct.
    """
    text = text.translate(_PUNCTUATION)
    if _COVERAGE is None:
        return text
    if all(ord(character) in _COVERAGE for character in text):
        return text
    return "".join(character for character in text if ord(character) in _COVERAGE)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def has_arabic(text: str) -> bool:
    return bool(_ARABIC.search(text))


def _shape(text: str) -> str:
    """Shape and reorder Arabic; leave Latin alone."""
    text = _sanitize(text)
    return get_display(arabic_reshaper.reshape(text)) if has_arabic(text) else text


# ---------------------------------------------------------------------------
# Line breaking
# ---------------------------------------------------------------------------
#
# Bidi reordering and line breaking do not commute, and doing them in the wrong
# order is what truncated the long Arabic questions.
#
# `get_display` converts a whole logical string into the single visual line a
# renderer would draw it as. Hand that to ReportLab and it wraps the result
# left to right, so the *end* of the sentence lands on the first line and its
# beginning — question number included — falls to the last. A 40-word Arabic
# question came out starting in the middle and finishing at the top left.
#
# So the text is broken into lines while it is still in logical order, and each
# finished line is reordered on its own. Every line then holds the words that
# belong on it, in the order Arabic is read.


def _font_for(bold: bool) -> str:
    return FONT_BOLD if bold else FONT


def _width_of(spans: list[tuple[str, bool]], size: float) -> float:
    return sum(pdfmetrics.stringWidth(_shape(text), _font_for(bold), size) for text, bold in spans)


def _tokenize(spans: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Words, each carrying the whitespace that preceded it.

    Keeping the space on the word rather than inferring it later is what lets a
    line be taken apart for measuring and put back together byte for byte,
    including at a boundary where the weight changes — `**bold**,` must not
    gain a space before its comma.
    """
    tokens: list[tuple[str, bool]] = []
    pending = ""
    for text, bold in spans:
        for piece in re.split(r"(\s+)", text):
            if not piece:
                continue
            if piece.isspace():
                pending = " "
            else:
                tokens.append((pending + piece, bold))
                pending = ""
    return tokens


def _merge(words: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Glue neighbouring words of the same weight back into one run.

    Wrapping has to see individual words; reordering must not. Reversing a line
    word by word turns an English clause quoted inside an Arabic sentence —
    "(Data storage location must be within the Kingdom)" — into its own mirror
    image. Restoring the runs before reordering means the bidi algorithm sees
    each Latin stretch whole and leaves its internal order alone.
    """
    runs: list[tuple[str, bool]] = []
    for text, bold in words:
        if runs and runs[-1][1] == bold:
            runs[-1] = (runs[-1][0] + text, bold)
        else:
            runs.append((text, bold))
    return runs


def _wrap(spans: list[tuple[str, bool]], size: float, width: float) -> list[list[tuple[str, bool]]]:
    """Break (text, bold) runs into lines that fit `width`, in logical order."""
    lines: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []

    for token, bold in _tokenize(spans):
        candidate = current + [(token, bold)]
        if current and _width_of(_merge(candidate), size) > width:
            lines.append(_merge(current))
            current = [(token.lstrip(), bold)]
        else:
            current = candidate
    if current:
        lines.append(_merge(current))
    return lines or [[("", False)]]


def _join(spans: list[tuple[str, bool]], rtl: bool) -> str:
    """One finished line as ReportLab markup.

    For a right-to-left line the runs are emitted last-first: ReportLab draws
    them left to right, so reversing the logical order puts the first run at
    the right-hand margin where Arabic starts. Each run is shaped on its own,
    which keeps a Latin fragment such as "(Non-Disclosure)" internally intact
    while still placing it correctly against the Arabic around it.
    """
    ordered = list(reversed(spans)) if rtl else spans
    return "".join(f"<b>{_escape(_shape(text))}</b>" if bold else _escape(_shape(text)) for text, bold in ordered)


def _lay_out(spans: list[tuple[str, bool]], style: ParagraphStyle, width: float) -> str:
    """Markup for a paragraph, pre-broken into lines when it runs right to left."""
    if not any(has_arabic(text) for text, _ in spans):
        return _join(spans, rtl=False)

    usable = width - style.leftIndent - style.rightIndent
    lines = _wrap(spans, style.fontSize, usable)
    return "<br/>".join(_join(line, rtl=True) for line in lines)


def _paragraph(text: str, style: ParagraphStyle, width: float = CONTENT_WIDTH) -> Paragraph:
    """A plain string as a correctly ordered paragraph."""
    spans = [(segment, False) for segment in text.split("\n")]
    if len(spans) == 1:
        return Paragraph(_lay_out(spans, style, width), style)
    return Paragraph("<br/>".join(_lay_out([span], style, width) for span in spans), style)


def _markup(block, style: ParagraphStyle, width: float) -> str:
    """One parsed line of an answer, laid out for its direction."""
    return _lay_out(list(block.spans), style, width)


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName=FONT_BOLD, fontSize=18, leading=23, textColor=INK, alignment=0
        ),
        "subtitle": ParagraphStyle(
            "st",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9.5,
            leading=13,
            textColor=INK_SOFT,
        ),
        "question": ParagraphStyle(
            "q",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=10.5,
            leading=14.5,
            textColor=INK,
        ),
        "question_rtl": ParagraphStyle(
            "q_rtl",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=10.5,
            leading=16,
            alignment=TA_RIGHT,
            textColor=INK,
        ),
        "qnum": ParagraphStyle(
            "qn",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=10.5,
            leading=14.5,
            textColor=ACCENT,
        ),
        "qnum_rtl": ParagraphStyle(
            "qn_rtl",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=10.5,
            leading=16,
            alignment=TA_RIGHT,
            textColor=ACCENT,
        ),
        "answer": ParagraphStyle(
            "a",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=14.5,
            spaceBefore=4,
            textColor=INK,
        ),
        "answer_rtl": ParagraphStyle(
            "a_rtl",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=16.5,
            alignment=TA_RIGHT,
            spaceBefore=4,
            textColor=INK,
        ),
        # `bulletFontName` matters for the left-to-right path: ReportLab draws
        # the bullet in Helvetica unless told otherwise, and Helvetica has no
        # glyph for U+2022 in the encoding used here.
        "bullet": ParagraphStyle(
            "b",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=14.5,
            leftIndent=14,
            bulletIndent=3,
            spaceBefore=2,
            bulletFontName=FONT,
            bulletFontSize=10,
            textColor=INK,
        ),
        "bullet_rtl": ParagraphStyle(
            "b_rtl",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=16.5,
            alignment=TA_RIGHT,
            textColor=INK,
        ),
        "marker_rtl": ParagraphStyle(
            "mk_rtl",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=16.5,
            alignment=TA_RIGHT,
            textColor=ACCENT,
        ),
        "answer_heading": ParagraphStyle(
            "ah",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=10,
            leading=14,
            spaceBefore=7,
            spaceAfter=1,
            textColor=INK,
        ),
        "label": ParagraphStyle(
            "lbl",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=7,
            leading=9.5,
        ),
        "meta": ParagraphStyle(
            "m",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8.8,
            leading=12.5,
            textColor=INK_SOFT,
        ),
        "meta_rtl": ParagraphStyle(
            "m_rtl",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8.8,
            leading=13.5,
            alignment=TA_RIGHT,
            textColor=INK_SOFT,
        ),
        "pill": ParagraphStyle(
            "p",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=9,
            leading=12,
            alignment=1,
        ),
    }


# ---------------------------------------------------------------------------
# Coloured building blocks
# ---------------------------------------------------------------------------


def _section(label: str, colour, body: list, styles: dict) -> Table:
    """A labelled block with a colour bar down its leading edge.

    The bar is what makes the three kinds of supporting material — where it
    came from, why it was written, how far to trust it — separable at a glance
    instead of reading as one grey footnote.
    """
    heading = Paragraph(f'<font color="{colour.hexval()}">{_escape(label.upper())}</font>', styles["label"])
    table = Table(
        [["", [heading, *body]]],
        colWidths=[_BAR_WIDTH, _SECTION_WIDTH + _BAR_GAP],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), colour),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), _BAR_GAP),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _pill(text: str, ink, background, styles: dict) -> Table:
    """A small filled badge, sized to its text rather than to the frame."""
    width = pdfmetrics.stringWidth(text, FONT_BOLD, 9) + 18
    cell = Paragraph(f'<font color="{ink.hexval()}">{_escape(text)}</font>', styles["pill"])
    table = Table([[cell]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("ROUNDEDCORNERS", [5, 5, 5, 5]),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def confidence_colours(confidence: float) -> tuple[colors.Color, colors.Color, str]:
    """Ink, background and wording for a confidence score."""
    if confidence >= 0.75:
        return OK, OK_BG, "High confidence"
    if confidence > 0.6:
        return WARN, WARN_BG, "Moderate confidence"
    return ERR, ERR_BG, "Low confidence"


def _list_item(markup: str, marker: str, styles: dict, rtl: bool, width: float) -> Table | Paragraph:
    """One bullet or numbered item, with its marker on the side the script starts.

    ReportLab's own `bulletText` is drawn at a fixed offset from the left edge
    regardless of alignment, so an Arabic list came out with every number
    stranded on the far side of the page from the text it numbered. Laying the
    item out as two cells puts the marker where the reader's eye starts.
    """
    if not rtl:
        return Paragraph(markup, styles["bullet"], bulletText=marker)

    body = Paragraph(markup, styles["bullet_rtl"])
    table = Table(
        [[body, Paragraph(_escape(marker), styles["marker_rtl"])]],
        colWidths=[width - _MARKER_WIDTH, _MARKER_WIDTH],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return table


def _answer_body(answer: str, styles: dict, width: float = CONTENT_WIDTH) -> list:
    """The answer itself, with its list structure preserved."""
    rtl = has_arabic(answer)
    flow = []
    for block in parse(answer):
        if block.kind in ("bullet", "number"):
            style = styles["bullet_rtl" if rtl else "bullet"]
            item_width = width - _MARKER_WIDTH if rtl else width
            markup = _markup(block, style, item_width)
            marker = "\u2022" if block.kind == "bullet" else f"{block.marker}."
            flow.append(_list_item(markup, marker, styles, rtl, width))
        elif block.kind == "heading":
            style = styles["answer_heading"]
            flow.append(Paragraph(_markup(block, style, width), style))
        else:
            style = styles["answer_rtl" if rtl else "answer"]
            flow.append(Paragraph(_markup(block, style, width), style))
    return flow or [Paragraph(_escape("(no answer was produced)"), styles["answer"])]


def _question_header(answered: AnsweredQuestion, styles: dict) -> Table:
    """The question, numbered on the side its script starts from."""
    text = answered.question.text
    rtl = has_arabic(text)
    number = f"{answered.question.id}."

    # Size the number column to the number, remembering that a ReportLab
    # column width is inclusive of its own padding. A fixed width was both too
    # narrow for "3.1.2" and, once padding came off, negative for "1.".
    padding = 16
    number_width = pdfmetrics.stringWidth(number, FONT_BOLD, 10.5) + padding
    body_width = CONTENT_WIDTH - number_width

    question = _paragraph(text, styles["question_rtl" if rtl else "question"], body_width - padding)
    marker = Paragraph(_escape(number), styles["qnum_rtl" if rtl else "qnum"])

    cells = [question, marker] if rtl else [marker, question]
    widths = [body_width, number_width] if rtl else [number_width, body_width]

    table = Table([cells], colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (0, 0), 10),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 10),
                ("ROUNDEDCORNERS", [4, 4, 4, 4]),
            ]
        )
    )
    return table


def _answer_flow(answered: AnsweredQuestion, styles: dict, options: "ExportOptions") -> list:
    """The flowables for one question, kept together on a page where they fit."""
    ink, background, word = confidence_colours(answered.confidence)
    percent = round(answered.confidence * 100)

    flow: list = [_question_header(answered, styles), Spacer(1, 7)]
    flow.extend(_answer_body(answered.answer or "", styles))

    if answered.needs_review:
        reasons = answered.review_reasons or ["confidence is below the review threshold"]
        body = [
            Spacer(1, 2),
            _paragraph("; ".join(reasons), styles["meta"], _SECTION_WIDTH),
        ]
        flow.append(Spacer(1, 9))
        flow.append(_section("Needs review", WARN, body, styles))

    if answered.confidence_reason:
        body = [Spacer(1, 2), _paragraph(answered.confidence_reason, styles["meta"], _SECTION_WIDTH)]
        flow.append(Spacer(1, 8))
        flow.append(_section("Why the confidence is low", ERR, body, styles))

    if options.include_citations and answered.citations:
        items = [Spacer(1, 2)]
        for citation in answered.citations:
            style = styles["meta_rtl"] if has_arabic(citation) else styles["meta"]
            items.append(_paragraph(f"\u2022  {citation}", style, _SECTION_WIDTH))
        flow.append(Spacer(1, 8))
        flow.append(_section("Sources", ACCENT, items, styles))

    if options.include_reasoning and answered.rationale:
        body = [Spacer(1, 2), _paragraph(answered.rationale, styles["meta"], _SECTION_WIDTH)]
        flow.append(Spacer(1, 8))
        flow.append(_section("Reasoning", VIOLET, body, styles))

    flow.append(Spacer(1, 9))
    flow.append(_pill(f"{word} \u2014 {percent}%", ink, background, styles))
    flow.append(Spacer(1, 6))
    flow.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=6, spaceAfter=2))
    flow.append(Spacer(1, 10))
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


def cover_note(result: AssessmentResult, answers: list[AnsweredQuestion]) -> str:
    """The line under the title saying what this file does and does not hold."""
    excluded = len(result.answers) - len(answers)
    note = f"{len(answers)} of {len(result.answers)} answers"
    if excluded:
        note += f" \u2014 {excluded} flagged for review and omitted"
    return note + ". Every answer is a draft and should be read before submission."


def render_pdf(result: AssessmentResult, options: ExportOptions | None = None) -> bytes:
    """Render `result` as a PDF and return the bytes."""
    options = options or ExportOptions()
    styles = _styles()
    answers = selected_answers(result, options)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=result.source_name,
        author="Assessment Answering Agent",
    )

    flow: list = [
        _paragraph(result.source_name, styles["title"]),
        _paragraph(cover_note(result, answers), styles["subtitle"]),
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=2.5, color=ACCENT, spaceBefore=0, spaceAfter=16),
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
    canvas.setFillColor(INK_FAINT)
    canvas.drawRightString(A4[0] - _MARGIN, 12 * mm, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


__all__ = [
    "ExportError",
    "ExportOptions",
    "confidence_colours",
    "cover_note",
    "render_pdf",
    "selected_answers",
]
