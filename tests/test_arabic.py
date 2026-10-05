"""Arabic and RTL handling.

Arabic fails differently from English, and it fails silently: a leading RLM is
not whitespace, so it defeats every `^\\s*` anchor while English keeps working.
These tests pin the specific behaviours that were observed to break.
"""

from __future__ import annotations

import pytest

from src.chunking import chunk_document, fold_digits, match_clause, parse_blocks, strip_bidi

RLM = "\u200f"


def kinds(blocks) -> dict:
    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
    return counts


# --- normalisation ---------------------------------------------------------


@pytest.mark.parametrize("control", ["\u200f", "\u200e", "\u202b", "\u202c", "\u2066", "\u061c"])
def test_bidi_controls_are_stripped(control):
    assert strip_bidi(f"{control}\u0645\u0631\u062d\u0628\u0627{control}") == "\u0645\u0631\u062d\u0628\u0627"


def test_bidi_control_does_not_hide_a_clause():
    """An RLM is not whitespace, so `^\\s*` alone would never reach the number."""
    blocks = parse_blocks(f"{RLM}\u0667.\u0662.\u0661 \u0646\u0635 \u0627\u0644\u0628\u0646\u062f.")
    assert [b.clause for b in blocks if b.kind == "clause"] == ["7.2.1"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("\u0667\u0662\u0661", "721"), ("\u06f5\u06f0", "50"), ("7.2", "7.2"), ("\u0667\u066b\u0662", "7\u066b2")],
)
def test_fold_digits(raw, expected):
    assert fold_digits(raw) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("\u0667.\u0662.\u0661 \u0646\u0635", "7.2.1"),
        ("\u0667\u066b\u0662\u066b\u0661 \u0646\u0635", "7.2.1"),  # Arabic decimal separator
        ("\u0627\u0644\u0645\u0627\u062f\u0629 \u0665 \u0645\u0628\u0627\u062f\u0626", "5"),  # المادة 5
        ("\u0627\u0644\u0628\u0646\u062f \u0667\u066b\u0662 \u0646\u0635", "7.2"),  # البند 7.2
        (
            "\u0661) \u0627\u0644\u0625\u0628\u0644\u0627\u063a \u062e\u0644\u0627\u0644 \u0667\u0662 \u0633\u0627\u0639\u0629",
            "1",
        ),
    ],
)
def test_arabic_clause_forms(line, expected):
    assert match_clause(line) == expected


# --- structure -------------------------------------------------------------


def test_arabic_series_keeps_stem_with_items():
    doc = f"""# MDS-CS-STD-004 \u0645\u0639\u064a\u0627\u0631 \u0627\u0644\u0645\u0631\u0627\u0642\u0628\u0629

## \u0667 \u0627\u0644\u0645\u0631\u0627\u0642\u0628\u0629

{RLM}\u0667\u066b\u0661 \u064a\u062c\u0628 \u0627\u0633\u062a\u064a\u0639\u0627\u0628 \u0627\u0644\u0623\u062d\u062f\u0627\u062b.
{RLM}\u0667\u066b\u0662 \u064a\u062c\u0628 \u0625\u0635\u062f\u0627\u0631 \u062a\u0646\u0628\u064a\u0647 \u0644\u0644\u062d\u0627\u0644\u0627\u062a \u0627\u0644\u062a\u0627\u0644\u064a\u0629:
{RLM}\u0667\u066b\u0662\u066b\u0661 \u0627\u0644\u0645\u0635\u0627\u062f\u0642\u0629 \u0627\u0644\u0637\u0627\u0631\u0626\u0629.
{RLM}\u0667\u066b\u0662\u066b\u0662 \u062d\u0633\u0627\u0628 \u0625\u062f\u0627\u0631\u064a \u0645\u0634\u062a\u0631\u0643.
{RLM}\u0667\u066b\u0662\u066b\u0663 \u062a\u062c\u0627\u0648\u0632 \u0645\u0633\u0627\u0631 \u0627\u0644\u0648\u0635\u0648\u0644.
{RLM}\u0667\u066b\u0663 \u064a\u062c\u0628 \u0627\u0644\u0625\u0642\u0631\u0627\u0631 \u062e\u0644\u0627\u0644 \u062f\u0642\u0627\u0626\u0642.
"""
    chunks = chunk_document(doc, source_name="ar.pdf", chunk_size=1800)
    series = [c for c in chunks if c.metadata["kind"] == "series"]
    assert len(series) == 1, "the stem was separated from the items it introduces"
    assert series[0].metadata["clause_start"] == "7"
    assert series[0].metadata["clause_end"] == "7.3"
    assert series[0].metadata["item_count"] == 6


