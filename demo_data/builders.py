"""Document builders for the demo corpus.

Two output formats matter to the app: DOCX and PDF (see
`src.documents.SUPPORTED_SUFFIXES`). Both are written from the same content
structures so a policy can be emitted either way.

Arabic needs care in PDF. ReportLab draws glyphs, not text runs, so Arabic must
be shaped (contextual letter forms) and bidi-reordered before it is drawn. That
is what `_shape` does. The consequence is covered in demo_data/README.md.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿ]")

_FONTS_READY = False


def _register_fonts() -> None:
    """DejaVu covers Latin and Arabic presentation forms; register it once."""
    global _FONTS_READY
    if _FONTS_READY:
        return
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")
    _FONTS_READY = True


def has_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _shape(text: str, width: float | None = None, font: str = "DejaVu", size: float = 9.5) -> str:
    """Shape + reorder Arabic so ReportLab draws it correctly. No-op for Latin.

    Bidi reordering has to be applied per *rendered line*, not to the whole
    string. ReportLab word-wraps whatever it is handed, so reversing first and
    letting it wrap afterwards splits the reversed text at the wrong points:
    the PDF looks right, but every extractor reads the lines back in the wrong
    order. So the line breaks are computed here, against the real font metrics
    and the real column width, and each line is reversed on its own.

    Pass `width` (the available text width in points) whenever the text can
    wrap. Without it the whole string is treated as one line.
    """
    if not has_arabic(text):
        return _escape(text)

    reshaped = arabic_reshaper.reshape(text)
    if width is None:
        return _escape(get_display(reshaped))

    lines: list[str] = []
    current = ""
    for word in reshaped.split(" "):
        candidate = f"{current} {word}".strip()
        if not current or pdfmetrics.stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    return "<br/>".join(_escape(get_display(line)) for line in lines)


# --- DOCX ------------------------------------------------------------------


def build_docx(path: Path, blocks: list[tuple]) -> Path:
    """Write a DOCX from ('heading'|'para'|'bullet'|'table', payload) blocks."""
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    for kind, payload in blocks:
        if kind == "title":
            document.add_heading(payload, level=0)
        elif kind == "heading":
            document.add_heading(payload, level=1)
        elif kind == "subheading":
            document.add_heading(payload, level=2)
        elif kind == "para":
            paragraph = document.add_paragraph(payload)
            if has_arabic(payload):
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif kind == "bullet":
            document.add_paragraph(payload, style="List Bullet")
        elif kind == "table":
            header, rows = payload
            table = document.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            for cell, text in zip(table.rows[0].cells, header):
                cell.text = str(text)
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            for row in rows:
                cells = table.add_row().cells
                for cell, text in zip(cells, row):
                    cell.text = str(text)
                    if has_arabic(str(text)):
                        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            document.add_paragraph()
        else:  # pragma: no cover - guards a typo in the content module
            raise ValueError(f"unknown block kind: {kind}")

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path


# --- PDF -------------------------------------------------------------------


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName="DejaVu-Bold", fontSize=17, leading=22, spaceAfter=10
        ),
        "heading": ParagraphStyle(
            "h", parent=base["Heading1"], fontName="DejaVu-Bold", fontSize=13, leading=17,
            spaceBefore=12, spaceAfter=6,
        ),
        "subheading": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="DejaVu-Bold", fontSize=11, leading=15,
            spaceBefore=8, spaceAfter=4,
        ),
        "para": ParagraphStyle(
            "p", parent=base["BodyText"], fontName="DejaVu", fontSize=9.5, leading=14,
            alignment=TA_JUSTIFY, spaceAfter=6,
        ),
        "para_rtl": ParagraphStyle(
            "p_rtl", parent=base["BodyText"], fontName="DejaVu", fontSize=9.5, leading=15,
            alignment=TA_RIGHT, spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "b", parent=base["BodyText"], fontName="DejaVu", fontSize=9.5, leading=14,
            leftIndent=12, bulletIndent=4, spaceAfter=3,
        ),
        "cell": ParagraphStyle("c", fontName="DejaVu", fontSize=8.5, leading=11.5),
        "cell_rtl": ParagraphStyle("c_rtl", fontName="DejaVu", fontSize=8.5, leading=12.5, alignment=TA_RIGHT),
        "cell_head": ParagraphStyle("ch", fontName="DejaVu-Bold", fontSize=8.5, leading=11.5),
    }


CELL_PADDING = 10.0  # LEFTPADDING + RIGHTPADDING in the table style below


def _cell(text: str, styles: dict, width: float, header: bool = False) -> Paragraph:
    text = str(text)
    if header:
        style = styles["cell_head"]
    else:
        style = styles["cell_rtl"] if has_arabic(text) else styles["cell"]
    shaped = _shape(text, width=width - CELL_PADDING, font=style.fontName, size=style.fontSize)
    return Paragraph(shaped or "&nbsp;", style)


def build_pdf(path: Path, blocks: list[tuple], col_widths: list[float] | None = None) -> Path:
    """Write a PDF from the same block structures `build_docx` consumes."""
    styles = _styles()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=path.stem,
    )

    flow = []
    for kind, payload in blocks:
        if kind in {"title", "heading", "subheading"}:
            style = styles[kind]
            flow.append(Paragraph(_shape(payload, doc.width, style.fontName, style.fontSize), style))
        elif kind == "para":
            style = styles["para_rtl"] if has_arabic(payload) else styles["para"]
            flow.append(Paragraph(_shape(payload, doc.width, style.fontName, style.fontSize), style))
        elif kind == "bullet":
            style = styles["bullet"]
            available = doc.width - style.leftIndent
            flow.append(Paragraph(_shape(payload, available, style.fontName, style.fontSize), style,
                                  bulletText="•"))
        elif kind == "table":
            header, rows = payload
            widths = col_widths or _auto_widths(len(header), doc.width)
            data = [[_cell(c, styles, widths[i], header=True) for i, c in enumerate(header)]]
            data += [[_cell(c, styles, widths[i]) for i, c in enumerate(row)] for row in rows]
            table = Table(data, colWidths=widths, repeatRows=1)
            table.setStyle(
                TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9aa0a6")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eaed")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ])
            )
            flow.append(table)
            flow.append(Spacer(1, 8))
        else:  # pragma: no cover
            raise ValueError(f"unknown block kind: {kind}")

    doc.build(flow)
    return path


def _auto_widths(columns: int, total: float) -> list[float]:
    """Narrow first column for '#'-style indexes, the rest split evenly."""
    if columns == 1:
        return [total]
    index = 12 * mm
    rest = (total - index) / (columns - 1)
    return [index] + [rest] * (columns - 1)


# --- CSV -------------------------------------------------------------------


def build_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    """UTF-8 with BOM so Excel opens the Arabic columns correctly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path
