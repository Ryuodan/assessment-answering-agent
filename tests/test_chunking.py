"""Step 1 — structure-aware chunking.

The property under test is not "chunks are the right size". It is: **no numbered
series and no table ever loses a member**, whatever the chunk size. That is the
defect the whole change exists to fix, so it is asserted at several chunk sizes
rather than one.
"""

from __future__ import annotations

import pytest

from src.chunking import (
    has_substance,
    build_units,
    chunk_document,
    clause_range,
    parent_clause,
    parse_blocks,
    strip_bidi,
)

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


def test_table_rows_are_never_separated_from_their_header(series_doc):
    """Tables now sit inside their section, but a header must reach every row."""
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=400)
    with_rows = [c for c in chunks if "| Critical |" in c.text or "| Low |" in c.text]
    assert with_rows
    assert all("Severity" in chunk.text for chunk in with_rows)


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


def test_every_chunk_carries_a_unit_id(series_doc):
    """v2 assigns unit_id to every unit, not only split ones, so expansion works."""
    for size in (400, 1800):
        chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=size)
        assert all(chunk.metadata["unit_id"] for chunk in chunks)


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


def test_a_unit_that_fits_is_a_single_part(series_doc):
    """`parts == 1` is the signal that nothing was split, not an absent unit_id."""
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=4000)
    assert all(chunk.metadata["parts"] == 1 for chunk in chunks)


# --- metadata --------------------------------------------------------------


def test_metadata_carries_locator_fields(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=1800)
    series = next(c for c in chunks if c.metadata["kind"] == "series")
    assert series.metadata["doc_id"] == "MDS-CS-STD-003"
    assert series.metadata["clause_start"] == "7"
    assert series.metadata["clause_end"] == "8"
    assert series.metadata["item_count"] >= 12
    assert "7 Monitoring" in series.metadata["heading"]


def test_clause_range_reports_the_span_not_just_the_first(series_doc):
    """A chunk labelled only by its first clause makes partial answers look audited."""
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=1800)
    spanning = [c for c in chunks if c.metadata["clause_end"] != c.metadata["clause_start"]]
    assert spanning, "expected at least one multi-clause chunk"


def test_clause_range_orders_numerically_not_lexically():
    assert clause_range(["7.9", "7.10", "7.2"]) == ("7.2", "7.10")


def test_chunk_indexes_are_dense_and_ordered(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=500)
    assert [c.metadata["chunk"] for c in chunks] == list(range(len(chunks)))
    assert all(c.metadata["source_name"] == "std.pdf" for c in chunks)


def test_heading_path_nests(series_doc):
    chunks = chunk_document(series_doc, source_name="std.pdf", chunk_size=1800)
    headings = [c.metadata["heading"] for c in chunks if c.metadata["heading"]]
    assert any("7 Monitoring" in heading for heading in headings)


# --- Arabic ----------------------------------------------------------------


def test_arabic_series_survives_and_folds_clause_numbers(arabic_doc):
    chunks = chunk_document(arabic_doc, source_name="std-ar.pdf", chunk_size=1800)
    series = [c for c in chunks if c.metadata["kind"] == "series"]
    assert series, "Arabic clause series not detected"
    assert series[0].metadata["clause_start"] == "7"
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
    en_clause = next(c.metadata["clause_start"] for c in english if c.metadata["kind"] == "series")
    ar_clause = next(c.metadata["clause_start"] for c in arabic if c.metadata["kind"] == "series")
    assert en_clause == ar_clause == "7"


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
    joined = "\n".join(c.text for c in chunks)
    assert "[table]" not in joined, "marker leaked into chunk text"
    assert "Critical" in joined and "24 hours" in joined


def test_docx_headings_reach_metadata():
    chunks = chunk_document(DOCX_PATCHED, source_name="std.docx", chunk_size=1800)
    assert any("SOC alert conditions" in c.metadata["heading"] for c in chunks)


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

# --- coalescing ------------------------------------------------------------

