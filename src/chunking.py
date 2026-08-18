"""Structure-aware chunking for policy and standards documents.

The default `RecursiveCharacterTextSplitter` is blind to document structure: it
cuts tables mid-body (orphaning rows from their header) and cuts numbered series
mid-run (orphaning items from the stem that introduces them). Both fragments are
then semantically weak and lose the top-k race

This module parses the Markdown that Docling emits (and the `[table]`-marked
text the local loaders emit) into structural *units*, then packs units into
chunks under three rules:

1. A table is never split from its header row. If a table must be split, the
   header row is repeated on every part.
2. A run of sibling clauses (`7.2.1` … `7.2.12`) is one unit. If it must be
   split, the introducing stem is repeated on every part.
3. Every part of a split unit carries the same `unit_id`, `part` and `parts`,
   so the retriever can recover the whole unit from any one hit and the
   confidence step can tell that it is holding a fragment.

Clause identifiers, heading path, document id and page number are parsed here
and carried in metadata, which is what makes clause-level citations possible
downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- line-level patterns ---------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_TABLE_OPEN = "[table]"
_TABLE_CLOSE = "[/table]"
_PAGE = re.compile(r"^-{2,}\s*page\s+(\d+)\s*-{2,}$", re.IGNORECASE)

# A clause is either multi-level ("7.2.1", "12.3.4") or single-level with
# punctuation ("7.", "7)", "7-"). Requiring one or the other keeps a sentence
# that merely opens with a year — "2024 saw the rollout" — from being read as
# clause 2024, which a bare `\d+` pattern would do.
#
# `\d` is Unicode-aware in Python, so Arabic-Indic digits ("\u0667.\u0662.\u0661")
# match here and are folded to ASCII by `_clause_of`.
_CLAUSE = re.compile(r"^\s*(?:[-*\u2022]\s+)?(\d+(?:[.\u066b]\d+){1,5}|\d+[.)\-])\s+(?=\S)")

# An unnumbered list item. DOCX numbered lists carry their number in the
# numbering XML rather than in the paragraph text, so python-docx returns them
# unnumbered; grouping bullets as a series is what keeps those lists intact.
_BULLET = re.compile(r"^\s*[-*\u2022\u25cf\u25aa]\s+(?=\S)")

# Matches MDS-CS-STD-003, ISO-IEC-27001 and similar corpus document ids.
_DOC_ID = re.compile(r"\b([A-Z]{2,5}(?:-[A-Z]{2,5}){1,3}-\d{2,4})\b")

# Bidi control characters. Word and some PDF producers emit RLM/LRM around
# Arabic runs; an RLM is not whitespace, so a leading one defeats every `^\s*`
# anchor in this module and silently disables clause detection for Arabic.
_BIDI_CONTROLS = dict.fromkeys(
    [0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
     0x2066, 0x2067, 0x2068, 0x2069],
    None,
)

# Arabic-Indic (U+0660) and Extended Arabic-Indic (U+06F0) digits -> ASCII.
_DIGIT_FOLD = {0x0660 + n: str(n) for n in range(10)}
_DIGIT_FOLD.update({0x06F0 + n: str(n) for n in range(10)})


def strip_bidi(text: str) -> str:
    """Remove bidi control characters, which break line-anchored patterns."""
    return text.translate(_BIDI_CONTROLS)


def _clause_of(raw: str) -> str:
    """Normalise a clause token to a comparable ASCII key.

    '7.2.1', '7.', '7)' and '\u0667.\u0662.\u0661' all reduce to a form that
    compares and groups correctly, so an Arabic document and its English
    counterpart produce the same clause identifiers.
    """
    folded = raw.translate(_DIGIT_FOLD).replace("\u066b", ".")
    return folded.rstrip(".)-")


def parent_clause(clause: str | None) -> str:
    """'7.2.1' -> '7.2'; '7.2' -> '7'; '7' -> ''. Used to group sibling clauses."""
    if not clause:
        return ""
    head, _, _ = clause.rpartition(".")
    return head


# --- parsing ---------------------------------------------------------------


@dataclass
class Block:
    """One structural element of the document."""

    kind: str  # "heading" | "table" | "clause" | "text"
    lines: list[str]
    heading: str | None = None
    clause: str | None = None
    page: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def parse_blocks(text: str) -> list[Block]:
    """Walk the document once, emitting structural blocks in reading order."""
    lines = strip_bidi(text).splitlines()
    total = len(lines)
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []
    page: int | None = None

    pending: list[str] = []
    pending_clause: str | None = None

    def heading_path() -> str | None:
        return " > ".join(title for _, title in stack) or None

    def flush() -> None:
        nonlocal pending, pending_clause
        if any(line.strip() for line in pending):
            blocks.append(
                Block(
                    kind="clause" if pending_clause else "text",
                    lines=list(pending),
                    heading=heading_path(),
                    clause=pending_clause,
                    page=page,
                )
            )
        pending = []
        pending_clause = None

    index = 0
    while index < total:
        line = lines[index]
        stripped = line.strip()

        page_match = _PAGE.match(stripped)
        if page_match:
            flush()
            page = int(page_match.group(1))
            index += 1
            continue

        heading_match = _HEADING.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            numbered = re.match(r"^(\d+(?:[.\u066b]\d+)*)\s+", title)
            blocks.append(
                Block(
                    "heading",
                    [line],
                    heading_path(),
                    _clause_of(numbered.group(1)) if numbered else None,
                    page,
                )
            )
            index += 1
            continue

        if stripped == _TABLE_OPEN:
            flush()
            cursor = index + 1
            body: list[str] = []
            while cursor < total and lines[cursor].strip() != _TABLE_CLOSE:
                body.append(lines[cursor])
                cursor += 1
            if body:
                blocks.append(Block("table", body, heading_path(), None, page))
            index = cursor + 1
            continue

        if _TABLE_ROW.match(line):
            flush()
            cursor = index
            body = []
            while cursor < total and _TABLE_ROW.match(lines[cursor]):
                body.append(lines[cursor])
                cursor += 1
            blocks.append(Block("table", body, heading_path(), None, page))
            index = cursor
            continue

        clause_match = _CLAUSE.match(line)
        if clause_match:
            flush()
            pending = [line]
            pending_clause = _clause_of(clause_match.group(1))
            index += 1
            # Absorb continuation lines that belong to this clause.
            while index < total:
                nxt = lines[index]
                if not nxt.strip():
                    break
                if _CLAUSE.match(nxt) or _HEADING.match(nxt) or _TABLE_ROW.match(nxt):
                    break
                if nxt.strip() in (_TABLE_OPEN, _TABLE_CLOSE):
                    break
                pending.append(nxt)
                index += 1
            flush()
            continue

        if _BULLET.match(line):
            flush()
            item = [line]
            index += 1
            while index < total:
                nxt = lines[index]
                if not nxt.strip() or _BULLET.match(nxt) or _CLAUSE.match(nxt):
                    break
                if _HEADING.match(nxt) or _TABLE_ROW.match(nxt):
                    break
                if nxt.strip() in (_TABLE_OPEN, _TABLE_CLOSE):
                    break
                item.append(nxt)
                index += 1
            blocks.append(Block("listitem", item, heading_path(), None, page))
            continue

        pending.append(line)
        index += 1

    flush()
    return blocks


# --- units -----------------------------------------------------------------


@dataclass
class Unit:
    """A block, or a run of blocks, that must not be split without a repeated stem."""

    kind: str  # "table" | "series" | "prose"
    blocks: list[Block] = field(default_factory=list)
    stem: str = ""
    """Header row(s) or introducing sentence, repeated on every part of a split unit."""

    @property
    def heading(self) -> str | None:
        return self.blocks[0].heading if self.blocks else None

    @property
    def clause(self) -> str | None:
        for block in self.blocks:
            if block.clause:
                return block.clause
        return None

    @property
    def page(self) -> int | None:
        for block in self.blocks:
            if block.page is not None:
                return block.page
        return None

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text).strip()


def _table_stem(block: Block) -> str:
    """The header row, plus the separator row when the table is Markdown."""
    rows = [line for line in block.lines if line.strip()]
    if not rows:
        return ""
    if len(rows) > 1 and _TABLE_SEP.match(rows[1]):
        return "\n".join(rows[:2])
    return rows[0]


def build_units(blocks: list[Block]) -> list[Unit]:
    """Group blocks into units, merging sibling clauses into a single series."""
    units: list[Unit] = []
    index = 0
    last_prose = ""

    while index < len(blocks):
        block = blocks[index]

        if block.kind == "table":
            units.append(Unit("table", [block], _table_stem(block)))
            index += 1
            continue

        if block.kind == "listitem":
            run = [block]
            cursor = index + 1
            while cursor < len(blocks) and blocks[cursor].kind == "listitem":
                run.append(blocks[cursor])
                cursor += 1
            units.append(Unit("series", run, last_prose))
            index = cursor
            continue

        if block.kind == "clause":
            parent = parent_clause(block.clause)
            run = [block]
            cursor = index + 1
            while cursor < len(blocks):
                candidate = blocks[cursor]
                # A bullet nested inside a numbered clause belongs to that clause.
                if candidate.kind == "listitem":
                    run.append(candidate)
                    cursor += 1
                    continue
                if candidate.kind != "clause" or parent_clause(candidate.clause) != parent:
                    break
                run.append(candidate)
                cursor += 1
            # The stem is whatever prose introduced the series ("...the following
            # conditions:"). Without it, part 2 of a split series is a bare list.
            units.append(Unit("series", run, last_prose))
            index = cursor
            continue

        units.append(Unit("prose", [block], ""))
        if block.text:
            last_prose = block.text.splitlines()[-1].strip()
        index += 1

    return units


# --- chunking --------------------------------------------------------------


@dataclass
class Chunk:
    text: str
    metadata: dict


def _split_unit(unit: Unit, chunk_size: int) -> list[str]:
    """Split one oversized unit into parts, repeating the stem on each."""
    if unit.kind == "table":
        rows = [line for line in unit.blocks[0].lines if line.strip()]
        stem_rows = unit.stem.splitlines()
        body = rows[len(stem_rows):]
        pieces, current = [], []
        budget = chunk_size - len(unit.stem) - 2
        length = 0
        for row in body:
            if current and length + len(row) + 1 > budget:
                pieces.append("\n".join(stem_rows + current))
                current, length = [], 0
            current.append(row)
            length += len(row) + 1
        if current:
            pieces.append("\n".join(stem_rows + current))
        return pieces or [unit.text]

    if unit.kind == "series":
        prefix = f"{unit.stem}\n" if unit.stem else ""
        pieces, current = [], []
        budget = chunk_size - len(prefix)
        length = 0
        for block in unit.blocks:
            body = block.text
            if current and length + len(body) + 1 > budget:
                pieces.append(prefix + "\n".join(current))
                current, length = [], 0
            current.append(body)
            length += len(body) + 1
        if current:
            pieces.append(prefix + "\n".join(current))
        return pieces or [unit.text]

    # Prose: fall back to sentence/paragraph-boundary splitting.
    text = unit.text
    pieces, current, length = [], [], 0
    for sentence in re.split(r"(?<=[.!?\u061f\u06d4])\s+", text):
        if current and length + len(sentence) + 1 > chunk_size:
            pieces.append(" ".join(current))
            current, length = [], 0
        current.append(sentence)
        length += len(sentence) + 1
    if current:
        pieces.append(" ".join(current))
    return pieces or [text]


def chunk_document(text: str, *, source_name: str = "", chunk_size: int = 1800) -> list[Chunk]:
    """Chunk a document into structure-respecting pieces with citation metadata.

    `chunk_size` is a soft ceiling for prose. A table or clause series that
    exceeds it is split into parts sharing a `unit_id`, never silently truncated.
    """
    blocks = parse_blocks(text)
    units = build_units(blocks)
    doc_id_match = _DOC_ID.search(text[:4000]) or _DOC_ID.search(source_name)
    doc_id = doc_id_match.group(1) if doc_id_match else ""

    chunks: list[Chunk] = []
    pending: list[Unit] = []
    pending_length = 0

    def emit_pending() -> None:
        nonlocal pending, pending_length
        if not pending:
            return
        body = "\n\n".join(unit.text for unit in pending if unit.text)
        if body.strip():
            head = pending[0]
            chunks.append(
                Chunk(
                    text=body,
                    metadata=_metadata(head, doc_id, unit_id="", part=1, parts=1),
                )
            )
        pending = []
        pending_length = 0

    for position, unit in enumerate(units):
        body = unit.text
        if not body:
            continue

        if len(body) > chunk_size:
            emit_pending()
            parts = _split_unit(unit, chunk_size)
            unit_id = f"{doc_id or source_name}:u{position}"
            for part_index, part in enumerate(parts, start=1):
                chunks.append(
                    Chunk(
                        text=part,
                        metadata=_metadata(
                            unit, doc_id, unit_id=unit_id, part=part_index, parts=len(parts)
                        ),
                    )
                )
            continue

        # A table or series that fits stays whole and is not merged with
        # neighbours, so a retrieval hit on it returns exactly the series.
        if unit.kind in ("table", "series"):
            emit_pending()
            chunks.append(
                Chunk(text=body, metadata=_metadata(unit, doc_id, unit_id="", part=1, parts=1))
            )
            continue

        if pending_length + len(body) > chunk_size:
            emit_pending()
        pending.append(unit)
        pending_length += len(body) + 2

    emit_pending()

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk"] = index
        chunk.metadata["source_name"] = source_name
    return chunks


def _metadata(unit: Unit, doc_id: str, *, unit_id: str, part: int, parts: int) -> dict:
    clause = unit.clause or ""
    return {
        "doc_id": doc_id,
        "clause": clause,
        "parent_clause": parent_clause(clause),
        "heading": unit.heading or "",
        "page": unit.page if unit.page is not None else -1,
        "kind": unit.kind,
        "unit_id": unit_id,
        "part": part,
        "parts": parts,
    }