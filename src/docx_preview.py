"""A Word document as a safe, self-contained HTML page, for the document viewer.

Moved out of `src/service.py` in plan 029, behaviour unchanged, so that
python-docx is used only from the integrations layer that owns it (TD-019).
`service.docx_preview_html` is still the name its callers use. Every piece of
the document's text is escaped: the preview is shown inside the app.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.text.run import Run

_ARABIC_TEXT = re.compile(r"[\u0600-\u06ff]")


def preview_html(path: str | Path) -> str:
    """Render a safe, self-contained HTML preview of a Word document."""
    from docx import Document as WordDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    path = Path(path)
    if path.suffix.lower() != ".docx":
        raise ValueError("HTML preview is only available for DOCX files.")

    document = WordDocument(str(path))
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            blocks.append(_preview_paragraph(Paragraph(child, document)))
        elif tag == "tbl":
            blocks.append(_preview_table(Table(child, document)))

    title = html.escape(path.stem.replace("_", " ").replace("-", " ").title())
    content = "\n".join(blocks)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 28px; background: #e8eaee; color: #1b1d21;
          font: 15px/1.55 Arial, "Noto Sans Arabic", sans-serif; }}
  .page {{ width: min(850px, 100%); min-height: 1050px; margin: 0 auto; padding: 58px 64px;
           counter-reset: preview-list;
           background: white; box-shadow: 0 2px 16px rgba(0,0,0,.14); }}
  h1, h2, h3, h4, h5, h6 {{ line-height: 1.25; margin: 1.2em 0 .45em; }}
  h1:first-child, h2:first-child {{ margin-top: 0; }}
  p {{ margin: .55em 0; white-space: normal; }}
  .spacer {{ height: .75em; }}
  .list-bullet {{ padding-inline-start: 1.4em; }}
  .list-bullet::before {{ content: "•"; display: inline-block; width: 1.2em; margin-inline-start: -1.2em; }}
  .list-number {{ padding-inline-start: 1.4em; }}
  .list-number {{ counter-increment: preview-list; }}
  .list-number::before {{ content: counter(preview-list) "."; display: inline-block; width: 1.4em;
                          margin-inline-start: -1.4em; }}
  .align-center {{ text-align: center; }}
  .align-right {{ text-align: right; }}
  .align-justify {{ text-align: justify; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 13px; }}
  th, td {{ border: 1px solid #aeb4bd; padding: 7px 9px; vertical-align: top; text-align: start; }}
  th {{ background: #edf1f6; font-weight: 700; }}
  [dir="rtl"] {{ text-align: right; }}
  @media (max-width: 700px) {{ body {{ padding: 0; }} .page {{ padding: 28px 22px; min-height: 100vh; }} }}
</style>
</head>
<body><main class="page">{content}</main></body>
</html>"""


def _preview_paragraph(paragraph: Paragraph) -> str:
    text = paragraph.text
    if not text.strip():
        return '<div class="spacer"></div>'

    style_name = paragraph.style.name if paragraph.style is not None else ""
    heading_match = re.fullmatch(r"Heading\s+([1-6])", style_name, flags=re.IGNORECASE)
    tag = f"h{heading_match.group(1)}" if heading_match else "p"

    classes = []
    lowered_style = style_name.lower()
    if "list bullet" in lowered_style:
        classes.append("list-bullet")
    elif "list number" in lowered_style:
        classes.append("list-number")

    # python-docx's alignment is an int enum: 1 centre, 2 right, 3 justify.
    alignments: dict[object, str] = {1: "align-center", 2: "align-right", 3: "align-justify"}
    alignment_class = alignments.get(paragraph.alignment)
    if alignment_class:
        classes.append(alignment_class)

    attributes = []
    if classes:
        attributes.append(f'class="{" ".join(classes)}"')
    if _ARABIC_TEXT.search(text):
        attributes.append('dir="rtl"')

    rendered_runs = "".join(_preview_run(run) for run in paragraph.runs)
    if not rendered_runs:
        rendered_runs = html.escape(text)
    attrs = f" {' '.join(attributes)}" if attributes else ""
    return f"<{tag}{attrs}>{rendered_runs}</{tag}>"


def _preview_run(run: Run) -> str:
    rendered = html.escape(run.text).replace("\t", "&emsp;").replace("\n", "<br>")
    if not rendered:
        return ""
    if run.bold:
        rendered = f"<strong>{rendered}</strong>"
    if run.italic:
        rendered = f"<em>{rendered}</em>"
    if run.underline:
        rendered = f"<u>{rendered}</u>"
    return rendered


def _preview_table(table: Table) -> str:
    rows = []
    for row_index, row in enumerate(table.rows):
        cells = []
        seen_cells = set()
        for cell in row.cells:
            cell_id = id(cell._tc)
            if cell_id in seen_cells:
                continue
            seen_cells.add(cell_id)

            cell_tag = "th" if row_index == 0 else "td"
            text = cell.text
            direction = ' dir="rtl"' if _ARABIC_TEXT.search(text) else ""
            paragraphs = "<br>".join(
                "".join(_preview_run(run) for run in paragraph.runs) or html.escape(paragraph.text)
                for paragraph in cell.paragraphs
                if paragraph.text.strip()
            )
            cells.append(f"<{cell_tag}{direction}>{paragraphs}</{cell_tag}>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{''.join(rows)}</table>"
