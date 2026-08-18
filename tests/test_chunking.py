"""Step 1 — structure-aware chunking.

The property under test is not "chunks are the right size". It is: **no numbered
series and no table ever loses a member**, whatever the chunk size. That is the
defect the whole change exists to fix, so it is asserted at several chunk sizes
rather than one.
"""

from __future__ import annotations

import pytest

from src.chunking import build_units, chunk_document, parent_clause, parse_blocks, strip_bidi

SERIES_ITEMS = [f"7.2.{n}" for n in range(1, 13)]
TABLE_ROWS = ["Critical", "High", "Medium", "Low"]


def kinds(chunks) -> list[str]:
    return [chunk.metadata["kind"] for chunk in chunks]


# --- clause parsing --------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("7.2.1 Failed authentication attempts.", "7.2.1"),
        ("12.3.4.5 Nested clause.", "12.3.4.5"),
        ("7. A single-level clause with a period.", "7"),
        ("7) A single-level clause with a paren.", "7"),
        ("\u0667.\u0662.\u0661 محاولات مصادقة فاشلة.", "7.2.1"),
        ("\u200f\u0667.\u0662.\u0662 مصادقة ناجحة.", "7.2.2"),
    ],
)
def test_clause_identifiers_are_parsed_and_folded_to_ascii(line, expected):
    blocks = parse_blocks(line)
    clauses = [block.clause for block in blocks if block.kind == "clause"]
    assert clauses == [expected]


@pytest.mark.parametrize(
    "line",
    [
        "2024 saw the rollout of the new standard.",
        "200 data subject records is the threshold.",
    ],
)
def test_bare_leading_number_is_not_read_as_a_clause(line):
    """A year or a quantity opening a sentence must not become clause 2024."""
    blocks = parse_blocks(line)
    assert [block.clause for block in blocks if block.kind == "clause"] == []


@pytest.mark.parametrize(
    ("clause", "expected"),
    [("7.2.1", "7.2"), ("7.2", "7"), ("7", ""), ("", ""), (None, "")],
)
def test_parent_clause(clause, expected):
    assert parent_clause(clause) == expected


def test_strip_bidi_removes_controls_but_keeps_arabic():
    text = "\u200f\u0667.\u0662.\u0661 \u0645\u062d\u0627\u0648\u0644\u0627\u062a\u202c"
    cleaned = strip_bidi(text)
    assert "\u200f" not in cleaned and "\u202c" not in cleaned
    assert "\u0645\u062d\u0627\u0648\u0644\u0627\u062a" in cleaned


# --- the core property -----------------------------------------------------


@pytest.mark.parametrize("chunk_size", [300, 500, 900, 1800, 4000])
def test_no_series_item_is_ever_lost(series_doc, chunk_size):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=chunk_size)
    joined = "\n".join(chunk.text for chunk in chunks)
    missing = [item for item in SERIES_ITEMS if item not in joined]
    assert not missing, f"lost {missing} at chunk_size={chunk_size}"


@pytest.mark.parametrize("chunk_size", [300, 500, 900, 1800, 4000])
def test_no_table_row_is_ever_lost(series_doc, chunk_size):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=chunk_size)
    joined = "\n".join(chunk.text for chunk in chunks)
    missing = [row for row in TABLE_ROWS if row not in joined]
    assert not missing, f"lost table rows {missing} at chunk_size={chunk_size}"


def test_whole_series_stays_in_one_chunk_at_default_size(series_doc):
    """At chunk_size=1800 a 12-item series should not need splitting at all."""
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=1800)
    series = [chunk for chunk in chunks if chunk.metadata["kind"] == "series"]
    assert len(series) == 1, "series was split unnecessarily at the default size"
    assert all(item in series[0].text for item in SERIES_ITEMS)
    assert series[0].metadata["parts"] == 1


def test_table_is_never_merged_with_surrounding_prose(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=4000)
    tables = [chunk for chunk in chunks if chunk.metadata["kind"] == "table"]
    assert len(tables) == 1
    assert "3072 bits" not in tables[0].text, "cryptography prose leaked into the table chunk"


# --- split behaviour -------------------------------------------------------


def test_split_series_repeats_the_stem_on_every_part(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=400)
    parts = [c for c in chunks if c.metadata["kind"] == "series" and c.metadata["parts"] > 1]
    assert len(parts) > 1, "expected the series to split at chunk_size=400"
    stem = "alerts for the following conditions"
    assert all(stem in part.text for part in parts), "stem not repeated on every part"


def test_split_table_repeats_the_header_on_every_part():
    rows = "\n".join(f"| Row{n} | value-{n} | note {n} |" for n in range(1, 30))
    doc = "## 9.1 Classification matrix\n\n| Level | Handling | Retention |\n| --- | --- | --- |\n" + rows
    chunks = chunk_document(doc, source_name="t.pdf", chunk_size=400)
    tables = [c for c in chunks if c.metadata["kind"] == "table"]
    assert len(tables) > 1, "expected the table to split"
    assert all("Level | Handling" in part.text for part in tables)
    joined = "\n".join(part.text for part in tables)
    assert all(f"Row{n}" in joined for n in range(1, 30))


def test_split_parts_share_a_unit_id_and_are_numbered(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=400)
    parts = [c for c in chunks if c.metadata["unit_id"]]
    assert parts, "split parts must carry a unit_id for retrieval expansion"
    groups: dict[str, list] = {}
    for part in parts:
        groups.setdefault(part.metadata["unit_id"], []).append(part)
    for unit_id, group in groups.items():
        numbers = sorted(part.metadata["part"] for part in group)
        assert numbers == list(range(1, len(group) + 1)), f"{unit_id} parts not contiguous"
        assert all(part.metadata["parts"] == len(group) for part in group)