# The shape that caused the regression: "3.4 End or Termination of Employment"
# holds 3.4.1-3.4.3 as plain clauses, then 3.4.4 opens its own heading. Sectioning
# alone puts the two in different chunks, and the last-working-day rule in 3.4.3
# is then invisible to a question that ranks 3.4.4 first.
TERMINATION_DOC = """## 3.4 End or Termination of Employment

- 3.4.1 Define employment termination procedures covering cybersecurity requirements.
- 3.4.2 The human resources director must inform the relevant units on termination.
- 3.4.3 Ensure that all assets are returned, and personnel access rights are cancelled
  on their last working day and prior to obtaining the necessary clearance.

## 3.4.4 Post-Employment Access Monitoring

After an employee's termination, cybersecurity teams must ensure all credentials
and access rights are revoked, monitor for unauthorised access attempts, and audit
the last 30 days of access logs to verify security compliance.
"""


def test_adjacent_sections_are_merged_into_one_retrievable_chunk():
    """3.4.3 and 3.4.4 must arrive together, or 'how quickly' has no answer."""
    chunks = chunk_document(TERMINATION_DOC, source_name="hr.pdf", chunk_size=1800)

    holding = [chunk for chunk in chunks if "last working day" in chunk.text]
    assert len(holding) == 1
    assert "Post-Employment Access Monitoring" in holding[0].text
    assert holding[0].metadata["clause_start"] == "3.4"
    assert holding[0].metadata["clause_end"] == "3.4.4"


def test_merging_stops_at_the_chunk_size():
    """Coalescing fills chunks; it must not concatenate a whole document into one."""
    prose = "Policy prose that runs on for a while. " * 20
    section = """## {n}. Section {n}

{prose}

"""
    document = "".join(section.format(n=n, prose=prose) for n in range(1, 15))

    chunks = chunk_document(document, source_name="long.pdf", chunk_size=1800)

    assert len(chunks) > 1
    # `chunk_size` is a soft ceiling: a runt tail may be folded back into its
    # predecessor, which _absorb_tiny_tail bounds at 1.3x.
    assert max(len(chunk.text) for chunk in chunks) <= 1800 * 1.3


def test_small_documents_still_produce_a_chunk():
    document = """## 1. Purpose

This policy is short.
"""
    chunks = chunk_document(document, source_name="tiny.pdf", chunk_size=1800)
    assert len(chunks) == 1
    assert "This policy is short." in chunks[0].text


# --- hard ceiling ----------------------------------------------------------


def test_a_single_giant_table_cell_is_split():
    """One cell holding a whole section produced a 13,000-character chunk."""
    cell = "Requirements for cybersecurity incident management shall include the following. " * 90
    document = "## 3. Incident Management\n\n| Control | Requirement |\n| --- | --- |\n| 3-1 | " + cell + " |\n"

    chunks = chunk_document(document, source_name="ecc.pdf", chunk_size=1800)

    assert max(len(chunk.text) for chunk in chunks) <= 1800 * 1.3


def test_unpunctuated_prose_is_still_bounded():
    """A clause with no sentence terminator has nothing to split on."""
    document = "## 5. Definitions\n\n" + ("word " * 2000)

    chunks = chunk_document(document, source_name="long.pdf", chunk_size=1800)

    assert max(len(chunk.text) for chunk in chunks) <= 1800 * 1.3


def test_hard_wrap_prefers_a_clean_boundary():
    from src.chunking import _hard_wrap

    text = "First sentence here. " + ("x" * 40) + ". Second sentence follows."
    pieces = _hard_wrap(text, 60)

    assert all(len(piece) <= 60 for piece in pieces)
    assert "".join(pieces).replace(" ", "") == text.replace(" ", "")


def test_hard_wrap_leaves_short_text_alone():
    from src.chunking import _hard_wrap

    assert _hard_wrap("short enough", 100) == ["short enough"]


# --- a heading is not a retrievable section --------------------------------


def _texts(doc: str, size: int = 1800) -> list[str]:
    from src.chunking import chunk_document
    return [c.text for c in chunk_document(doc, source_name="x.pdf", chunk_size=size)]


def test_a_heading_followed_by_a_heading_is_not_its_own_chunk():
    """105 chunks in the real corpus were nothing but their own title."""
    doc = (
        "## Contents\n\n"
        "| 1. Summary | 4 |\n|---|---|\n| 2. Scope | 6 |\n\n"
        "## 1. Summary\n\n" + ("The position is set out as follows. " * 30) + "\n"
    )
    chunks = _texts(doc)
    assert not any(c.strip().startswith("##") and len(c) < 60 for c in chunks)
    assert any("Contents" in c and "Summary" in c for c in chunks)


