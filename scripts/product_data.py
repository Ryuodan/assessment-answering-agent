"""Clean product data, made checkable: extract, validate, and write it for review (plan 026).

    python -m scripts.product_data extract <file>                      # its text, one located block per line
    python -m scripts.product_data check <batch.json> --root <dir> [--exclude <dir>]
    python -m scripts.product_data workbook <batch.json> <out.xlsx>
    python -m scripts.product_data factsheet <batch.json> <out.docx> [--draft]
    python -m scripts.product_data held <out.xlsx> <batch.json>... [--existing <entries.json>]
    python -m scripts.product_data contamination <batch.json>...       # needs `poe eval-unlock`
    python -m scripts.product_data typing <out.xlsx> <batch.json>...  # the kept answers, to type in

The raw files the team sends are messy -- exported email threads, tickets,
filled and blank questionnaires -- so cleaning them takes judgement, and the
judgement is made by people and by agents reading the files. What this module
adds is the part that can be checked: every fact and every answer in a batch
cites a source file, a location and a verbatim quote, and `check` refuses a
batch whose quote is not in that file, which carries an email address or a
phone number, which states a dated status as a standing fact, or which draws on
a file the evaluation holds out.

Nothing here writes the knowledge base or the answer memory. The batch, the
review workbook, the fact sheet and the typing sheet live beside the raw data,
outside the repository, because they are the team's confidential material.
They reach the app the way a person would bring them (plan 028): the fact sheet
uploaded into its knowledge base, and each kept answer typed in on the memory
page.
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
from typing import Any, Literal

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
    quote: str = Field(
        min_length=1, description="Verbatim text from that location, in its own language; a whole cell may be one word"
    )


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
    rewritten: bool = Field(
        default=False,
        description="True when the answer was reworded to stand on its own (an attachment reference removed); "
        "the sources hold T2's original words",
    )
    scope: Literal["product", "t2_wide"]
    sources: list[Source] = Field(min_length=1)
    note: str = ""
    proposed: Proposal


class Existing(BaseModel):
    """An entry already in the live answer memory, held for the team rather than moved (plan 026)."""

    entry_id: str
    product: str
    from_file: str
    question: str
    answer: str
    why: str


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


Column = tuple[str, int]
"""A sheet column: its header and its width."""

FACT_COLUMNS: list[Column] = [
    ("ID", 8), ("Topic", 22), ("Statement", 60), ("Status", 10), ("As of", 10), ("Scope", 10),
    ("Confidence", 11), ("Proposed", 10), ("Decision", 10), ("Reviewer note", 30), ("Cleaner's note", 40),
    ("Sources", 70),
]  # fmt: skip
PAIR_COLUMNS: list[Column] = [
    ("ID", 8), ("Question", 45), ("Answer", 70), ("Language", 9), ("Question rebuilt", 9),
    ("Answer rewritten", 9), ("Scope", 10), ("Proposed", 10), ("Decision", 10), ("Reviewer note", 30),
    ("Cleaner's note", 40), ("Sources", 70),
]  # fmt: skip
ASK_COLUMNS: list[Column] = [
    ("ID", 8), ("Question", 60), ("Why", 12), ("Detail", 70), ("Related items", 20), ("Team's answer", 50),
]  # fmt: skip


def _fact_row(f: Fact) -> list[str]:
    return [f.id, f.topic, f.statement, f.status, f.as_of, f.scope, f.confidence, f.proposed, "", "", f.note,
            _sources(f.sources)]  # fmt: skip


def _pair_row(p: Pair) -> list[str]:
    yes = {True: "yes", False: "no"}
    return [p.id, p.question, p.answer, p.language, yes[p.question_rebuilt], yes[p.rewritten], p.scope,
            p.proposed, "", "", p.note, _sources(p.sources)]  # fmt: skip


def _ask_row(a: Ask) -> list[str]:
    return [a.id, a.question, a.why, a.detail, ", ".join(a.related), ""]


def _by_topic(facts: list[Fact]) -> list[Fact]:
    order = {topic: i for i, topic in enumerate(TOPICS)}
    return sorted(facts, key=lambda f: (order.get(f.topic, 99), f.id))


def _book(title: str, read_me: list[str]) -> Any:
    import openpyxl
    from openpyxl.styles import Font

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Read me"
    sheet.append([title])
    sheet["A1"].font = Font(bold=True, size=14)
    for line in read_me:
        sheet.append([line])
    sheet.column_dimensions["A"].width = 120
    return book


def _add_sheet(book: Any, title: str, columns: list[Column], rows: list[list[str]]) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    sheet = book.create_sheet(title)
    headers = [name for name, _ in columns]
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
    for i, (_, width) in enumerate(columns, 1):
        sheet.column_dimensions[get_column_letter(i)].width = width
    for line in sheet.iter_rows(min_row=2):
        for cell in line:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "B2"
    if "Decision" in headers:
        letter = get_column_letter(headers.index("Decision") + 1)
        choice = DataValidation(type="list", formula1='"keep,edit,drop"', allow_blank=True)
        sheet.add_data_validation(choice)
        choice.add(f"{letter}2:{letter}{max(2, len(rows) + 1)}")


def write_workbook(batch: Batch, out: Path) -> None:
    """One batch for review: facts, pairs, questions for the team, and what was done with each file."""
    counts = Counter(f.proposed for f in batch.facts) + Counter(p.proposed for p in batch.pairs)
    totals = (
        f"{len(batch.facts)} facts, {len(batch.pairs)} pairs, {len(batch.asks)} questions, "
        f"{len(batch.files)} files. Proposed: {dict(counts)}"
    )
    book = _book(f"{batch.product}: clean data for review, prepared {batch.prepared_on}", [*READ_ME, "", totals])
    _add_sheet(book, "Facts", FACT_COLUMNS, [_fact_row(f) for f in _by_topic(batch.facts)])
    _add_sheet(book, "Q&A", PAIR_COLUMNS, [_pair_row(p) for p in batch.pairs])
    _add_sheet(book, "Questions for the team", ASK_COLUMNS, [_ask_row(a) for a in batch.asks])
    files = [[f.file, f.decision, f.reason, ", ".join(f.items)] for f in batch.files]
    _add_sheet(book, "Files", [("File", 60), ("What was done", 14), ("Why", 80), ("Items from it", 30)], files)
    book.save(str(out))


HELD_READ_ME = [
    "What is held, across every product, until the team can review it",
    "",
    "The team could not review anything when the data was cleaned, so only items with no conflict, no open",
    "gap and no draft status were proposed for use. Everything else is collected here: held facts and answers,",
    "the questions that would settle them, and entries already in the live shared memory that were neither kept",
    "as they are nor moved, with the reason. Write the team's answer in the last column; an answered row can",
    "then be kept, corrected or dropped in its product's batch.",
]


def owns(batch: Batch, item: Fact | Pair) -> bool:
    """Whether this batch is where the item is used: a product's own items, or the shared batch's T2-wide ones.

    A product batch also extracts the T2-wide items it finds, and the shared
    batch merges them all, so taking them from both would count them twice.
    """
    return batch.product == SHARED or item.scope == "product"


def write_held(batches: list[Batch], out: Path, existing: list[Existing] | None = None) -> int:
    """Every held item from every batch, in one workbook for the team. Returns how many rows."""
    product = [("Product", 12)]
    facts = [
        [b.product, *_fact_row(f)] for b in batches for f in _by_topic(b.facts) if f.proposed == "hold" and owns(b, f)
    ]
    pairs = [[b.product, *_pair_row(p)] for b in batches for p in b.pairs if p.proposed == "hold" and owns(b, p)]
    asks = [[b.product, *_ask_row(a)] for b in batches for a in b.asks]
    rows = [[e.product, e.entry_id, e.from_file, e.question, e.answer, e.why, ""] for e in existing or []]
    book = _book("Held for the team's review", HELD_READ_ME)
    _add_sheet(book, "Held facts", product + FACT_COLUMNS, facts)
    _add_sheet(book, "Held answers", product + PAIR_COLUMNS, pairs)
    _add_sheet(book, "Questions for the team", product + ASK_COLUMNS, asks)
    memory_columns = [("Entry", 10), ("From questionnaire", 40), ("Question", 50), ("Answer", 60), ("Why held", 50),
                      ("Team's answer", 40)]  # fmt: skip
    _add_sheet(book, "Existing memory entries", product + memory_columns, rows)
    book.save(str(out))
    return len(facts) + len(pairs) + len(asks) + len(rows)


SHARED = "Shared"
"""The batch of T2-wide items, for the shared knowledge base and memory rather than one product's."""