def test_arabic_abjad_list_markers_are_items():
    """أ) ب) ج) order a list the same way (a) (b) (c) does."""
    doc = """\u0627\u0644\u0645\u0627\u062f\u0629 \u0665 \u0645\u0628\u0627\u062f\u0626 \u0627\u0644\u0645\u0639\u0627\u0644\u062c\u0629

\u064a\u062c\u0628 \u0623\u0646 \u062a\u0643\u0648\u0646 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a:
\u0623) \u0645\u0639\u0627\u0644\u062c\u0629 \u0628\u0635\u0648\u0631\u0629 \u0645\u0634\u0631\u0648\u0639\u0629\u061b
\u0628) \u0645\u062c\u0645\u0648\u0639\u0629 \u0644\u0623\u063a\u0631\u0627\u0636 \u0645\u062d\u062f\u062f\u0629\u061b
\u062c) \u0643\u0627\u0641\u064a\u0629 \u0648\u0630\u0627\u062a \u0635\u0644\u0629\u061b
\u062f) \u062f\u0642\u064a\u0642\u0629 \u0648\u0645\u062d\u062f\u062b\u0629\u061b
\u0647\u0640) \u0645\u062d\u0641\u0648\u0638\u0629 \u0644\u0645\u062f\u0629 \u0645\u062d\u062f\u062f\u0629\u061b
\u0648) \u0645\u0639\u0627\u0644\u062c\u0629 \u0628\u0637\u0631\u064a\u0642\u0629 \u0622\u0645\u0646\u0629.
"""
    assert kinds(parse_blocks(doc)).get("listitem") == 6


def test_arabic_bullets_group_as_a_series():
    doc = """## \u0636\u0628\u0637 \u0627\u0644\u0648\u0635\u0648\u0644

\u064a\u062c\u0628 \u0627\u0633\u062a\u064a\u0641\u0627\u0621 \u0627\u0644\u062a\u0627\u0644\u064a:

- \u0627\u0644\u0645\u0635\u0627\u062f\u0642\u0629 \u0645\u062a\u0639\u062f\u062f\u0629 \u0627\u0644\u0639\u0648\u0627\u0645\u0644.
- \u062d\u0633\u0627\u0628\u0627\u062a \u0645\u0633\u0645\u0627\u0629 \u0641\u0631\u064a\u062f\u0629.
- \u0645\u0631\u0627\u062c\u0639\u0627\u062a \u0648\u0635\u0648\u0644 \u0631\u0628\u0639 \u0633\u0646\u0648\u064a\u0629.
"""
    chunks = chunk_document(doc, source_name="ar.pdf", chunk_size=1800)
    assert any(c.metadata["kind"] == "series" for c in chunks)
    assert max(c.metadata["item_count"] for c in chunks) == 3


def test_arabic_table_survives():
    doc = """## \u0667\u066b\u0664 \u0646\u0648\u0627\u0641\u0630 \u0627\u0644\u0645\u0639\u0627\u0644\u062c\u0629

| \u0627\u0644\u062e\u0637\u0648\u0631\u0629 | \u062e\u0627\u0631\u062c\u064a | \u062f\u0627\u062e\u0644\u064a |
| --- | --- | --- |
| \u062d\u0631\u062c\u0629 | \u0662\u0664 \u0633\u0627\u0639\u0629 | \u0667\u0662 \u0633\u0627\u0639\u0629 |
| \u0639\u0627\u0644\u064a\u0629 | \u0667 \u0623\u064a\u0627\u0645 | \u0661\u0664 \u064a\u0648\u0645\u0627\u064b |
"""
    chunks = chunk_document(doc, source_name="ar.pdf", chunk_size=1800)
    joined = "\n".join(c.text for c in chunks)
    assert "\u062d\u0631\u062c\u0629" in joined and "\u0639\u0627\u0644\u064a\u0629" in joined
    assert chunks[0].metadata["clause_start"] == "7.4"


def test_mixed_arabic_and_latin_clause_numbering():
    """Arabic prose is routinely numbered with Latin digits."""
    doc = """# MDS-CS-POL-002 \u0633\u064a\u0627\u0633\u0627\u062a

## 9 \u062d\u0645\u0627\u064a\u0629 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a

9.1 \u062a\u0642\u0639 \u0627\u0644\u0627\u0644\u062a\u0632\u0627\u0645\u0627\u062a \u0627\u0644\u062a\u0627\u0644\u064a\u0629:
9.1.1 \u0627\u0644\u0645\u0633\u0627\u0621\u0644\u0629 \u0639\u0646 \u0627\u0644\u0627\u0645\u062a\u062b\u0627\u0644.
9.1.2 \u0627\u0644\u0627\u062d\u062a\u0641\u0627\u0638 \u0628\u0633\u062c\u0644 \u0627\u0644\u0645\u0639\u0627\u0644\u062c\u0629.
"""
    chunks = chunk_document(doc, source_name="ar.pdf", chunk_size=1800)
    assert chunks[0].metadata["doc_id"] == "MDS-CS-POL-002"
    assert chunks[0].metadata["clause_start"] == "9"