def test_an_arabic_heading_run_is_absorbed_the_same_way():
    doc = (
        "## المحتويات\n\n"
        "## 1. المقدمة\n\n"
        + ("تهدف هذه السياسة إلى تحديد المتطلبات. " * 20)
        + "\n"
    )
    chunks = _texts(doc)
    assert len(chunks) == 1
    assert "المحتويات" in chunks[0]


def test_a_trailing_runt_is_folded_backwards():
    doc = ("## A\n\n" + ("Body text here. " * 120) + "\n\n## Z\n")
    assert not any(c.strip() == "## Z" for c in _texts(doc))


def test_a_real_short_section_is_still_kept_whole():
    """The cap must not glue two substantial sections into one chunk."""
    body = "Requirements are enumerated below in detail. " * 45
    doc = f"## 1. First\n\n{body}\n\n## 2. Second\n\n{body}\n"
    assert len(_texts(doc)) >= 2


def test_a_heading_before_an_oversized_block_leads_it_rather_than_standing_alone():
    """92 of 98 short chunks in the real index were 'part 1 of N': a heading
    flushed on its own because the block after it had to be split."""
    body = "The controller shall document each processing activity in full. " * 120
    doc = f"## 4.1 Data\n\n{body}\n"
    chunks = _texts(doc, size=800)

    assert len(chunks) > 1, "fixture must force a split"
    assert not any(len(c) < 150 for c in chunks), f"orphan: {[c for c in chunks if len(c) < 150]}"
    assert chunks[0].lstrip().startswith("## 4.1 Data")


def test_an_arabic_heading_before_an_oversized_block_behaves_the_same():
    body = "يجب على المسؤول توثيق كل نشاط من أنشطة المعالجة بشكل كامل ومفصل. " * 60
    doc = f"## 2.3 التعريفات\n\n{body}\n"
    chunks = _texts(doc, size=800)

    assert len(chunks) > 1
    assert not any(len(c) < 150 for c in chunks)
    assert "التعريفات" in chunks[0]


def test_an_oversized_block_with_nothing_before_it_still_splits():
    body = "Each requirement is stated once and applies to every system. " * 120
    assert len(_texts(body, size=800)) > 1


def test_a_nearly_full_group_is_not_folded_into_an_unsplittable_block():
    """Rescuing a runt heading is right; folding in 1.7 KB of pending prose is
    not — that traded an undersized chunk for a 3.5 KB one."""
    from src.chunking import chunk_document

    filler = "Each control is described in a full sentence of prose. " * 30
    wide_row = "| " + " | ".join("a very long cell value indeed" for _ in range(40)) + " |"
    doc = f"## 9.1.2 Controls\n\n{filler}\n\n| A | B |\n|---|---|\n{wide_row}\n"

    chunks = chunk_document(doc, source_name="x.pdf", chunk_size=1800)
    assert all(len(c.text) <= 1800 * 1.3 for c in chunks), \
        f"oversize: {sorted(len(c.text) for c in chunks)}"


# --- two numbering conventions ---------------------------------------------
#
# T2's policies number clauses with dots; the NCA and SDAIA publications number
# controls with dashes. The ECC implementation guide — the largest document in
# this corpus at 840 chunks — uses 352 dashed control ids and not one dotted
# clause, so recognising only dots left every chunk of it with no clause at
# all: citations gave a file name and no reference, and the check that a named
# clause is supported could not evaluate one of them.


def test_a_dashed_control_id_has_a_depth_and_a_parent():
    from src.chunking import clause_depth, parent_clause

    assert clause_depth("1-1-1") == 3
    assert parent_clause("1-1-1") == "1-1"
    assert parent_clause("1-1") == "1"


def test_the_separator_the_document_used_is_kept():
    """An assessor looks the identifier up in the document; 1.1.1 is not there."""
    from src.chunking import parent_clause

    assert parent_clause("3.4.1") == "3.4"
    assert "-" in parent_clause("1-1-1")


def test_dashed_ids_sort_numerically():
    from src.chunking import clause_range

    assert clause_range(["1-1-10", "1-1-2", "1-1-9"]) == ("1-1-2", "1-1-10")