def write_fact_sheet(batch: Batch, out: Path, *, draft: bool = False) -> int:
    """The knowledge-base document: kept, standing facts by topic. Returns how many.

    A product's sheet holds its product facts; the shared batch's holds the
    T2-wide ones. No source file is named: a file name can carry a customer's
    name, and a drafter quoting its source would put that name in somebody
    else's answer. A draft, for review, carries a banner and each fact's id.
    The final sheet, the one uploaded, carries neither, so an id never reaches
    an answer; the batch keeps the ids for tracing a fact back. Neither claims
    a team review, which has not happened (plan 028). A batch with no kept
    facts gets no sheet, because an empty document in a knowledge base reads as
    if it said something.
    """
    import docx

    shared = batch.product == SHARED
    kept = kept_facts(batch)
    if not kept:
        raise ValueError(f"{batch.product} has no kept standing facts, so it gets no fact sheet")
    document = docx.Document()
    subject = "T2" if shared else batch.product
    document.add_heading(f"{subject}: security and operations facts", level=0)
    if draft:
        document.add_paragraph("DRAFT FOR REVIEW. Not yet confirmed by the team, and not indexed.")
    compiled = f"compiled from the security team's correspondence and questionnaires ({batch.prepared_on})"
    document.add_paragraph(
        f"What T2 has stated about itself, whatever the product, {compiled}."
        if shared
        else f"What T2 has stated about {batch.product}, {compiled}. Where these facts and T2's general policies "
        f"differ, these describe {batch.product}."
    )
    for topic in TOPICS:
        facts = [f for f in kept if f.topic == topic]
        if facts:
            document.add_heading(topic, level=1)
            for fact in facts:
                document.add_paragraph(
                    f"{fact.statement} [{fact.id}]" if draft else fact.statement, style="List Bullet"
                )
    document.save(str(out))
    return len(kept)


