"""Structure-aware chunking for policy, standards and regulatory documents.

A character-counting splitter cuts tables away from their headers and numbered
series away from the sentence that introduces them, leaving fragments that are
semantically weak and lose the retrieval race. This module chunks along the
document's own structure instead.

The unit model
--------------
The organising idea is the *unit*: a span of the document that should be
retrieved together. A unit is a **section** — a heading plus everything under it
until the next heading of the same or shallower level — chosen adaptively:

- A section that fits within the ceiling becomes one unit, so a stem clause
  ("7.2 The following shall generate an alert:") stays with the items it
  introduces ("7.2.1 ... 7.2.12"), and sibling clauses stay with each other.
- A section too large to be one unit is subdivided into its child sections, and
  the test is applied again. Depth is chosen by size, not by a fixed level.
- A document with no headings is sectioned by its top-level clause numbers
  instead; one with neither is a single unit split by size.

An earlier version grouped clauses by shared `parent_clause`. That put "7.2" in
the same group as "7.1" while "7.2.1"-"7.2.12" formed a separate one, so the
sentence introducing a list could never be retrieved with the list. Sections fix
this because a stem and its children are always in the same section.

Every unit gets a `unit_id`, and every chunk records `part`/`parts`, so a hit on
any part can recover the rest. Chunks record the *range* of clauses they cover
(`clause_start`..`clause_end`): a chunk spanning 5.1-5.6 but labelled "5.1"
produces citations that look precise and are not.

Numbering
---------
Documents number things in many ways, so the parser accepts decimal clauses
(7.2.1), single-level with punctuation (7. / 7)), bold-wrapped numbers
(**7.2.1**, which Markdown converters emit for bold runs), keyword-prefixed
clauses (Article 7, Section 7.2, §7.2, البند ٧), Arabic-Indic digits, and
letter/roman list markers ((a), (iv), iii.). Only decimal forms carry hierarchy;
the rest are list items belonging to the enclosing clause.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- text normalisation ----------------------------------------------------

# Bidi controls. Word and some PDF producers emit RLM/LRM around Arabic runs; an
# RLM is not whitespace, so a leading one defeats every `^\s*` anchor here and
# silently disables clause detection for Arabic while English keeps working.
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


def fold_digits(text: str) -> str:
    """Fold Arabic-Indic digits to ASCII so clause keys compare across languages."""
    return text.translate(_DIGIT_FOLD)


# --- line patterns ---------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_TABLE_OPEN = "[table]"
_TABLE_CLOSE = "[/table]"
_PAGE = re.compile(r"^-{2,}\s*page\s+(\d+)\s*-{2,}$", re.IGNORECASE)

_EMPHASIS = r"(?:\*\*|__|\*|_)"
# Words that introduce a clause number in legal and regulatory drafting. With one
# of these present, a bare single-level number is unambiguous.
_CLAUSE_WORD = (
    r"(?:article|section|clause|rule|paragraph|item|control|"
    r"req(?:uirement)?|المادة|البند|القسم|الفقرة|الضابط)"
)
_NUMBER = r"\d+(?:[.\u066b]\d+){0,7}"

# Three ways a line can open with a clause identifier.
_CLAUSE_PATTERNS = (
    # Multi-level: "7.2.1", "**7.2.1**", "7.2.1)" — unambiguous on its own.
    re.compile(
        rf"^\s*(?:[-*\u2022]\s+)?{_EMPHASIS}?(\d+(?:[.\u066b]\d+){{1,7}}){_EMPHASIS}?[.)\-\u2013]?\s+(?=\S)"
    ),
    # Keyword- or section-sign-prefixed: "Article 7", "§7.2", "البند ٧".
    re.compile(
        rf"^\s*(?:[-*\u2022]\s+)?{_EMPHASIS}?(?:{_CLAUSE_WORD}\s+|\u00a7\s*){_EMPHASIS}?({_NUMBER})"
        rf"{_EMPHASIS}?[.)\-\u2013:]?\s*(?=\S|$)",
        re.IGNORECASE,
    ),
    # Single-level with mandatory punctuation: "7." / "7)". The punctuation is
    # what distinguishes a clause from a sentence opening with a year or a count.
    re.compile(rf"^\s*(?:[-*\u2022]\s+)?{_EMPHASIS}?(\d+){_EMPHASIS}?[.)\u2013]\s+(?=\S)"),
)

# Letter and roman-numeral list markers: "(a)", "a.", "(iv)", "iii)", and the
# Arabic abjad sequence "أ)", "ب)", "(ج)", "هـ)" used the same way. These order
# items but carry no hierarchy, so they are list items rather than clauses.
_ABJAD = r"(?:\u0623|\u0628|\u062c|\u062f|\u0647\u0640|\u0647|\u0648|\u0632|\u062d|\u0637|\u064a|\u0643|\u0644|\u0645|\u0646)"
_ALPHA_ITEM = re.compile(
    r"^\s*(?:"
    rf"\(\s*(?:[a-z]{{1,2}}|[ivxlc]{{1,6}}|{_ABJAD})\s*\)"
    rf"|(?:[a-z]|[ivxlc]{{1,6}}|{_ABJAD})[.)\u2013]"
    r")\s+(?=\S)",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*[-*\u2022\u25cf\u25aa]\s+(?=\S)")

# A clause number stranded at the end of a line. Some PDF text layers store
# Arabic runs in visual order, so "٥٫١ يجب أن..." is extracted with the number
# last. Used only when the document as a whole shows this pattern — see
# `_uses_trailing_clauses` — because "الإصدار ٤٫٢" would otherwise be read as
# clause 4.2 in a perfectly well-formed document.
_TRAILING_CLAUSE = re.compile(r"(\d+(?:[.\u066b]\d+){1,7})\s*$")

_ARABIC = re.compile(r"[\u0621-\u064a]")

# Document identifiers: MDS-CS-STD-003, ACS-POL-001, ISO-IEC-27001.
_DOC_ID = re.compile(r"\b([A-Z]{2,6}(?:-[A-Z]{2,6}){1,3}-\d{2,5})\b")


# A control identifier in the first cell of a table row: "| 1-1-1 | The entity
# shall ...". Three groups minimum, because two would also match a year range
# or a page span, and this has to be safe on eighty documents it was not
# designed against. Nothing else in this corpus is shaped like it.
_ROW_CONTROL_ID = re.compile(r"^\s*\|\s*(?:\*\*|__)?\s*(\d+(?:-\d+){2,5})\s*(?:\*\*|__)?\s*\|")


def row_control_id(line: str) -> str | None:
    """The control identifier a table row opens with, if it has one."""
    found = _ROW_CONTROL_ID.match(fold_digits(line))
    return found.group(1) if found else None


def _table_clause_range(lines: list[str]) -> tuple[str, str]:
    """First and last control identifier among a table's rows."""
    found = [control for control in (row_control_id(line) for line in lines) if control]
    return clause_range(found) if found else ("", "")