@pytest.mark.parametrize(("row", "expected"), [
    ("| 1-1-1     | The entity shall document its strategy. |", "1-1-1"),
    ("| **2-3-4** | Bold, as a converter emits it. |", "2-3-4"),
    ("|  1-2-3-4  | Four groups. |", "1-2-3-4"),
    ("| 2024-2025 | A year range is not a control. |", None),
    ("| 1-2 | Two groups could be a range. |", None),
    ("Prose mentioning 1-1-1 mid-sentence.", None),
])
def test_only_an_unambiguous_control_id_in_the_first_cell_counts(row, expected):
    from src.chunking import row_control_id

    assert row_control_id(row) == expected


def test_a_control_table_chunk_carries_the_range_of_rows_it_holds():
    """Citing the first of nine rows would look precise and not be."""
    from src.chunking import chunk_document

    rows = "\n".join(
        f"| 1-1-{n} | The entity shall satisfy requirement number {n}. " + "Detail. " * 40 + "|"
        for n in range(1, 10)
    )
    # No numbered heading, so the range comes from the rows alone. A heading
    # that carries its own clause widens the span on purpose — see below.
    doc = f"## Governance\n\n| Control | Requirement |\n|---|---|\n{rows}\n"

    chunks = chunk_document(doc, source_name="ecc.pdf", chunk_size=1800)
    ranged = [c for c in chunks if c.metadata.get("clause_start")]

    assert ranged, "no chunk picked up a control id"
    first = ranged[0].metadata
    assert first["clause_start"].startswith("1-1-")
    assert first["clause_end"].startswith("1-1-")
    assert first["clause_start"] != first["clause_end"], "a multi-row chunk cited one row"


def test_a_numbered_heading_does_not_narrow_the_table_it_introduces():
    """The section is "1"; the rows are 1-1-1 upward. The chunk holding the
    rows must be cited by the rows, not by the section they sit under."""
    from src.chunking import chunk_document

    rows = "\n".join(
        f"| 1-1-{n} | Requirement {n}. " + "Detail. " * 40 + "|" for n in range(1, 6)
    )
    doc = f"## 1 Governance\n\n| Control | Requirement |\n|---|---|\n{rows}\n"

    table = next(c for c in chunk_document(doc, source_name="ecc.pdf", chunk_size=1800)
                 if c.metadata.get("kind") == "table")

    assert table.metadata["clause_start"] == "1-1-1"
    assert table.metadata["clause_end"] == "1-1-5"


def test_a_dotted_document_is_unaffected():
    """The corpus is mixed; adding one convention must not disturb the other."""
    from src.chunking import chunk_document

    doc = "## 3.4 Access\n\n" + "\n".join(
        f"- 3.4.{n} Access is reviewed at defined intervals. " + "Detail. " * 20
        for n in range(1, 8)
    )
    chunks = chunk_document(doc, source_name="policy.pdf", chunk_size=1800)
    starts = [c.metadata.get("clause_start") for c in chunks if c.metadata.get("clause_start")]

    assert starts and all("." in s for s in starts)


# --- table padding ---------------------------------------------------------


def test_alignment_padding_is_stripped_but_nothing_else():
    """Docling pads every cell to its column's widest; that is 47% of the
    corpus's table text, and it is charged to the chunk budget, the embedding
    and the drafting prompt alike."""
    from src.chunking import compact_table

    raw = [
        "| Asset Type        | All systems   | Notes                    |",
        "|-------------------|---------------|--------------------------|",
        "| Operating Systems | 3 Monthly     | see 3.1.1                |",
    ]
    out = compact_table(raw)

    assert out == [
        "| Asset Type | All systems | Notes |",
        "| --- | --- | --- |",
        "| Operating Systems | 3 Monthly | see 3.1.1 |",
    ]
    assert len(out) == len(raw), "a row must never be dropped"
    assert [line.count("|") for line in out] == [line.count("|") for line in raw]


