"""Clean product data, made checkable: extract, validate, and write it for review (plan 026).

    python -m scripts.product_data extract <file>                      # its text, one located block per line
    python -m scripts.product_data check <batch.json> --root <dir> [--exclude <dir>]
    python -m scripts.product_data workbook <batch.json> <out.xlsx>
    python -m scripts.product_data factsheet <batch.json> <out.docx> [--draft]

The raw files the team sends are messy -- exported email threads, tickets,
filled and blank questionnaires -- so cleaning them takes judgement, and the
judgement is made by people and by agents reading the files. What this module
adds is the part that can be checked: every fact and every answer in a batch
cites a source file, a location and a verbatim quote, and `check` refuses a
batch whose quote is not in that file, which carries an email address or a
phone number, which states a dated status as a standing fact, or which draws on
a file the evaluation holds out.

Nothing here writes the knowledge base or the answer memory. The batch, the
review workbook and the fact sheet live beside the raw data, outside the
repository, because they are the team's confidential material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

TOPICS = (
    "Product and hosting",
    "Tenancy and data segregation",
    "Identity and access",
    "Logging and monitoring",
    "Testing and vulnerabilities",
    "Data protection",
    "Resilience",
    "Compliance and certifications",
    "Disclosure and evidence",
    "Support and operations",
)
"""The fact sheet's sections, in the order it prints them."""

Proposal = Literal["keep", "hold", "drop"]


class Source(BaseModel):
    file: str = Field(description="Path relative to the delivery's root")
    where: str = Field(description="A location label exactly as `extract` prints it")
    quote: str = Field(min_length=3, description="Verbatim text from that location, in its own language")


class Fact(BaseModel):
    id: str
    topic: str
    statement: str = Field(min_length=10, description="In English, neutral, about the product or T2")
    status: Literal["standing", "dated", "draft", "conflict"]
    as_of: str = Field(default="", description="YYYY-MM or YYYY-MM-DD; required unless standing")
    scope: Literal["product", "t2_wide"]
    confidence: Literal["high", "medium", "low"]
    sources: list[Source] = Field(min_length=1)
    note: str = ""
    proposed: Proposal


class Pair(BaseModel):
    id: str
    question: str = Field(min_length=5)
    answer: str = Field(min_length=2)
    language: Literal["en", "ar", "mixed"]
    question_rebuilt: bool = Field(description="True when the question was reconstructed rather than read")
    scope: Literal["product", "t2_wide"]
    sources: list[Source] = Field(min_length=1)
    note: str = ""
    proposed: Proposal


class Ask(BaseModel):
    id: str
    question: str
    why: Literal["gap", "conflict", "unconfirmed", "product"]
    detail: str = ""
    related: list[str] = []


class FileDecision(BaseModel):
    file: str
    decision: Literal["used", "already_held", "held_out", "duplicate", "discard", "elsewhere"]
    reason: str
    items: list[str] = []


class Batch(BaseModel):
    product: str
    prepared_on: str
    facts: list[Fact] = []
    pairs: list[Pair] = []
    asks: list[Ask] = []
    files: list[FileDecision] = []


# ---------------------------------------------------------------------------
# Extracting a file's text, with locations a quote can be checked against
# ---------------------------------------------------------------------------

EMPTY_ROWS_TO_STOP = 200
"""Consecutive empty rows after which a sheet is taken to have ended.

One delivered sheet is formatted down to a million rows; reading every empty
one took minutes and found nothing."""