def kept_facts(batch: Batch) -> list[Fact]:
    """The facts this batch's sheet states: kept, standing, and of the batch's own scope."""
    scope = "t2_wide" if batch.product == SHARED else "product"
    return [f for f in batch.facts if f.proposed == "keep" and f.status == "standing" and f.scope == scope]


def kept_pairs(batch: Batch) -> list[Pair]:
    """The pairs this batch puts into its memory: kept, and counted here rather than in another batch."""
    return [p for p in batch.pairs if p.proposed == "keep" and owns(batch, p)]


def contamination(batches: list[Batch], cases: list[Any]) -> list[Any]:
    """Every evaluation case whose question or reference answer the import would show the system.

    The house set measures answers to questionnaires the system has never seen
    (docs/measurements/evaluation.md). Importing a fact or a pair that repeats
    one of its questions or reference answers would hand the system the answer
    key, so each kept item is checked as eval/contamination.py checks src/ and
    the memory: a run of words in common, or the same question normalised.
    The leaks name case ids and item ids only.
    """
    from eval.contamination import in_memory, in_sources

    texts = {f"{b.product}:{f.id}": f.statement for b in batches for f in kept_facts(b)}
    texts |= {f"{b.product}:{p.id}": f"{p.question}\n{p.answer}" for b in batches for p in kept_pairs(b)}
    items = [(c.test_id, c.question) for c in cases] + [(c.test_id + ":reference", c.answer) for c in cases]
    remembered = [p.question for b in batches for p in kept_pairs(b)]
    return in_sources(items, texts) + in_memory([(c.test_id, c.question) for c in cases], remembered)


