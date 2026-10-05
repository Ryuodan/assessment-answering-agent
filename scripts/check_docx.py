"""Check what a real .docx actually yields, end to end.

The self-check greps `_load_docx` for heading handling, so a delegating wrapper
reads as unpatched even when it works. This script settles the question the
honest way: it builds a Word file with real Heading styles, a real numbered list
and a real table, runs it through the actual loader, and reports what survived.

Run:  python -m scripts.check_docx
"""

from __future__ import annotations

import inspect
import sys
import tempfile
from pathlib import Path


def build_sample(path: Path) -> None:
    from docx import Document

    document = Document()
    document.add_heading("MDS-CS-STD-003 Secure Configuration Standard", level=1)
    document.add_heading("7.2 SOC alert conditions", level=2)
    document.add_paragraph("The SOC shall generate alerts for the following conditions:")

    # Word stores these numbers in the numbering XML, not in paragraph.text.
    for text in (
        "Failed authentication attempts exceeding five within fifteen minutes.",
        "Successful authentication from an unobserved geography.",
        "Privileged account creation outside an approved change window.",
        "Disabling of endpoint protection agents.",
    ):
        document.add_paragraph(text, style="List Number")

    table = document.add_table(rows=3, cols=3)
    for row_index, row_values in enumerate(
        [
            ("Severity", "Internet-facing", "Internal"),
            ("Critical", "24 hours", "72 hours"),
            ("High", "7 days", "14 days"),
        ]
    ):
        for cell_index, value in enumerate(row_values):
            table.cell(row_index, cell_index).text = value

    document.save(str(path))


def main() -> int:
    from src.chunking import chunk_document
    from src.config import settings
    from src.documents import _load_docx

    source = inspect.getsource(_load_docx)
    delegating = len(source.strip().splitlines()) <= 3
    print(f"_load_docx is {'a delegating wrapper' if delegating else 'inline'}\n")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.docx"
        build_sample(path)
        text = _load_docx(path)

    print("--- extracted text " + "-" * 51)
    print(text)
    print("-" * 70)

    chunks = chunk_document(text, source_name="sample.docx", chunk_size=settings.chunk_size)
    print("\n--- chunks " + "-" * 59)
    for chunk in chunks:
        meta = chunk.metadata
        print(f"[{meta['chunk']}] kind={meta['kind']:7} heading={meta['heading']!r}")
    print("-" * 70 + "\n")

    findings: list[tuple[bool, str, str]] = [
        (
            text.lstrip().startswith("#"),
            "heading styles became Markdown headings",
            "headings are bare text; every chunk will have an empty heading path",
        ),
        (
            any(chunk.metadata["heading"] for chunk in chunks),
            "heading path reaches chunk metadata",
            "no chunk carries a heading",
        ),
        (
            any(chunk.metadata["kind"] == "series" for chunk in chunks),
            "the numbered list was grouped as a series",
            "list items are loose prose and can be split mid-list",
        ),
        (
            any(chunk.metadata["kind"] == "table" for chunk in chunks),
            "the table was recognised as a unit",
            "table rows can be cut away from their header",
        ),
        (
            "\n\n" in text,
            "paragraphs are blank-line separated",
            "paragraphs run together; block boundaries are lost",
        ),
    ]

    failed = 0
    for ok, good, bad in findings:
        print(f"{'PASS' if ok else 'FAIL'}  {good if ok else bad}")
        failed += not ok

    if failed:
        print(
            "\nThe loader is not producing structured output. Paste the _load_docx body "
            "into src/documents.py (keeping your own _format_row) rather than delegating."
        )
    else:
        print("\nDOCX extraction is structured; the self-check WARN is a false negative.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