def test_unsplit_chunks_have_no_unit_id(series_doc):
    """`unit_id` is the expansion trigger, so a whole unit must not set it."""
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=1800)
    assert all(chunk.metadata["unit_id"] == "" for chunk in chunks)
    assert all(chunk.metadata["parts"] == 1 for chunk in chunks)


# --- metadata --------------------------------------------------------------


def test_metadata_carries_locator_fields(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=1800)
    series = next(c for c in chunks if c.metadata["kind"] == "series")
    assert series.metadata["doc_id"] == "MDS-CS-STD-003"
    assert series.metadata["clause"] == "7.2.1"
    assert series.metadata["parent_clause"] == "7.2"
    assert "7.2 SOC alert conditions" in series.metadata["heading"]


def test_chunk_indexes_are_dense_and_ordered(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=500)
    assert [c.metadata["chunk"] for c in chunks] == list(range(len(chunks)))
    assert all(c.metadata["source_name"] == "std.pdf" for c in chunks)


def test_heading_path_nests(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=1800)
    headings = [c.metadata["heading"] for c in chunks if c.metadata["heading"]]
    assert any(" > 7 Monitoring > " in heading for heading in headings)


# --- Arabic ----------------------------------------------------------------


def test_arabic_series_survives_and_folds_clause_numbers(arabic_doc):
    chunks = chunk_document(arabic_doc, source_name="std-ar.pdf", chunk_size=1800)
    series = [c for c in chunks if c.metadata["kind"] == "series"]
    assert series, "Arabic clause series not detected"
    assert series[0].metadata["clause"] == "7.2.1"
    assert series[0].metadata["parent_clause"] == "7.2"
    for digit in "\u0661\u0662\u0663\u0664\u0665":
        assert f"\u0667.\u0662.{digit}" in series[0].text


def test_bidi_controls_do_not_reach_the_index(arabic_doc):
    chunks = chunk_document(arabic_doc, source_name="std-ar.pdf", chunk_size=1800)
    joined = "".join(chunk.text for chunk in chunks)
    assert "\u200f" not in joined and "\u200e" not in joined


def test_arabic_and_english_editions_produce_matching_clause_keys(series_doc, arabic_doc):
    """The corpus numbers clauses identically across languages; keys must match."""
    english = chunk_document(series_doc, source_name="en.pdf", chunk_size=1800)
    arabic = chunk_document(arabic_doc, source_name="ar.pdf", chunk_size=1800)
    en_clause = next(c.metadata["clause"] for c in english if c.metadata["kind"] == "series")
    ar_clause = next(c.metadata["clause"] for c in arabic if c.metadata["kind"] == "series")
    assert en_clause == ar_clause == "7.2.1"


# --- DOCX shape ------------------------------------------------------------

DOCX_PATCHED = """# MDS-CS-STD-003 Secure Configuration Standard

## 7.2 SOC alert conditions

The SOC shall generate alerts for the following conditions:

- Failed authentication attempts exceeding five within fifteen minutes.

- Successful authentication from an unobserved geography.

- Privileged account creation outside an approved change window.

- Disabling of endpoint protection agents.

[table]
Severity | Internet-facing | Internal
Critical | 24 hours | 72 hours
High | 7 days | 14 days
[/table]"""


def test_docx_bullet_run_is_grouped_as_a_series():
    """Word stores list numbers in XML, so the loader emits bullets; group them."""
    chunks = chunk_document(DOCX_PATCHED, source_name="std.docx", chunk_size=1800)
    assert "series" in kinds(chunks), "bullet run was not grouped"
    series = next(c for c in chunks if c.metadata["kind"] == "series")
    assert series.text.count("- ") == 4


def test_docx_bracket_table_markers_are_recognised():
    chunks = chunk_document(DOCX_PATCHED, source_name="std.docx", chunk_size=1800)
    tables = [c for c in chunks if c.metadata["kind"] == "table"]
    assert len(tables) == 1
    assert "[table]" not in tables[0].text, "marker leaked into chunk text"
    assert "Critical" in tables[0].text


def test_docx_headings_reach_metadata():
    chunks = chunk_document(DOCX_PATCHED, source_name="std.docx", chunk_size=1800)
    assert any("7.2 SOC alert conditions" in c.metadata["heading"] for c in chunks)


def test_unstructured_docx_still_chunks_without_crashing():
    """Regression guard: the pre-patch loader shape must not raise."""
    flat = "MDS-CS-STD-003 Standard\nSome policy prose.\nMore prose.\n"
    chunks = chunk_document(flat, source_name="old.docx", chunk_size=1800)
    assert chunks and all(c.text for c in chunks)


# --- degenerate input ------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   \n\n  \n", "\u200f\u200e"])
def test_empty_input_yields_no_chunks(text):
    assert chunk_document(text, source_name="x.pdf", chunk_size=1800) == []


def test_single_paragraph_longer_than_chunk_size_is_split_on_sentences():
    doc = " ".join(f"Sentence number {n} about policy." for n in range(200))
    chunks = chunk_document(doc, source_name="x.pdf", chunk_size=500)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 700 for chunk in chunks)
    joined = " ".join(chunk.text for chunk in chunks)
    assert "Sentence number 199" in joined


def test_build_units_is_stable_on_headings_only():
    blocks = parse_blocks("# A\n\n## B\n\n### C\n")
    assert build_units(blocks)