def _uses_trailing_clauses(lines: list[str]) -> bool:
    """Whether this document looks like RTL text extracted in visual order.

    Decided per document rather than per line: a single line ending in a version
    number proves nothing, but a run of Arabic lines that all end in a clause
    number and none that start with one is unambiguous.
    """
    leading = trailing = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or _HEADING.match(line) or _TABLE_ROW.match(line):
            continue
        folded = fold_digits(stripped)
        if any(pattern.match(folded) for pattern in _CLAUSE_PATTERNS):
            leading += 1
        elif _ARABIC.search(stripped) and _TRAILING_CLAUSE.search(folded):
            trailing += 1
    return trailing >= 3 and trailing > leading * 2


def match_clause(line: str, *, trailing: bool = False) -> str | None:
    """Return the normalised clause identifier a line carries, if any.

    With `trailing=True` the identifier is also accepted at the end of the line,
    for Arabic extracted in visual rather than logical order.
    """
    folded = fold_digits(line)
    for pattern in _CLAUSE_PATTERNS:
        found = pattern.match(folded)
        if found:
            return found.group(1).replace("\u066b", ".").rstrip(".)-\u2013")
    if trailing and _ARABIC.search(line):
        found = _TRAILING_CLAUSE.search(folded)
        if found:
            return found.group(1).replace("\u066b", ".")
    return None


# A heading's leading number is unambiguous in a way a sentence's is not: a
# heading is never a sentence opening with a year, so no trailing punctuation is
# required to tell "9 Data protection" from "2024 was a busy year".
_HEADING_NUMBER = re.compile(rf"^\s*{_EMPHASIS}?({_NUMBER}){_EMPHASIS}?[.)\-\u2013:]?\s+(?=\S)")


