"""Reading and writing .xlsx as what it is: a zip of XML parts.

No spreadsheet library. That is a deliberate choice rather than an omission --
measured on the sample workbooks, a load-and-save through openpyxl dropped 16
drawings from one file and every cell comment from another, and mangled most
conditional formatting, because a library can only write back what its object
model understood. Here, the only bytes that change are the cells being answered;
every other part is copied across untouched, so parts we do not understand
cannot be damaged by us.

Reading needs the same package anyway -- cell text, merged ranges, dropdown
vocabularies, which sheets are hidden -- so one mechanism serves both directions
and there is no second model of a workbook to keep in step.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import xml.etree.ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = f"{{{MAIN}}}"
RELNS = f"{{{REL}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

ET.register_namespace("", MAIN)

_REF = re.compile(r"^([A-Z]+)(\d+)$")
_RANGE = re.compile(r"^(?:'([^']+)'|([A-Za-z0-9_ .]+))!\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)$")


def column_number(letters: str) -> int:
    """'A' -> 1, 'AA' -> 27. Sort order for columns is not alphabetical."""
    value = 0
    for character in letters:
        value = value * 26 + (ord(character) - 64)
    return value


def column_letters(number: int) -> str:
    letters = ""
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def split_ref(ref: str) -> tuple[str, int]:
    """'C9' -> ('C', 9)."""
    match = _REF.match(ref)
    if not match:
        raise ValueError(f"Not a cell reference: {ref!r}")
    return match.group(1), int(match.group(2))


@dataclass
class Sheet:
    """One worksheet, read into memory."""

    name: str
    part: str
    state: str
    cells: dict[tuple[int, str], str] = field(default_factory=dict)
    formulas: set[tuple[int, str]] = field(default_factory=set)
    """Cells holding a formula. Never written to -- see `Workbook.write`."""

    merges: list[str] = field(default_factory=list)
    validations: list[tuple[str, str]] = field(default_factory=list)
    """(sqref, formula1) pairs, before the formula is resolved to values."""

    _rows: list[int] | None = field(default=None, repr=False)
    _columns: list[str] | None = field(default=None, repr=False)
    _by_row: dict[int, dict[str, str]] | None = field(default=None, repr=False)

    @property
    def visible(self) -> bool:
        return self.state == "visible"

    @property
    def rows(self) -> list[int]:
        """Row numbers holding anything, ascending.

        Cached. Detection reads this inside nested loops -- every candidate
        header row against every column -- and recomputing a sorted set each
        time made a large sheet quadratic: 4,000 rows took a second and 30,000
        took nearly three minutes.
        """
        if self._rows is None:
            self._rows = sorted({row for row, _ in self.cells})
        return self._rows

    @property
    def columns(self) -> list[str]:
        if self._columns is None:
            self._columns = sorted({column for _, column in self.cells}, key=column_number)
        return self._columns

    def value(self, row: int, column: str) -> str:
        return self.cells.get((row, column), "")

    def row_values(self, row: int) -> dict[str, str]:
        """Everything on one row. Indexed once, because detection asks per row."""
        if self._by_row is None:
            index: dict[int, dict[str, str]] = {}
            for (number, column), text in self.cells.items():
                if text:
                    index.setdefault(number, {})[column] = text
            self._by_row = index
        return self._by_row.get(row, {})

    def column_values(self, column: str) -> list[tuple[int, str]]:
        """Everything in one column, ascending by row."""
        return [(row, self.cells[(row, column)]) for row in self.rows if (row, column) in self.cells]


MAX_PART_BYTES = 64 * 1024 * 1024
"""Most a single decompressed part may be.