def test_padding_is_all_that_a_compacted_table_loses():
    """Asserted as a property, so the transform cannot quietly start editing
    content: the non-whitespace characters must be identical, in order."""
    import re

    from src.chunking import compact_table

    raw = [
        "| مستوى الخطورة   | التعريف                | الوقت    |",
        "|------------------|------------------------|----------|",
        "| كارثي            | فشل كارثي في الخدمات   | فوري     |",
        "| Critical (حرج)   | Gross threat -- image  | 2 hours  |",
    ]
    squash = lambda rows: re.sub(r"\s+", "", "".join(rows))  # noqa: E731

    body_raw = [r for r in raw if "---" not in r]
    body_new = [r for r in compact_table(raw) if set(r) - set("| -")]

    assert squash(body_new) == squash(body_raw)


def test_an_empty_cell_survives_compaction():
    """Empty cells carry column position. Losing one shifts every later cell."""
    from src.chunking import compact_table

    out = compact_table(["|          | Systems   | Systems   |"])
    assert out == ["|  | Systems | Systems |"]
    assert out[0].count("|") == 4


def test_a_table_that_only_padding_made_oversized_stays_whole():
    """The defect this was found through: a six-row frequency table measured
    2,000 characters padded and 700 unpadded, so it was split into four pieces
    and the drafter never saw a whole row."""
    header = "| Asset Type        | All systems       | Internet-facing   | Internal          |"
    sep = "|-------------------|-------------------|-------------------|-------------------|"
    rows = [
        f"| {name:17s} | 3 Monthly         | Monthly           | 3 Months*         |"
        for name in ("Operating Systems", "Databases", "Network Devices", "Applications")
    ]
    doc = "## 3.1 General\n\n" + "\n".join([header, sep, *rows])

    chunks = chunk_document(doc, source_name="vuln.pdf", chunk_size=1800)
    holding = [c for c in chunks if "Applications" in c.text]

    assert len(holding) == 1, "the table was split despite fitting once de-padded"
    assert "Operating Systems" in holding[0].text, "the whole table belongs together"


def test_a_split_table_carries_the_row_that_names_the_columns():
    """Docling flattens a merged cell by repeating it once per column spanned,
    so row one can be `| | Systems | Systems | ... |` — which names nothing. A
    piece carrying only that header is unreadable."""
    rows = "\n".join(
        f"| Row {n} | 3 Monthly | Monthly | 3 Months | " + "pad " * 30 + "|"
        for n in range(1, 12)
    )
    doc = (
        "## 3.1 General\n\n"
        "|  | Systems | Systems | Systems | Systems |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Asset Type | All systems | Internet-facing | Internal | Cloud |\n"
        f"{rows}\n"
    )
    tables = [c for c in chunk_document(doc, source_name="v.pdf", chunk_size=900)
              if c.metadata["kind"] == "table"]

    assert len(tables) > 1, "expected the table to split"
    assert all("Asset Type | All systems" in t.text for t in tables)


def test_an_ordinary_header_is_not_padded_out_with_body_rows():
    """The carry-down rule must fire only on a spanned label, or a normal table
    would lose its first rows into every piece's header."""
    rows = "\n".join(f"| Row{n} | value-{n} | note {n} |" for n in range(1, 40))
    doc = "## 9.1 Matrix\n\n| Level | Handling | Retention |\n| --- | --- | --- |\n" + rows
    tables = [c for c in chunk_document(doc, source_name="t.pdf", chunk_size=400)
              if c.metadata["kind"] == "table"]

    assert len(tables) > 1
    assert sum(t.text.count("Row1 |") for t in tables) == 1, "a body row became a header"


def test_a_table_is_cited_by_the_clause_that_introduces_it():
    """The clause ending in a colon owns the table, not the nearest one.

    Docling emits a floating table after the whole run of headings on its page,
    so the vulnerability-frequency table arrived six blocks below its own
    clause and directly beneath an unrelated one. The chunk holding it was
    cited §3.1.7-3.1.8 -- two clauses about remediation planning -- for a table
    of scanning frequencies.
    """
    from src.chunking import parse_blocks

    filler = "Detail follows here for the reader. " * 8
    doc = (
        "### 3.1 General\n\n"
        "#### 3.1.1 Vulnerabilities must be scanned as follows:\n\n"
        f"#### 3.1.2 Define systems subject to assessment. {filler}\n\n"
        f"#### 3.1.6 Remedy all vulnerabilities per their severity. {filler}\n\n"
        "| Asset Type | All systems | Internet-facing |\n"
        "| --- | --- | --- |\n"
        "| Operating Systems | 3 Monthly | Monthly |\n\n"
        f"#### 3.1.7 Develop a vulnerability management plan. {filler}\n"
    )

    table = next(b for b in parse_blocks(doc) if b.kind == "table")
    assert table.clause == "3.1.1", "the colon clause introduces the table"

    holding = next(c for c in chunk_document(doc, source_name="v.pdf", chunk_size=700)
                   if "Operating Systems" in c.text)
    assert holding.metadata["clause_start"] == "3.1.1"