def match_heading_clause(title: str) -> str | None:
    """Return the section number a heading carries, if any."""
    folded = fold_digits(_strip_emphasis(title))
    found = _HEADING_NUMBER.match(folded)
    if found:
        return found.group(1).replace("\u066b", ".").rstrip(".)-\u2013")
    return match_clause(title + " x")


# Two numbering conventions live in this corpus and both have to be read.
# T2's own policies number clauses with dots — 3.4.1. The NCA and SDAIA
# publications number controls with dashes — 1-1-1 — and the largest document
# here, the ECC implementation guide, uses nothing else: 352 dashed control
# ids and not one dotted clause. Recognising only dots left all 840 of its
# chunks with no clause at all, so its citations gave a file name and no
# reference, and the check that a named clause is actually supported could
# not evaluate a single one of them.
_CLAUSE_SEPARATORS = ".-٫"


def _clause_parts(clause: str) -> list[str]:
    return re.split(rf"[{re.escape(_CLAUSE_SEPARATORS)}]", clause)


def clause_depth(clause: str | None) -> int:
    """'7' -> 1, '7.2' -> 2, '7.2.1' -> 3, '1-1-1' -> 3. Zero for no clause."""
    return len(_clause_parts(clause)) if clause else 0


def parent_clause(clause: str | None) -> str:
    """'7.2.1' -> '7.2'; '1-1-1' -> '1-1'; '7' -> ''.

    The separator the document used is preserved, because the identifier is
    something a reader looks up in that document.
    """
    if not clause:
        return ""
    match = re.search(rf"[{re.escape(_CLAUSE_SEPARATORS)}][^{re.escape(_CLAUSE_SEPARATORS)}]*$", clause)
    return clause[: match.start()] if match else ""


def _clause_sort_key(clause: str) -> tuple[int, ...]:
    """Numeric key, so 7.10 sorts after 7.9 rather than before it."""
    return tuple(int(part) for part in _clause_parts(clause) if part.isdigit())


def clause_range(clauses: list[str]) -> tuple[str, str]:
    """Lowest and highest clause in a set, numerically ordered."""
    usable = [clause for clause in clauses if clause]
    if not usable:
        return "", ""
    ordered = sorted(set(usable), key=_clause_sort_key)
    return ordered[0], ordered[-1]


# --- blocks ----------------------------------------------------------------


@dataclass
class Block:
    """One structural element, in reading order."""

    kind: str  # "heading" | "table" | "clause" | "listitem" | "text"
    lines: list[str]
    level: int = 0  # heading level; 0 for everything else
    clause: str | None = None
    page: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()

    @property
    def length(self) -> int:
        return len(self.text)


def compact_table(lines: list[str]) -> list[str]:
    """Strip the column-alignment padding out of a Markdown table.

    Docling pads every cell to the width of the widest cell in its column, so a
    table carrying one 200-character definition pads all of its other rows to
    match. Across this corpus that padding is **47% of all table text** — an
    18-row table measured 40,320 characters holding 8,323 characters of content.

    The cost is not cosmetic. Padding is counted against the chunk budget, so
    tables that comfortably fit were split into parts; it is embedded, so half
    of a table chunk's vector is runs of spaces; and it is spent again in the
    drafting prompt, where thirty evidence chunks share one context window.

    Nothing is removed but whitespace: every cell, every pipe and every
    duplicated spanning label survives, so a chunk shown under Sources still
    reflects how the document actually parsed.
    """
    compacted: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            compacted.append(line)
            continue
        # Docling never escapes a pipe inside a cell (verified across the
        # corpus), so splitting on the delimiter cannot lose content.
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if _TABLE_SEP.match(stripped):
            cells = ["---"] * len(cells)
        compacted.append("| " + " | ".join(cells) + " |")
    return compacted


# How far back to look for the clause that introduces a table. Generous
# enough to clear a page's worth of headings, bounded so an unrelated
# clause on the previous page cannot claim it.
_INTRODUCTION_WINDOW = 12


def _introduced_by(blocks: list[Block], rows: list[str]) -> str | None:
    """The clause a table belongs to, when the table names none itself.

    A table under "3.1.1 ... as follows:" is part of 3.1.1, but nothing in its
    own rows says so, so the chunk holding it was labelled by whatever numbered
    text happened to share the chunk. The vulnerability-frequency table came out
    cited as §3.1.7–3.1.8 — two clauses about remediation planning that
    have nothing to do with scanning frequencies.

    Skipped when the rows carry control identifiers of their own: those are the
    table's real labels, and a section heading above them would only widen the
    citation back out to the section.
    """
    if any(row_control_id(row) for row in rows):
        return None

    nearest = None
    for block in reversed(blocks[-_INTRODUCTION_WINDOW:]):
        if not block.clause:
            continue
        # A clause that ends in a colon is introducing what comes after it, and
        # that is the one the table belongs to. Nearest-preceding is not enough:
        # Docling emits a floating table after the whole run of headings on its
        # page, so 3.1.1 "... as follows:" is six blocks above its own table
        # while 3.1.6 sits directly on top of it.
        if block.text.rstrip().endswith((":", "：")):
            return block.clause
        nearest = nearest or block.clause
    return nearest