def test_arabic_and_english_editions_share_clause_keys():
    english = chunk_document("## 7.2 Alerts\n\n7.2.1 First.\n7.2.2 Second.\n", source_name="en.pdf", chunk_size=1800)
    arabic = chunk_document(
        f"## \u0667\u066b\u0662 \u0627\u0644\u062a\u0646\u0628\u064a\u0647\u0627\u062a\n\n{RLM}\u0667\u066b\u0662\u066b\u0661 \u0627\u0644\u0623\u0648\u0644.\n{RLM}\u0667\u066b\u0662\u066b\u0662 \u0627\u0644\u062b\u0627\u0646\u064a.\n",
        source_name="ar.pdf",
        chunk_size=1800,
    )
    assert english[0].metadata["clause_start"] == arabic[0].metadata["clause_start"] == "7.2"
    assert english[0].metadata["clause_end"] == arabic[0].metadata["clause_end"] == "7.2.2"


# --- visual-order extraction ----------------------------------------------


def test_clause_number_stranded_at_line_end_is_recovered():
    """Some PDF text layers store Arabic in visual order, moving the number last."""
    doc = f"""# MDS-CS-STD-002 \u0645\u0639\u064a\u0627\u0631 \u0627\u0644\u062a\u0634\u0641\u064a\u0631

## \u0665 \u0625\u062f\u0627\u0631\u0629 \u0627\u0644\u0645\u0641\u0627\u062a\u064a\u062d

\u064a\u062c\u0628 \u0623\u0646 \u062a\u0643\u0648\u0646 \u0627\u0644\u0645\u0641\u0627\u062a\u064a\u062d \u0628\u0637\u0648\u0644 \u0662\u0665\u0666 \u0628\u062a \u0665\u066b\u0661
\u064a\u062c\u0628 \u062a\u062f\u0648\u064a\u0631 \u0627\u0644\u0645\u0641\u0627\u062a\u064a\u062d \u0633\u0646\u0648\u064a\u0627\u064b \u0665\u066b\u0662
\u064a\u062c\u0628 \u062a\u0648\u0644\u064a\u062f \u0627\u0644\u0645\u0641\u0627\u062a\u064a\u062d \u062f\u0627\u062e\u0644 \u0648\u062d\u062f\u0629 \u0623\u0645\u0627\u0646 \u0665\u066b\u0663
"""
    blocks = parse_blocks(doc)
    assert [b.clause for b in blocks if b.kind == "clause"] == ["5.1", "5.2", "5.3"]


def test_visual_order_mode_stays_off_for_well_formed_documents():
    """A trailing version number must not be mistaken for a clause identifier."""
    doc = """# \u0633\u064a\u0627\u0633\u0629

## \u0663 \u0627\u0644\u062a\u0634\u0641\u064a\u0631

\u0663\u066b\u0661 \u064a\u062c\u0628 \u0627\u0633\u062a\u062e\u062f\u0627\u0645 AES. \u0627\u0644\u0625\u0635\u062f\u0627\u0631 \u0664\u066b\u0662
\u0663\u066b\u0662 \u064a\u062c\u0628 \u062a\u062f\u0648\u064a\u0631 \u0627\u0644\u0645\u0641\u0627\u062a\u064a\u062d. \u0627\u0644\u0645\u0639\u064a\u0627\u0631 \u0661\u066b\u0663
\u0663\u066b\u0663 \u064a\u062c\u0628 \u0627\u0644\u062d\u0641\u0638 \u0641\u064a \u0648\u062d\u062f\u0629 \u0623\u0645\u0627\u0646. \u0627\u0644\u0646\u0633\u062e\u0629 \u0662\u066b\u0660
"""
    blocks = parse_blocks(doc)
    assert [b.clause for b in blocks if b.kind == "clause"] == ["3.1", "3.2", "3.3"]


def test_english_documents_never_enter_visual_order_mode():
    doc = "Policy revised in 2024.\nSee also standard 4.2\nApproved under version 1.3\nReviewed 2.0\n"
    blocks = parse_blocks(doc)
    assert not any(b.kind == "clause" for b in blocks)


# --- visual-order PDF text layers ------------------------------------------


def test_bidi_round_trip_preserves_numbers_and_latin_tokens():
    """Visual order is undone exactly, including the tokens most likely to break.

    A digit run reversed with the rest of the line is how a 12-character
    minimum password length was indexed as 21.
    """
    from bidi.algorithm import get_display

    from src.documents import to_logical_order

    originals = [
        "يجب أن تتكون كلمة المرور من 12 حرف على الأقل.",
        "يجب استخدام التشفير AES-256 لجميع البيانات.",
        "وفقاً لمعيار NIST SP 800-63B يجب التغيير كل 60 يوماً.",
        "الإبلاغ خلال 72 ساعة كما تنص عليه PDPL (المادة 20).",
    ]
    for original in originals:
        assert to_logical_order(get_display(original, base_dir="R")) == original


def test_logical_order_leaves_text_without_arabic_alone():
    from src.documents import to_logical_order

    line = "Critical | 24 hours | 72 hours | Permitted with CISO approval"
    assert to_logical_order(line) == line


def test_presentation_forms_fold_back_to_letters():
    """NFKC runs after reordering, so a lam-alef ligature expands the right way round."""
    from src.documents import to_logical_order

    # "ﻻ" is the lam-alef ligature; naive reversal yields "ال" instead of "لا".
    assert to_logical_order("ﻻ") == "لا"