TYPING_READ_ME = [
    "How to add these answers, one memory at a time",
    "",
    "Each sheet after this one is one answer memory: a product's, or Shared. For every row:",
    "  1. On the Answer memory page, choose that memory (the product, or Shared) in the selector.",
    "  2. Press Add an answer, paste the Question and the Answer exactly as they are here, and save.",
    "  3. Put an x in the Added column, so a second person can see what is done.",
    "An answer added by hand is dated today. If the memory already holds an answer to the same question, the",
    "conflict check treats the new one as the later word and the older one as superseded.",
    "These are only the kept answers. Held ones are in 'Held for the team's review.xlsx' and must not be added.",
]


def write_typing_sheet(batches: list[Batch], out: Path) -> int:
    """The kept answers to type into the app, one sheet per memory, with nothing else. Returns how many.

    The user chose to add them by hand (plan 028). The sheet carries no
    sources and no cleaner's notes: those name customers' questionnaires, and
    this sheet is meant to be handed around.
    """
    book = _book("Kept answers to add to the answer memories", TYPING_READ_ME)
    columns: list[Column] = [("#", 5), ("Question", 60), ("Answer", 80), ("Language", 10), ("Item", 9), ("Added", 8)]
    total = 0
    for b in batches:
        pairs = kept_pairs(b)
        if pairs:
            rows = [[str(n), p.question, p.answer, p.language, p.id, ""] for n, p in enumerate(pairs, 1)]
            _add_sheet(book, b.product, columns, rows)
            total += len(pairs)
    book.save(str(out))
    return total


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
    held = commands.add_parser("held")
    held.add_argument("out", type=Path)
    held.add_argument("batches", type=Path, nargs="+")
    held.add_argument("--existing", type=Path, help="JSON list of live memory entries held for the team")
    leaks = commands.add_parser("contamination")
    leaks.add_argument("batches", type=Path, nargs="+")
    typing = commands.add_parser("typing")
    typing.add_argument("out", type=Path)
    typing.add_argument("batches", type=Path, nargs="+")
    args = parser.parse_args(argv)

    if args.command == "extract":
        for where, text in extract(args.file):
            print(f"[{where}] {text}")
        return 0
    if args.command == "held":
        batches = [Batch.model_validate(json.loads(b.read_text(encoding="utf-8"))) for b in args.batches]
        existing = (
            [Existing.model_validate(e) for e in json.loads(args.existing.read_text(encoding="utf-8"))]
            if args.existing
            else []
        )
        rows = write_held(batches, args.out, existing)
        print(f"wrote {args.out}: {rows} row(s) from {len(batches)} batch(es)")
        return 0
    if args.command in ("contamination", "typing"):
        batches = [Batch.model_validate(json.loads(b.read_text(encoding="utf-8"))) for b in args.batches]
        if args.command == "typing":
            print(f"wrote {args.out}: {write_typing_sheet(batches, args.out)} answer(s)")
            return 0
        from eval.house import load_house_set

        cases = load_house_set()
        found = contamination(batches, cases)
        for leak in found:
            print(f"LEAK {leak.item} in {leak.where}")
        kept = sum(len(kept_facts(b)) + len(kept_pairs(b)) for b in batches)
        print(f"contamination: {len(cases)} house-set cases against {kept} kept item(s): {len(found)} leak(s)")
        return 1 if found else 0
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
    try:
        written = write_fact_sheet(batch, args.out, draft=args.draft)
    except ValueError as refused:
        print(f"not written: {refused}")
        return 1
    print(f"wrote {args.out}: {written} fact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