def _strip_emphasis(text: str) -> str:
    return re.sub(r"(\*\*|__|\*|_)", "", text)


def parse_blocks(text: str) -> list[Block]:
    """Walk the document once, emitting structural blocks in reading order."""
    lines = strip_bidi(text).splitlines()
    total = len(lines)
    trailing = _uses_trailing_clauses(lines)
    blocks: list[Block] = []
    page: int | None = None

    pending: list[str] = []
    pending_kind = "text"
    pending_clause: str | None = None

    def flush() -> None:
        nonlocal pending, pending_kind, pending_clause
        if any(line.strip() for line in pending):
            blocks.append(Block(pending_kind, list(pending), 0, pending_clause, page))
        pending = []
        pending_kind = "text"
        pending_clause = None

    def absorb_continuation(start: int) -> int:
        """Consume wrapped lines belonging to the item that started at `start`."""
        cursor = start
        while cursor < total:
            nxt = lines[cursor]
            if not nxt.strip():
                break
            if _HEADING.match(nxt) or _TABLE_ROW.match(nxt):
                break
            if nxt.strip() in (_TABLE_OPEN, _TABLE_CLOSE):
                break
            if match_clause(nxt, trailing=trailing) or _BULLET.match(nxt) or _ALPHA_ITEM.match(nxt):
                break
            pending.append(nxt)
            cursor += 1
        return cursor

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
            title = heading_match.group(2).strip()
            blocks.append(
                Block("heading", [line], len(heading_match.group(1)), match_heading_clause(title), page)
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
                rows = compact_table(body)
                blocks.append(Block("table", rows, 0, _introduced_by(blocks, rows), page))
            index = cursor + 1
            continue

        if _TABLE_ROW.match(line):
            flush()
            cursor = index
            body = []
            while cursor < total and _TABLE_ROW.match(lines[cursor]):
                body.append(lines[cursor])
                cursor += 1
            rows = compact_table(body)
            blocks.append(Block("table", rows, 0, _introduced_by(blocks, rows), page))
            index = cursor
            continue

        clause = match_clause(line, trailing=trailing)
        if clause:
            flush()
            pending = [line]
            pending_kind = "clause"
            pending_clause = clause
            index = absorb_continuation(index + 1)
            flush()
            continue

        if _BULLET.match(line) or _ALPHA_ITEM.match(line):
            flush()
            pending = [line]
            pending_kind = "listitem"
            index = absorb_continuation(index + 1)
            flush()
            continue

        pending.append(line)
        index += 1

    flush()
    return blocks


# --- sections --------------------------------------------------------------


@dataclass
class Section:
    """A heading and everything beneath it, nested."""

    title: str = ""
    level: int = 0
    clause: str | None = None
    heading_block: Block | None = None
    blocks: list[Block] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)

    @property
    def length(self) -> int:
        own = sum(block.length + 2 for block in self.blocks)
        if self.heading_block:
            own += self.heading_block.length + 2
        return own + sum(child.length for child in self.children)

    def flatten(self) -> list[Block]:
        """Every block beneath this section, in reading order, heading first."""
        result: list[Block] = []
        if self.heading_block:
            result.append(self.heading_block)
        result.extend(self.blocks)
        for child in self.children:
            result.extend(child.flatten())
        return result


def build_sections(blocks: list[Block]) -> Section:
    """Nest blocks under their headings, returning a synthetic root."""
    root = Section(level=0)
    stack: list[Section] = [root]

    for block in blocks:
        if block.kind == "heading":
            while len(stack) > 1 and stack[-1].level >= block.level:
                stack.pop()
            section = Section(
                title=_strip_emphasis(block.lines[0]).lstrip("# ").strip(),
                level=block.level,
                clause=block.clause,
                heading_block=block,
            )
            stack[-1].children.append(section)
            stack.append(section)
        else:
            stack[-1].blocks.append(block)

    return root