def test_a_control_table_labels_itself_and_is_not_reintroduced():
    """The introducing clause must not widen a table that names its own rows."""
    from src.chunking import _introduced_by, parse_blocks

    doc = (
        "## 1 Governance applies as follows:\n\n"
        "| Control | Requirement |\n|---|---|\n"
        "| 1-1-1 | The entity shall define a strategy. |\n"
        "| 1-1-5 | The entity shall review it annually. |\n"
    )
    blocks = parse_blocks(doc)
    table = next(b for b in blocks if b.kind == "table")

    assert table.clause is None, "row control ids are the table's own labels"
    assert _introduced_by(blocks, table.lines) is None


# --- chunks that would index nothing ---------------------------------------


def test_a_cover_page_of_only_an_image_is_not_indexed():
    """Docling marks every figure with a placeholder, so a cover page that is
    nothing but a logo became a chunk whose whole body was that placeholder --
    and it embedded to something, so searching "logo" returned an empty card."""
    doc = "<!-- image -->\n\n<!-- image -->\n\n## 1 Scope\n\nRetention is 90 days.\n"
    chunks = chunk_document(doc, source_name="p.pdf", chunk_size=1800)

    assert chunks, "the real content must survive"
    assert all(has_substance(c.text) for c in chunks)
    assert any("90 days" in c.text for c in chunks)


def test_a_document_of_nothing_but_images_indexes_nothing():
    chunks = chunk_document("<!-- image -->\n\n<!-- image -->\n", source_name="p.pdf")
    assert chunks == []


def test_a_stranded_heading_is_merged_forward_not_dropped():
    """Dropping it lost the heading outright: the part that followed carried the
    stem only because it was part 2, and renumbering it to part 1 stopped the
    stem being prepended at all."""
    filler = "Detail follows for the reader. " * 40
    doc = f"### 7.4 Hiring and training of employees\n\n{filler}\n"
    chunks = chunk_document(doc, source_name="p.pdf", chunk_size=700)

    joined = "\n".join(c.text for c in chunks)
    assert "Hiring and training" in joined, "the heading must survive somewhere"
    heading_only = [c for c in chunks if c.text.strip() == "### 7.4 Hiring and training of employees"]
    assert not heading_only, "a heading with no body must not be its own chunk"


def test_a_clause_rendered_as_a_heading_is_never_mistaken_for_a_stranded_one():
    """Docling renders numbered clauses as headings, so whole pages of real
    requirements arrive as heading blocks. Judging "heading only" by block kind
    alone deleted 102 words of policy from one document."""
    clauses = "\n\n".join(
        f"### 3.1.{n} It is prohibited to bypass the protection systems, "
        f"including anti-virus programs and firewalls, without prior authorisation."
        for n in range(1, 9)
    )
    chunks = chunk_document(clauses, source_name="p.pdf", chunk_size=700)

    joined = " ".join(c.text for c in chunks)
    for n in range(1, 9):
        assert f"3.1.{n}" in joined, f"clause 3.1.{n} was dropped"
    assert "anti-virus" in joined


def test_nothing_a_document_says_is_lost_to_the_filter():
    """The property, asserted directly: every word of the source survives."""
    import re

    doc = (
        "<!-- image -->\n\n## Policy\n\n<!-- image -->\n\n"
        "### 1 Scope\n\n### 1.1 Retention\n\nRecords are kept for 90 days.\n\n"
        "<!-- image -->\n\n### 1.2 Deletion\n\nRecords are destroyed after 7 years.\n"
    )
    chunks = chunk_document(doc, source_name="p.pdf", chunk_size=1800)

    words = lambda t: set(re.findall(r"[^\W_]+", t.lower()))  # noqa: E731
    assert words(doc) <= words("\n".join(c.text for c in chunks))