def extract(path: Path) -> Iterator[tuple[str, str]]:
    """(location, text) for every non-empty paragraph, table cell or sheet cell, in reading order."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        yield from _docx_blocks(path)
    elif suffix in (".xlsx", ".xlsm"):
        yield from _xlsx_blocks(path)
    else:
        raise ValueError(f"{path.name}: only .docx and .xlsx files can be read")


def _docx_blocks(path: Path) -> Iterator[tuple[str, str]]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    paragraph = table = 0
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, document).text.strip()
            if text:
                paragraph += 1
                yield f"paragraph {paragraph}", text
        elif tag == "tbl":
            table += 1
            for r, row in enumerate(Table(child, document).rows, 1):
                previous = None
                for c, cell in enumerate(row.cells, 1):
                    text = cell.text.strip()
                    # A merged cell is returned once per grid column it spans.
                    if text and cell._tc is not previous:
                        yield f"table {table} row {r} cell {c}", text
                    previous = cell._tc


def _xlsx_blocks(path: Path) -> Iterator[tuple[str, str]]:
    import openpyxl
    from openpyxl.utils import get_column_letter

    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            empty = 0
            for r, row in enumerate(sheet.iter_rows(values_only=True), 1):
                cells = [(c, v) for c, v in enumerate(row, 1) if v is not None and str(v).strip()]
                if not cells:
                    empty += 1
                    if empty >= EMPTY_ROWS_TO_STOP:
                        break
                    continue
                empty = 0
                for c, value in cells:
                    yield f"{sheet.title}!{get_column_letter(c)}{r}", str(value).strip()
    finally:
        workbook.close()


_MARKS = re.compile(r"[ً-ْـ]")  # Arabic short vowels and tatweel: spelling, not words
_TOKEN = re.compile(r"[^\W_]+")


def tokens(text: str) -> str:
    """Words only, folded: what a quote and its source must share, whatever the punctuation and spacing."""
    folded = _MARKS.sub("", unicodedata.normalize("NFKC", text)).casefold()
    return " ".join(_TOKEN.findall(folded))


def quote_in(quote: str, text: str) -> bool:
    wanted = tokens(quote)
    return bool(wanted) and f" {wanted} " in f" {tokens(text)} "


# ---------------------------------------------------------------------------
# Validating a batch
# ---------------------------------------------------------------------------

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<![\w#])(?:\+|00)?\d(?:[\s-]?\d){8,13}(?![\w])")
DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _hashes(directories: Iterable[Path]) -> set[str]:
    return {hashlib.sha256(p.read_bytes()).hexdigest() for d in directories for p in d.rglob("*") if p.is_file()}


def check(batch: Batch, root: Path, exclude: Iterable[Path] = ()) -> list[str]:
    """Every reason this batch may not go to review. Empty when it may."""
    problems: list[str] = []
    ids = Counter(item.id for item in [*batch.facts, *batch.pairs, *batch.asks])
    problems += [f"{i}: the id is used {n} times" for i, n in ids.items() if n > 1]
    excluded = _hashes(exclude)
    texts: dict[str, list[tuple[str, str]] | None] = {}

    def blocks(file: str) -> list[tuple[str, str]] | None:
        if file not in texts:
            path = root / file
            texts[file] = list(extract(path)) if path.is_file() else None
        return texts[file]

    items: list[Fact | Pair] = [*batch.facts, *batch.pairs]
    for item in items:
        words = [item.statement] if isinstance(item, Fact) else [item.question, item.answer]
        words += [item.note, *(s.quote for s in item.sources)]
        for text in words:
            if EMAIL.search(text):
                problems.append(f"{item.id}: an email address is in the text")
            if PHONE.search(text):
                problems.append(f"{item.id}: a phone number is in the text")
        if isinstance(item, Fact):
            if item.topic not in TOPICS:
                problems.append(f"{item.id}: unknown topic {item.topic!r}")
            if item.status != "standing" and not DATE.match(item.as_of):
                problems.append(f"{item.id}: a {item.status} fact needs as_of (YYYY-MM or YYYY-MM-DD)")
            if item.proposed == "keep" and item.status != "standing":
                problems.append(f"{item.id}: only a standing fact may be proposed for keeping, not a {item.status} one")
        for source in item.sources:
            found = blocks(source.file)
            if found is None:
                problems.append(f"{item.id}: no file {source.file!r} under the root")
                continue
            if excluded and hashlib.sha256((root / source.file).read_bytes()).hexdigest() in excluded:
                problems.append(f"{item.id}: {source.file!r} is an excluded file (held or held out)")
            at = [text for where, text in found if where == source.where]
            if not at:
                problems.append(f"{item.id}: no location {source.where!r} in {source.file!r}")
            elif not quote_in(source.quote, at[0]):
                problems.append(f"{item.id}: the quote is not at {source.where!r} in {source.file!r}")
    known = {item.id for item in items}
    for ask in batch.asks:
        problems += [f"{ask.id}: refers to unknown item {r}" for r in ask.related if r not in known]
    return problems


# ---------------------------------------------------------------------------
# Writing it for review
# ---------------------------------------------------------------------------

READ_ME = [
    "How to review this batch",
    "",
    "Every row was extracted from the team's files and checked against its source by a second reader.",
    "Column 'Proposed' is the cleaner's suggestion: keep, hold (needs the team's confirmation) or drop.",
    "Write your decision in 'Decision' (keep, edit, drop) and anything else in 'Reviewer note'.",
    "To change wording, write the new text in 'Reviewer note' and set Decision to edit.",
    "",
    "Status of a fact: standing (true until changed), dated (true as of a date), draft (proposed, never",
    "confirmed as sent), conflict (another source says otherwise; see 'Questions for the team').",
    "Scope: product (about this product only) or t2_wide (a T2-wide position, for the shared batch).",
    "Sources: file, location and the exact words the item rests on.",
    "Only rows kept here reach the product's fact sheet and answer memory, and only when an import is asked for.",
]


def _sources(sources: list[Source]) -> str:
    return "\n\n".join(f"{s.file} @ {s.where}:\n“{s.quote}”" for s in sources)


def write_workbook(batch: Batch, out: Path) -> None:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    book = openpyxl.Workbook()
    readme = book.active
    readme.title = "Read me"
    readme.append([f"{batch.product}: clean data for review, prepared {batch.prepared_on}"])
    readme["A1"].font = Font(bold=True, size=14)
    for line in READ_ME:
        readme.append([line])
    counts = Counter(f.proposed for f in batch.facts) + Counter(p.proposed for p in batch.pairs)
    readme.append([""])
    readme.append(
        [
            f"{len(batch.facts)} facts, {len(batch.pairs)} pairs, {len(batch.asks)} questions, "
            f"{len(batch.files)} files. Proposed: {dict(counts)}"
        ]
    )
    readme.column_dimensions["A"].width = 120

    order = {topic: i for i, topic in enumerate(TOPICS)}
    sheets: list[tuple[str, list[str], list[list[str]], list[int]]] = [
        (
            "Facts",
            [
                "ID",
                "Topic",
                "Statement",
                "Status",
                "As of",
                "Scope",
                "Confidence",
                "Proposed",
                "Decision",
                "Reviewer note",
                "Cleaner's note",
                "Sources",
            ],
            [
                [
                    f.id,
                    f.topic,
                    f.statement,
                    f.status,
                    f.as_of,
                    f.scope,
                    f.confidence,
                    f.proposed,
                    "",
                    "",
                    f.note,
                    _sources(f.sources),
                ]
                for f in sorted(batch.facts, key=lambda f: (order.get(f.topic, 99), f.id))
            ],
            [8, 22, 60, 10, 10, 10, 11, 10, 10, 30, 40, 70],
        ),
        (
            "Q&A",
            [
                "ID",
                "Question",
                "Answer",
                "Language",
                "Question rebuilt",
                "Scope",
                "Proposed",
                "Decision",
                "Reviewer note",
                "Cleaner's note",
                "Sources",
            ],
            [
                [
                    p.id,
                    p.question,
                    p.answer,
                    p.language,
                    "yes" if p.question_rebuilt else "no",
                    p.scope,
                    p.proposed,
                    "",
                    "",
                    p.note,
                    _sources(p.sources),
                ]
                for p in batch.pairs
            ],
            [8, 45, 70, 9, 9, 10, 10, 10, 30, 40, 70],
        ),
        (
            "Questions for the team",
            ["ID", "Question", "Why", "Detail", "Related items", "Team's answer"],
            [[a.id, a.question, a.why, a.detail, ", ".join(a.related), ""] for a in batch.asks],
            [8, 60, 12, 70, 20, 50],
        ),
        (
            "Files",
            ["File", "What was done", "Why", "Items from it"],
            [[f.file, f.decision, f.reason, ", ".join(f.items)] for f in batch.files],
            [60, 14, 80, 30],
        ),
    ]
    header = PatternFill("solid", fgColor="1F3864")
    for title, columns, rows, widths in sheets:
        sheet = book.create_sheet(title)
        sheet.append(columns)
        for row in rows:
            sheet.append(row)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header
        for i, width in enumerate(widths, 1):
            sheet.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.freeze_panes = "B2"
        if "Decision" in columns:
            letter = openpyxl.utils.get_column_letter(columns.index("Decision") + 1)
            choice = DataValidation(type="list", formula1='"keep,edit,drop"', allow_blank=True)
            sheet.add_data_validation(choice)
            choice.add(f"{letter}2:{letter}{max(2, len(rows) + 1)}")
    book.save(str(out))


def write_fact_sheet(batch: Batch, out: Path, *, draft: bool = False) -> int:
    """The product's knowledge-base document: kept, standing, product facts by topic. Returns how many.

    Facts are cited by id only. A file name can carry a customer's name, and a
    drafter quoting its source would put that name in somebody else's answer.
    """
    import docx

    kept = [f for f in batch.facts if f.proposed == "keep" and f.status == "standing" and f.scope == "product"]
    document = docx.Document()
    document.add_heading(f"{batch.product}: security and operations facts", level=0)
    if draft:
        document.add_paragraph("DRAFT FOR REVIEW. Not yet confirmed by the team, and not indexed.")
    reviewed = "" if draft else " and reviewed by the team"
    document.add_paragraph(
        f"What T2 has stated about {batch.product}, compiled from the security team's correspondence and "
        f"questionnaires{reviewed} ({batch.prepared_on}). Where these facts and T2's general policies differ, "
        f"these describe {batch.product}."
    )
    for topic in TOPICS:
        facts = [f for f in kept if f.topic == topic]
        if facts:
            document.add_heading(topic, level=1)
            for fact in facts:
                document.add_paragraph(f"{fact.statement} [{fact.id}]", style="List Bullet")
    document.save(str(out))
    return len(kept)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="python -m scripts.product_data", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("extract")
    one.add_argument("file", type=Path)
    checking = commands.add_parser("check")
    checking.add_argument("batch", type=Path)
    checking.add_argument("--root", type=Path, required=True)
    checking.add_argument("--exclude", type=Path, action="append", default=[])
    book = commands.add_parser("workbook")
    book.add_argument("batch", type=Path)
    book.add_argument("out", type=Path)
    sheet = commands.add_parser("factsheet")
    sheet.add_argument("batch", type=Path)
    sheet.add_argument("out", type=Path)
    sheet.add_argument("--draft", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "extract":
        for where, text in extract(args.file):
            print(f"[{where}] {text}")
        return 0
    batch = Batch.model_validate(json.loads(args.batch.read_text(encoding="utf-8")))
    if args.command == "check":
        problems = check(batch, args.root, args.exclude)
        for problem in problems:
            print(f"PROBLEM {problem}")
        print(f"{len(batch.facts)} facts, {len(batch.pairs)} pairs: {len(problems)} problem(s)")
        return 1 if problems else 0
    if args.command == "workbook":
        write_workbook(batch, args.out)
        print(f"wrote {args.out}")
        return 0
    written = write_fact_sheet(batch, args.out, draft=args.draft)
    print(f"wrote {args.out}: {written} fact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