def _split_by_top_clause(blocks: list[Block]) -> list[Section]:
    """Section an unheaded run by its shallowest clause level.

    Documents that number clauses but use no headings — common in converted PDFs,
    and in DOCX where heading styles were never applied — would otherwise be one
    undifferentiated unit.
    """
    depths = [clause_depth(block.clause) for block in blocks if block.clause]
    if not depths:
        return []
    top = min(depths)

    groups: list[Section] = []
    current: Section | None = None
    for block in blocks:
        if (block.clause and clause_depth(block.clause) == top) or current is None:
            current = Section(title=block.clause or "", level=99, clause=block.clause)
            groups.append(current)
        current.blocks.append(block)

    return groups if len(groups) > 1 else []


# --- units -----------------------------------------------------------------


# A stem is a lead-in line, not a paragraph. Anything longer is not introducing
# a list and would waste most of each continuation chunk.
_MAX_STEM_CHARS = 300


@dataclass
class Unit:
    """A span that should be retrieved together."""

    blocks: list[Block]
    heading_path: str = ""
    section_clause: str | None = None

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks if block.text).strip()

    @property
    def length(self) -> int:
        return sum(block.length + 2 for block in self.blocks)

    @property
    def heading(self) -> str:
        """Heading path, falling back to the unit's own headings.

        A small document collapses into a single root-level unit, which has no
        section path above it; without this fallback its heading metadata would
        be empty even though the headings are right there in the text.
        """
        if self.heading_path:
            return self.heading_path
        titles = [
            re.sub(r"(\*\*|__|\*|_)", "", block.lines[0]).lstrip("# ").strip()
            for block in self.blocks
            if block.kind == "heading"
        ]
        return " > ".join(titles[:3])

    @property
    def stem(self) -> str:
        """The line that introduces the unit, repeated on every split part.

        Preference: a line ending in a colon (the classic "the following shall:"
        lead-in), then the heading. The colon line comes first because the
        heading path is already carried in metadata and rendered in the sources
        block, whereas the lead-in is what makes a bare continuation list mean
        anything.

        Bounded by `_MAX_STEM_CHARS`, and empty when no short introducing line
        exists: on an unstructured wall of prose the first "line" is the whole
        block, and prepending that to every part would multiply the document.
        """
        for block in self.blocks:
            if not block.text:
                continue
            first_line = block.text.splitlines()[0].rstrip()
            if first_line.endswith((":", "\uff1a", "\u061b")) and len(first_line) <= _MAX_STEM_CHARS:
                return first_line

        if self.blocks and self.blocks[0].kind == "heading":
            candidate = self.blocks[0].text
            return candidate if len(candidate) <= _MAX_STEM_CHARS else ""

        if self.blocks:
            first_line = self.blocks[0].text.splitlines()[0]
            if len(first_line) <= _MAX_STEM_CHARS:
                return first_line
        return ""


def _collect_units(section: Section, ceiling: int, path: list[str], units: list[Unit]) -> None:
    """Emit units from a section tree, descending only where a section is too big."""
    if section.level > 0 and section.title:
        path = [*path, section.title]

    if section.length <= ceiling and (section.blocks or section.heading_block or section.children):
        units.append(Unit(section.flatten(), " > ".join(path), section.clause))
        return

    own = ([section.heading_block] if section.heading_block else []) + section.blocks
    if own:
        # No child headings to descend into, so fall back to clause numbering.
        synthetic = _split_by_top_clause(section.blocks) if not section.children else []
        if synthetic:
            if section.heading_block:
                units.append(Unit([section.heading_block], " > ".join(path), section.clause))
            for group in synthetic:
                units.append(Unit(group.blocks, " > ".join(path), group.clause))
        else:
            units.append(Unit(own, " > ".join(path), section.clause))

    for child in section.children:
        _collect_units(child, ceiling, path, units)


