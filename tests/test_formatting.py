"""The slice of Markdown the drafter writes, and the noise it leaks."""

from __future__ import annotations

import pytest

from src.formatting import Block, parse, strip_source_markers, to_plain_text

MARKER = "【3】"  # 【3】
MARKER_ALT = "〔1〕"  # 〔1〕


# --- leaked source indices -------------------------------------------------


def test_a_leaked_source_index_is_removed():
    """The prompt numbers its sources; the reader never sees that numbering."""
    text = f"Logs are kept twelve (12) months (see §3.1.5){MARKER}."
    assert strip_source_markers(text) == "Logs are kept twelve (12) months (see §3.1.5)."


def test_the_other_bracket_style_is_removed_too():
    assert strip_source_markers(f"Retention is 12 months{MARKER_ALT}.") == "Retention is 12 months."


def test_the_labelled_marker_this_model_writes_is_removed():
    """Four of these in a row reached an answer measured on the held-out
    questionnaires. Stripping only the brackets left the word "source"
    standing in the middle of the sentence."""
    text = "Cryptographic controls apply【1†source】【2†source】 at rest."

    assert strip_source_markers(text) == "Cryptographic controls apply at rest."


def test_stripping_does_not_leave_a_gap_before_punctuation():
    assert strip_source_markers(f"Retention is 12 months {MARKER} .") == "Retention is 12 months."


def test_double_spaces_are_collapsed():
    assert strip_source_markers("Retention  is  12 months.") == "Retention is 12 months."


def test_text_without_markers_is_untouched():
    text = "Retention is 12 months, per §3.1.5."
    assert strip_source_markers(text) == text


def test_a_square_bracket_reference_is_left_alone():
    """Only the CJK bracket form is a model artefact; [1] may be real text."""
    text = "See annex [1] of the contract."
    assert strip_source_markers(text) == text


def test_markers_are_stripped_before_parsing():
    blocks = parse(f"- Retention is 12 months{MARKER}")
    assert blocks[0].text == "Retention is 12 months"


# --- structure -------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "kind", "text"),
    [
        ("Plain prose.", "paragraph", "Plain prose."),
        ("- A bullet", "bullet", "A bullet"),
        ("* A bullet", "bullet", "A bullet"),
        ("• A bullet", "bullet", "A bullet"),
        ("1. First", "number", "First"),
        ("2) Second", "number", "Second"),
        ("## A heading", "heading", "A heading"),
    ],
)
def test_line_kinds(line, kind, text):
    block = parse(line)[0]
    assert (block.kind, block.text) == (kind, text)


def test_numbered_items_keep_their_marker():
    assert parse("3. Third")[0].marker == "3"


def test_blank_lines_are_dropped():
    assert len(parse("One.\n\n\nTwo.")) == 2


def test_empty_text_produces_no_blocks():
    assert parse("") == [] and parse(None) == []


# --- emphasis --------------------------------------------------------------


def test_bold_spans_are_split_out():
    assert Block("paragraph", "Kept **twelve months** minimum.").spans == [
        ("Kept ", False),
        ("twelve months", True),
        (" minimum.", False),
    ]


def test_underscore_emphasis_is_recognised():
    assert Block("paragraph", "__Twelve__ months").spans[0] == ("Twelve", True)


def test_an_unclosed_marker_is_left_as_text():
    assert Block("paragraph", "A ** stray marker").spans == [("A ** stray marker", False)]


def test_underscores_inside_an_identifier_are_not_emphasis():
    """MAX_ANSWER_ATTEMPTS must not become MAXANSWERATTEMPTS in bold."""
    spans = Block("paragraph", "Set MAX_ANSWER_ATTEMPTS to 3.").spans
    assert spans == [("Set MAX_ANSWER_ATTEMPTS to 3.", False)]


# --- flat rendering --------------------------------------------------------


def test_plain_text_keeps_list_structure_and_drops_emphasis():
    rendered = to_plain_text("Controls:\n- **Encryption** at rest\n1. First step")
    assert rendered == "Controls:\n• Encryption at rest\n1. First step"


def test_plain_text_of_an_empty_answer_is_empty():
    assert to_plain_text("") == ""


# --- what goes into a questionnaire's cell -----------------------------------
#
# A spreadsheet cell and a Word table cell show text, not Markdown. Written as
# the drafter wrote it, the NMDC questionnaire went back to its customer with
# "**Identifiers** –" in a cell, asterisks and all.


def test_a_cell_gets_no_markdown_markers():
    from src.formatting import to_cell_text

    written = to_cell_text("**Yes.** T2 encrypts data at rest.\n\n**Identifiers** – name, ID number")
    assert "**" not in written
    assert written == "Yes. T2 encrypts data at rest.\n\nIdentifiers – name, ID number"


def test_a_cell_keeps_its_lists_and_paragraph_breaks():
    from src.formatting import to_cell_text

    written = to_cell_text(
        "T2 requires:\n\n- multi-factor authentication\n* quarterly access reviews\n"
        "1. one numbered item\n\n## Retention\nData is kept for 90 days."
    )
    assert written == (
        "T2 requires:\n\n• multi-factor authentication\n• quarterly access reviews\n"
        "1. one numbered item\n\nRetention\nData is kept for 90 days."
    )


def test_a_cell_keeps_arabic_and_plain_text_as_it_is():
    from src.formatting import to_cell_text

    assert to_cell_text("نعم، يتم تشفير البيانات.") == "نعم، يتم تشفير البيانات."
    assert to_cell_text("Yes. 2 * 3 = 6, and a_b stays.") == "Yes. 2 * 3 = 6, and a_b stays."