These files arrive from other companies and the service is publicly reachable,
so the uncompressed size is not something to take on trust: a few kilobytes of
zip can expand to gigabytes, and every part here is read into memory. The
largest real sample decompresses to under two megabytes.
"""

MAX_CELLS = 400_000
"""Most cells one workbook may hold. The largest real sample has 1,288."""


class FormatError(Exception):
    """The file is not a workbook this can read. The message is safe to show."""


class Workbook:
    """An .xlsx file, read once and held.

    Cheap enough to hold whole: the largest sample is a megabyte of zip and a
    few thousand cells, and detection needs to look across the whole sheet
    repeatedly.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        try:
            self._zip = zipfile.ZipFile(self.path)
        except (zipfile.BadZipFile, OSError) as error:
            raise FormatError(f"{self.path.name} is not a readable .xlsx file.") from error

        self._guard_sizes()
        try:
            self._strings = self._read_shared_strings()
            self.sheets = [self._read_sheet(*entry) for entry in self._sheet_entries()]
        except FormatError:
            raise
        except KeyError as error:
            self._zip.close()
            # zipfile's KeyError carries a whole English sentence as its
            # argument. Recover just the part name, so the message reads as ours.
            missing = re.search(r"named '([^']+)'", str(error.args[0] if error.args else ""))
            named = f" ({missing.group(1)})" if missing else ""
            raise FormatError(
                f"{self.path.name} is missing a part it needs{named}, so it is not a complete workbook."
            ) from error
        except ET.ParseError as error:
            self._zip.close()
            raise FormatError(f"{self.path.name} contains XML that could not be read: {error}") from error

        total = sum(len(sheet.cells) for sheet in self.sheets)
        if total > MAX_CELLS:
            self._zip.close()
            raise FormatError(
                f"{self.path.name} holds {total:,} cells, past the {MAX_CELLS:,} this reads. "
                "Split it into smaller files."
            )
        self._by_name = {sheet.name: sheet for sheet in self.sheets}

    def _guard_sizes(self) -> None:
        """Refuse a part that would decompress to more than we will hold.

        Checked from the directory rather than by reading, so a zip bomb is
        turned away before any of it is expanded.
        """
        for item in self._zip.infolist():
            if item.file_size > MAX_PART_BYTES:
                self._zip.close()
                raise FormatError(
                    f"{self.path.name} contains a part of "
                    f"{item.file_size / 1024 / 1024:,.0f} MB, past the "
                    f"{MAX_PART_BYTES // 1024 // 1024} MB this reads."
                )

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> Workbook:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __getitem__(self, name: str) -> Sheet:
        return self._by_name[name]

    def get(self, name: str) -> Sheet | None:
        return self._by_name.get(name)

    @property
    def part_count(self) -> int:
        return len(self._zip.namelist())

    # --- reading -----------------------------------------------------------

    def _read_shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self._zip.namelist():
            return []
        root = ET.fromstring(self._zip.read("xl/sharedStrings.xml"))
        return ["".join(node.text or "" for node in item.iter(f"{NS}t")) for item in root.findall(f"{NS}si")]

    def _sheet_entries(self) -> Iterator[tuple[str, str, str]]:
        """Sheet name, package part, and visibility -- in workbook tab order."""
        workbook = ET.fromstring(self._zip.read("xl/workbook.xml"))
        rels = ET.fromstring(self._zip.read("xl/_rels/workbook.xml.rels"))
        targets = {node.get("Id"): node.get("Target") for node in rels}
        sheets = workbook.find(f"{NS}sheets")
        if sheets is None:
            raise FormatError(f"{self.path.name} lists no sheets, so there is nothing to read.")
        for node in sheets:
            target = (targets.get(node.get(f"{RELNS}id")) or "").lstrip("/")
            if not target:
                continue
            if not target.startswith("xl/"):
                target = "xl/" + target
            yield node.get("name") or "", target, node.get("state") or "visible"

    def _cell_text(self, cell: ET.Element) -> str:
        kind = cell.get("t")
        if kind == "inlineStr":
            inline = cell.find(f"{NS}is")
            return "".join(node.text or "" for node in inline.iter(f"{NS}t")) if inline is not None else ""
        value = cell.find(f"{NS}v")
        if value is None or value.text is None:
            return ""
        if kind == "s":
            index = int(value.text)
            return self._strings[index] if index < len(self._strings) else ""
        return value.text

    def _read_sheet(self, name: str, part: str, state: str) -> Sheet:
        sheet = Sheet(name=name, part=part, state=state)
        try:
            raw = self._zip.read(part)
        except KeyError:
            return sheet
        root = ET.fromstring(raw)

        for cell in root.iter(f"{NS}c"):
            ref = cell.get("r")
            if not ref:
                continue
            try:
                column, row = split_ref(ref)
            except ValueError:
                continue
            if cell.find(f"{NS}f") is not None:
                sheet.formulas.add((row, column))
            text = self._cell_text(cell).strip()
            if text:
                sheet.cells[(row, column)] = text

        sheet.merges = [node.get("ref") or "" for node in root.iter(f"{NS}mergeCell")]

        for node in root.iter(f"{NS}dataValidation"):
            formula = node.find(f"{NS}formula1")
            sheet.validations.append((node.get("sqref") or "", (formula.text or "") if formula is not None else ""))
        # Newer Excel writes list validations into an extension block instead.
        text = raw.decode("utf-8", "replace")
        for block in re.findall(r"<x14:dataValidation\b.*?</x14:dataValidation>", text, re.S):
            sqref = re.search(r"<xm:sqref>(.*?)</xm:sqref>", block, re.S)
            formula = re.search(r"<xm:f>(.*?)</xm:f>", block, re.S)
            if sqref:
                sheet.validations.append((sqref.group(1), formula.group(1) if formula else ""))
        return sheet

    # --- derived views -----------------------------------------------------

    def merged_ranges(self, sheet: Sheet) -> dict[tuple[int, str], tuple[int, str]]:
        """Every covered cell mapped to the anchor whose value it displays.

        Excel keeps a merged region's text in its top-left cell and leaves the
        rest empty, so a question spanning three columns reads as blank in two
        of them unless this mapping is applied.
        """
        covered: dict[tuple[int, str], tuple[int, str]] = {}
        for span in sheet.merges:
            if ":" not in span:
                continue
            try:
                start, end = span.split(":")
                first_column, first_row = split_ref(start)
                last_column, last_row = split_ref(end)
            except ValueError:
                continue
            anchor = (first_row, first_column)
            for row in range(first_row, last_row + 1):
                for number in range(column_number(first_column), column_number(last_column) + 1):
                    key = (row, column_letters(number))
                    if key != anchor:
                        covered[key] = anchor
        return covered

    def validated_columns(self, sheet: Sheet) -> set[str]:
        """Columns carrying a dropdown, whether or not anything was ever typed in one.

        `Sheet.columns` only knows about columns holding a value, and an unused
        dropdown holds none. On a blank questionnaire that is the normal state
        of the status column -- the one place a form most wants an answer -- so
        reading only the populated columns made it invisible.
        """
        found: set[str] = set()
        for sqref, _ in sheet.validations:
            for part in sqref.split():
                bounds = part.split(":")
                try:
                    first = column_number(split_ref(bounds[0])[0])
                    last = column_number(split_ref(bounds[-1])[0])
                except (ValueError, IndexError):
                    continue
                found.update(column_letters(number) for number in range(first, last + 1))
        return found

    def vocabulary_for(self, sheet: Sheet, column: str) -> list[str]:
        """The values a dropdown on this column allows, if there is one.

        Two shapes appear in the samples: an inline quoted list, and a reference
        to a range on another sheet -- the ISRA workbook keeps its compliance
        levels on a hidden 'Score' sheet and points fifteen validations at it.
        Both resolve here so the drafter is handed actual words either way.
        """
        for sqref, formula in sheet.validations:
            if not _covers_column(sqref, column) or not formula:
                continue
            values = self._resolve_vocabulary(formula)
            if values:
                return values
        return []

    def _resolve_vocabulary(self, formula: str) -> list[str]:
        formula = formula.strip()
        if formula.startswith('"') and formula.endswith('"'):
            return [part.strip() for part in formula[1:-1].split(",") if part.strip()]

        match = _RANGE.match(formula)
        if not match:
            return []
        sheet_name = match.group(1) or match.group(2)
        source = self.get(sheet_name.strip())
        if source is None:
            return []
        first_column, first_row = match.group(3), int(match.group(4))
        last_column, last_row = match.group(5), int(match.group(6))
        values = []
        for row in range(first_row, last_row + 1):
            for number in range(column_number(first_column), column_number(last_column) + 1):
                text = source.value(row, column_letters(number))
                if text:
                    values.append(text)
        return values

    # --- writing -----------------------------------------------------------

    def write(
        self,
        destination: str | Path,
        values: dict[str, dict[str, str]],
        *,
        allow_formula_overwrite: bool = False,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Write `{sheet: {ref: text}}` and copy every other part unchanged.

        Returns `(written, skipped)` -- the second maps a `sheet!ref` to why
        nothing was put there.

        A cell holding a formula is refused by default. Overwriting one is how
        a workbook quietly stops adding up: the ISRA file scores itself from 93
        formulas on a hidden sheet, and a value dropped into the wrong cell
        would look filled in and be wrong.
        """
        written: dict[str, str] = {}
        skipped: dict[str, str] = {}
        edits: dict[str, dict[str, str]] = {}

        for sheet_name, cells in values.items():
            sheet = self.get(sheet_name)
            if sheet is None:
                for ref in cells:
                    skipped[f"{sheet_name}!{ref}"] = f"No sheet named {sheet_name!r}."
                continue
            for ref, text in cells.items():
                try:
                    column, row = split_ref(ref)
                except ValueError:
                    skipped[f"{sheet_name}!{ref}"] = f"{ref!r} is not a cell reference."
                    continue
                if (row, column) in sheet.formulas and not allow_formula_overwrite:
                    skipped[f"{sheet_name}!{ref}"] = "That cell holds a formula."
                    continue
                edits.setdefault(sheet.part, {})[ref] = text
                written[f"{sheet_name}!{ref}"] = sheet.value(row, column)

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Build beside the destination and move it into place. Two reasons, and
        # the first is data loss: writing straight to the destination truncates
        # it, so `write(path, path)` -- answering a file in place, which is the
        # obvious thing for a caller to ask for -- destroyed the questionnaire
        # while still reading it. The second is that a crash halfway through now
        # leaves the old file rather than half a new one.
        # Assembled in memory first, so every read from the source is finished
        # before anything on disk moves. Windows refuses to replace a file that
        # is still open, which is exactly the in-place case. Size is bounded by
        # MAX_PART_BYTES and MAX_CELLS, so this is a few megabytes at most.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
            for item in self._zip.infolist():
                raw = self._zip.read(item.filename)
                if item.filename in edits:
                    raw = _apply_cell_edits(raw, edits[item.filename])
                # The same ZipInfo, so names, timestamps and attributes survive.
                out.writestr(item, raw)

        in_place = destination.exists() and self.path.exists() and destination.samefile(self.path)
        if in_place:
            self._zip.close()

        temporary = destination.with_name(destination.name + ".partial")
        try:
            temporary.write_bytes(buffer.getvalue())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return written, skipped


def _covers_column(sqref: str, column: str) -> bool:
    """Whether a validation's range touches this column.

    `sqref` is space-separated ranges: 'C2:C11', or 'C2:C7 C9:C12' where a row
    in the middle is exempt. Column membership is all this needs to answer.
    """
    wanted = column_number(column)
    for part in sqref.split():
        bounds = part.split(":")
        try:
            first = column_number(split_ref(bounds[0])[0])
            last = column_number(split_ref(bounds[-1])[0])
        except (ValueError, IndexError):
            continue
        if first <= wanted <= last:
            return True
    return False


MAX_CELL_CHARACTERS = 32767
"""The most text Excel holds in one cell. Past it, Excel reports the file damaged."""

_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
"""Characters XML 1.0 does not allow anywhere, which a model's output can still carry."""


def xml_safe(text: str) -> str:
    """`text` without the characters no XML document may contain.

    Every format this writes is XML inside a zip, and a model's answer can carry
    a vertical tab or a form feed. python-docx refuses those outright, so one of
    them failed a whole Word fill; ElementTree writes them, so one of them made
    a worksheet part unreadable.
    """
    return _NOT_XML.sub("", text or "")


_ATTRIBUTE = re.compile(r"""([^\s=/>]+)\s*=\s*("[^"]*"|'[^']*')""")


def _cell_safe(text: str) -> str:
    """Text a cell can hold: legal XML, and no longer than Excel accepts."""
    text = xml_safe(text)
    if len(text) > MAX_CELL_CHARACTERS:
        text = text[: MAX_CELL_CHARACTERS - 1] + "\u2026"
    return text


class _Unspliceable(Exception):
    """A worksheet shaped in a way the byte-level splice does not handle."""


def _apply_cell_edits(sheet_xml: bytes, edits: dict[str, str]) -> bytes:
    """Set cells in one worksheet part, leaving everything else as it was.

    Strings go in as `t="inlineStr"` so `sharedStrings.xml` is never touched --
    one fewer part to rewrite, and no index bookkeeping that could corrupt the
    strings every other sheet is sharing. The style index `s` is kept, so a cell
    written into a wrapped, bordered column still looks like its neighbours.

    Spliced into the part's own bytes rather than parsed and serialised again.
    A round trip through ElementTree renamed every namespace prefix but the main
    one and dropped the declarations it did not see used, so the `mc:Ignorable`
    list Excel puts on every worksheet ended up naming prefixes that no longer
    existed -- and Excel would not open the filled file. The whole-part rewrite
    stays as the fallback for a shape the splice does not recognise.
    """
    edits = {ref: _cell_safe(text) for ref, text in edits.items()}
    try:
        return _splice_cell_edits(sheet_xml, edits)
    except _Unspliceable:
        return _rewrite_cell_edits(sheet_xml, edits)


def _splice_cell_edits(sheet_xml: bytes, edits: dict[str, str]) -> bytes:
    try:
        text = sheet_xml.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _Unspliceable from error

    opening = re.search(r"<((?:[A-Za-z_][\w.-]*:)?)sheetData\b([^>]*?)(/?)>", text)
    if opening is None:
        return sheet_xml
    prefix = opening.group(1)
    if opening.group(3):
        head = text[: opening.start()] + f"<{prefix}sheetData{opening.group(2)}>"
        inner = ""
        tail = f"</{prefix}sheetData>" + text[opening.end() :]
    else:
        closing = text.find(f"</{prefix}sheetData>", opening.end())
        if closing < 0:
            raise _Unspliceable
        head, inner, tail = text[: opening.end()], text[opening.end() : closing], text[closing:]

    tag = re.escape(prefix)
    # [(row number or None for whitespace between rows, raw text)]
    segments: list[list] = []
    for start, end, match in _elements(inner, rf"<{tag}row\b([^>]*?)(/>|>(.*?)</{tag}row>)"):
        if start < 0:
            segments.append([None, inner[end:match]])
            continue
        number = _number_attribute(match.group(1))
        segments.append([number, match])

    wanted: dict[int, dict[str, str]] = {}
    for ref, value in edits.items():
        column, row_number = split_ref(ref)
        wanted.setdefault(row_number, {})[ref] = value

    rows = {segment[0]: segment for segment in segments if segment[0] is not None}
    for row_number, cells in sorted(wanted.items()):
        if row_number in rows:
            match = rows[row_number][1]
            body = _set_cells(match.group(3) or "", cells, prefix)
            rows[row_number][1] = f"<{prefix}row{match.group(1)}>{body}</{prefix}row>"
            continue
        created = f'<{prefix}row r="{row_number}">{_set_cells("", cells, prefix)}</{prefix}row>'
        later = next(
            (index for index, segment in enumerate(segments) if segment[0] is not None and segment[0] > row_number),
            len(segments),
        )
        segments.insert(later, [row_number, created])
        rows[row_number] = segments[later]

    rebuilt = "".join(segment[1] if isinstance(segment[1], str) else segment[1].group(0) for segment in segments)
    return (head + rebuilt + tail).encode("utf-8")


def _elements(text: str, pattern: str):
    """Walk `text` as a run of `pattern` matches with only whitespace between.

    Yields `(-1, gap_start, gap_end)` for the whitespace and `(start, end, match)`
    for each element. Anything else between them -- a comment, an element the
    splice does not know -- is refused rather than guessed around.
    """
    position = 0
    for match in re.finditer(pattern, text, re.S):
        if text[position : match.start()].strip():
            raise _Unspliceable
        if match.start() > position:
            yield -1, position, match.start()
        yield match.start(), match.end(), match
        position = match.end()
    if text[position:].strip():
        raise _Unspliceable
    if position < len(text):
        yield -1, position, len(text)


def _attributes(raw: str) -> list[tuple[str, str]]:
    return _ATTRIBUTE.findall(raw)


def _number_attribute(raw: str) -> int:
    value = dict(_attributes(raw)).get("r")
    if value is None or not value[1:-1].isdigit():
        raise _Unspliceable  # a row without its number is legal, and left to the rewrite
    return int(value[1:-1])


def _set_cells(body: str, cells: dict[str, str], prefix: str) -> str:
    """One row's cells with `cells` written in, in column order."""
    tag = re.escape(prefix)
    # [(column number or None for whitespace, raw text)]
    segments: list[list] = []
    for start, end, match in _elements(body, rf"<{tag}c\b([^>]*?)(/>|>(.*?)</{tag}c>)"):
        if start < 0:
            segments.append([None, body[end:match], ""])
            continue
        reference = dict(_attributes(match.group(1))).get("r")
        if reference is None:
            raise _Unspliceable
        try:
            column, _ = split_ref(reference[1:-1])
        except ValueError as error:
            raise _Unspliceable from error
        segments.append([column_number(column), match.group(0), match.group(1)])

    by_column = {segment[0]: segment for segment in segments if segment[0] is not None}
    for ref, value in sorted(cells.items(), key=lambda item: column_number(split_ref(item[0])[0])):
        number = column_number(split_ref(ref)[0])
        if number in by_column:
            kept = "".join(
                f" {name}={quoted}" for name, quoted in _attributes(by_column[number][2]) if name not in ("r", "t")
            )
            by_column[number][1] = _inline_cell(ref, kept, value, prefix)
            continue
        created = [number, _inline_cell(ref, "", value, prefix), ""]
        later = next(
            (index for index, segment in enumerate(segments) if segment[0] is not None and segment[0] > number),
            len(segments),
        )
        segments.insert(later, created)
        by_column[number] = created
    return "".join(segment[1] for segment in segments)


def _inline_cell(ref: str, attributes: str, text: str, prefix: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<{prefix}c r="{ref}"{attributes} t="inlineStr"><{prefix}is>'
        f'<{prefix}t xml:space="preserve">{escaped}</{prefix}t></{prefix}is></{prefix}c>'
    )


def _rewrite_cell_edits(sheet_xml: bytes, edits: dict[str, str]) -> bytes:
    """The whole part parsed and serialised again. Only for what the splice refuses."""
    root = ET.fromstring(sheet_xml)
    data = root.find(f"{NS}sheetData")
    if data is None:
        return sheet_xml

    rows = {int(node.get("r")): node for node in data.findall(f"{NS}row") if node.get("r")}

    for ref, text in edits.items():
        column, row_number = split_ref(ref)
        row = rows.get(row_number)
        if row is None:
            row = ET.Element(f"{NS}row", {"r": str(row_number)})
            later = [node for number, node in sorted(rows.items()) if number > row_number]
            children = list(data)
            data.insert(children.index(later[0]) if later else len(children), row)
            rows[row_number] = row

        cell = next((node for node in row.findall(f"{NS}c") if node.get("r") == ref), None)
        if cell is None:
            cell = ET.Element(f"{NS}c", {"r": ref})
            wanted = column_number(column)
            after = [
                node
                for node in row.findall(f"{NS}c")
                if node.get("r") and column_number(split_ref(node.get("r"))[0]) > wanted
            ]
            children = list(row)
            row.insert(children.index(after[0]) if after else len(children), cell)

        for child in list(cell):
            cell.remove(child)
        cell.set("t", "inlineStr")
        inline = ET.SubElement(cell, f"{NS}is")
        node = ET.SubElement(inline, f"{NS}t")
        node.text = text
        # Without this Excel strips leading and trailing spaces on read.
        node.set(XML_SPACE, "preserve")

    return ET.tostring(root, xml_declaration=True, encoding="UTF-8")