def _coalesce(units: list[Unit], target: int) -> list[Unit]:
    """Merge consecutive units that together still fit inside one chunk.

    Sectioning alone produces units as small as the document's own structure —
    a three-line clause under its own heading is a valid section and becomes a
    300-character unit. Retrieval then ranks that fragment on its own, and the
    drafter never sees the clause next to it.

    That is not hypothetical. "3.4.3 ... access rights are cancelled on their
    last working day" and "3.4.4 Post-Employment Access Monitoring" are
    adjacent sections of the HR policy; split apart, a question about how
    quickly access is revoked retrieved 3.4.4 alone and answered that the
    policy specifies no timeframe. Merged, both clauses arrive together and
    still fit in a single chunk.

    Merging is by adjacency in reading order, which is the only relationship
    that survives every numbering scheme in the corpus. A unit that already
    fills the chunk is left alone, so this only ever grows the small ones.
    """
    merged: list[Unit] = []
    for unit in units:
        previous = merged[-1] if merged else None
        if previous is not None and _absorbs(previous, unit, target):
            previous.blocks.extend(unit.blocks)
            # The heading path stays that of the first unit: it is the wider
            # context, and the merged text carries the later headings inline.
            previous.section_clause = previous.section_clause or unit.section_clause
        else:
            merged.append(Unit(list(unit.blocks), unit.heading_path, unit.section_clause))

    # A runt with nothing after it to join goes backwards instead.
    while len(merged) > 1 and _is_runt(merged[-1]):
        tail = merged.pop()
        merged[-1].blocks.extend(tail.blocks)
    return merged


# A unit this short carries no retrievable claim of its own. The threshold is
# generous on purpose: the failure it prevents is a chunk being *ranked and
# cited* on its own, and a hundred characters is not enough to answer anything.
_RUNT_CHARS = 200


def _is_heading_only(unit: Unit) -> bool:
    return bool(unit.blocks) and all(block.kind == "heading" for block in unit.blocks)


def _is_runt(unit: Unit) -> bool:
    return _is_heading_only(unit) or unit.length < _RUNT_CHARS


def _absorbs(previous: Unit, unit: Unit, target: int) -> bool:
    """Whether `unit` should join the unit before it.

    Adjacent units merge while they fit, which is the ordinary case. The two
    exceptions both exist to stop a fragment being indexed as though it were a
    retrievable section:

    Sectioning splits on every heading, so a heading immediately followed by
    another heading — "## Contents", "## Definitions", "## KEY TASKS" — became
    a unit whose entire content was its own title. 105 such chunks were indexed
    from this corpus, the shortest 11 characters long. They embed close to any
    query using the same word, so "what are the definitions of..." retrieved a
    chunk reading "## Definitions" and nothing else, and it consumed one of the
    fourteen slots in the drafting prompt. A heading belongs to the section it
    introduces, so it merges forward regardless of size; if the section is large
    the packer will split it again afterwards, with the heading leading the
    first part where it belongs.

    A merely short unit is the same problem in weaker form, and merges when the
    result stays within the oversize tolerance the packer already tolerates.
    """
    if previous.length + unit.length <= target:
        return True
    if _is_heading_only(previous):
        return True
    return _is_runt(previous) and previous.length + unit.length <= target * _OVERSIZE_TOLERANCE


def build_units(blocks: list[Block], *, ceiling: int = 7200, target: int = 1800) -> list[Unit]:
    """Group blocks into retrieval units, adapting depth to section size."""
    root = build_sections(blocks)
    units: list[Unit] = []
    _collect_units(root, ceiling, [], units)
    return _coalesce([unit for unit in units if unit.text], target)


# --- chunking --------------------------------------------------------------


@dataclass
class Chunk:
    text: str
    metadata: dict


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _spans_one_label(row: str) -> bool:
    """Whether a row is a single heading stretched across the table.

    Docling flattens a merged cell by repeating its text once per column it
    covers, so a grouping header arrives as `| | Systems | Systems | ... |`.
    That row names no column, and a piece of a split table that carries only it
    is unreadable: the vulnerability-frequency table lost `Asset Type | All
    systems | Critical systems connected to the internet | ...` to the split and
    left the drafter six columns all called "Systems".
    """
    labels = {cell for cell in _cells(row) if cell}
    return len(labels) == 1 and len(_cells(row)) > 2


def _table_header(block: Block) -> list[str]:
    rows = [line for line in block.lines if line.strip()]
    if not rows:
        return []
    header = rows[:2] if len(rows) > 1 and _TABLE_SEP.match(rows[1]) else rows[:1]

    # Carry the rows beneath a spanned label too, up to the first that really
    # names the columns. Bounded so a table of repeated values cannot be pulled
    # into its own header wholesale.
    while (
        len(header) < len(rows)
        and len(header) <= 3
        and _spans_one_label(header[-1] if not _TABLE_SEP.match(header[-1]) else header[0])
    ):
        header.append(rows[len(header)])

    return header


def _hard_wrap(text: str, budget: int) -> list[str]:
    """Cut `text` into pieces of at most `budget`, at the latest clean boundary.

    The last resort, for content that has no structure left to split on: a
    Markdown table whose whole body is one enormous cell, which `_split_table`
    cannot divide by rows because there is only one. Left alone, such a block
    became a 13,000-character chunk, and a dozen of those would crowd
    everything else out of the drafting prompt.

    Boundaries are tried in descending order of quality — paragraph, line,
    sentence, space — before giving up and cutting mid-word, so a clean break
    is taken whenever one exists.
    """
    pieces: list[str] = []
    remaining = text.strip()

    while len(remaining) > budget:
        window = remaining[:budget]
        cut = -1
        for separator in ("\n\n", "\n", ". ", "؟ ", "। ", " "):
            cut = window.rfind(separator)
            if cut > budget // 2:
                cut += len(separator)
                break
            cut = -1
        if cut <= 0:
            cut = budget
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()

    if remaining:
        pieces.append(remaining)
    return pieces


def _split_table(block: Block, budget: int) -> list[list[Block]]:
    """Split one table by rows, repeating the header on every piece."""
    header = _table_header(block)
    header_length = sum(len(line) + 1 for line in header)

    # A "table" that is one enormous line has no rows to split and its header
    # *is* the content — Docling emits this for a single-cell table holding a
    # whole section, and it produced 9,000-character chunks. There is no
    # structure to preserve, so wrap the text and keep no header.
    if header_length > budget:
        return [
            [Block("table", [piece], 0, block.clause, block.page)]
            for piece in _hard_wrap(block.text, budget)
        ]

    rows = [line for line in block.lines if line.strip()][len(header):]
    # A single row can also exceed the budget on its own — one cell holding a
    # paragraph. Break those down first, so the packing below is working with
    # rows that can actually fit beneath the repeated header.
    room_for_row = max(budget - header_length, 200)
    rows = [piece for row in rows for piece in _hard_wrap(row, room_for_row)]
    room = max(budget - sum(len(line) + 1 for line in header), 200)

    pieces: list[list[Block]] = []
    current: list[str] = []
    used = 0
    for row in rows:
        if current and used + len(row) + 1 > room:
            pieces.append([Block(
                "table", header + current, 0,
                _table_clause_range(current)[0] or block.clause, block.page,
            )])
            current, used = [], 0
        current.append(row)
        used += len(row) + 1
    if current:
        pieces.append([Block(
            "table", header + current, 0,
            _table_clause_range(current)[0] or block.clause, block.page,
        )])
    return pieces or [[block]]


def _split_prose(block: Block, budget: int) -> list[list[Block]]:
    """Split an oversized paragraph on sentence boundaries."""
    pieces: list[list[Block]] = []
    current: list[str] = []
    used = 0
    # Latin, Arabic question mark, Urdu full stop, CJK full stop. A "sentence"
    # with no terminator in it \u2014 a long unpunctuated legal clause \u2014 is hard-
    # wrapped, so no piece exceeds the budget however the text is written.
    sentences = [
        piece
        for sentence in re.split(r"(?<=[.!?\u061f\u06d4\u3002])\s+", block.text)
        for piece in _hard_wrap(sentence, budget)
    ]
    for sentence in sentences:
        if current and used + len(sentence) + 1 > budget:
            pieces.append([Block(block.kind, ["\n".join(current)], 0, block.clause, block.page)])
            current, used = [], 0
        current.append(sentence)
        used += len(sentence) + 1
    if current:
        pieces.append([Block(block.kind, ["\n".join(current)], 0, block.clause, block.page)])
    return pieces or [[block]]


def _pack_unit(unit: Unit, chunk_size: int) -> list[list[Block]]:
    """Divide a unit into block groups that each fit, never breaking a table."""
    stem = unit.stem
    prefix_cost = len(stem) + 2 if stem else 0

    groups: list[list[Block]] = []
    current: list[Block] = []
    used = 0

    def close() -> None:
        nonlocal current, used
        if current:
            groups.append(current)
        current, used = [], 0

    for block in unit.blocks:
        budget = chunk_size - (prefix_cost if groups or current else 0)

        if block.length > budget:
            pieces = _split_table(block, budget) if block.kind == "table" else _split_prose(block, budget)
            # A runt that has accumulated so far leads the first piece rather
            # than being flushed on its own. A section's heading is followed by
            # the table or prose run it introduces; closing here made that
            # heading part 1 of N, an eleven-character chunk that was indexed,
            # ranked and cited by itself. Merging the heading into its unit
            # earlier is not enough — this is where the unit is divided again,
            # and it is where the heading was being left behind.
            #
            # Only a runt, though. Folding in whatever happened to be pending
            # produced 3.5 KB chunks when a nearly full group met a table that
            # could not be split, which trades one budget breach for another.
            if current and pieces and used <= _RUNT_CHARS:
                pieces[0] = current + pieces[0]
                current, used = [], 0
            else:
                close()
            groups.extend(pieces)
            continue

        if current and used + block.length + 2 > budget:
            close()
        current.append(block)
        used += block.length + 2

    close()
    return _absorb_tiny_tail(groups, chunk_size) or [list(unit.blocks)]


# A final group this far below the ceiling is an artefact of where the last
# block happened to land, not a unit worth retrieving on its own. Folding it
# back costs a slightly oversized chunk — `chunk_size` is a soft ceiling — and
# saves a fragment that would otherwise be ranked and cited by itself.
_TAIL_FRACTION = 0.2
_OVERSIZE_TOLERANCE = 1.3


def _absorb_tiny_tail(groups: list[list[Block]], chunk_size: int) -> list[list[Block]]:
    """Fold a runt final group back into its predecessor where that stays reasonable."""
    if len(groups) < 2:
        return groups

    tail_length = sum(block.length + 2 for block in groups[-1])
    head_length = sum(block.length + 2 for block in groups[-2])
    if tail_length > chunk_size * _TAIL_FRACTION:
        return groups
    if head_length + tail_length > chunk_size * _OVERSIZE_TOLERANCE:
        return groups

    return [*groups[:-2], groups[-2] + groups[-1]]


def _chunk_kind(blocks: list[Block]) -> str:
    kinds = {block.kind for block in blocks if block.kind != "heading"}
    if kinds == {"table"}:
        return "table"
    if sum(1 for block in blocks if block.kind in ("clause", "listitem")) >= 2:
        return "series"
    if "table" in kinds:
        return "mixed"
    return "prose"


def chunk_document(text: str, *, source_name: str = "", chunk_size: int = 1800) -> list[Chunk]:
    """Chunk a document into structure-respecting pieces with citation metadata.

    `chunk_size` is a soft ceiling. A table or clause run that exceeds it is
    divided into parts that share a `unit_id` and repeat the unit's stem, rather
    than being silently truncated.
    """
    blocks = parse_blocks(text)
    units = build_units(blocks, ceiling=max(chunk_size * 4, chunk_size), target=chunk_size)

    doc_id_match = _DOC_ID.search(text[:4000]) or _DOC_ID.search(source_name)
    doc_id = doc_id_match.group(1) if doc_id_match else ""
    base = doc_id or source_name or "doc"

    chunks: list[Chunk] = []
    for unit_index, unit in enumerate(units):
        groups = _pack_unit(unit, chunk_size)
        unit_id = f"{base}:u{unit_index}"
        stem = unit.stem

        for part_index, group in enumerate(groups, start=1):
            body = "\n\n".join(block.text for block in group if block.text).strip()
            if not body:
                continue
            # Repeat the stem on continuation parts, so a bare list still says
            # what it is a list of.
            if part_index > 1 and stem and not body.startswith(stem):
                body = f"{stem}\n{body}"

            labelled = [block.clause for block in group if block.clause]
            # A control table numbers its rows, not its blocks: one block can
            # hold "1-1-1" through "1-1-9", and taking the block's own label
            # alone would cite the first of nine and look precise doing it.
            labelled += [
                control
                for block in group if block.kind == "table"
                for control in map(row_control_id, block.lines) if control
            ]
            start, end = clause_range(labelled)
            pages = [block.page for block in group if block.page is not None]

            chunks.append(
                Chunk(
                    text=body,
                    metadata={
                        "doc_id": doc_id,
                        "clause": start,
                        "clause_start": start,
                        "clause_end": end,
                        "parent_clause": parent_clause(start),
                        "section_clause": unit.section_clause or "",
                        "heading": unit.heading,
                        "page": pages[0] if pages else -1,
                        "kind": _chunk_kind(group),
                        "item_count": sum(1 for block in group if block.kind in ("clause", "listitem")),
                        "unit_id": unit_id,
                        "part": part_index,
                        "parts": len(groups),
                    },
                )
            )

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk"] = index
        chunk.metadata["source_name"] = source_name
    return chunks