"""Clean product data is checkable: extraction, validation, and the review files (plan 026).

Every file here is synthetic; the team's real files never enter the suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import docx
import openpyxl
import pytest

from scripts import product_data as pd

STATEMENT = "Customer data is hosted in data centres inside Saudi Arabia."


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A delivery: one exported ticket and one answered sheet, with an Arabic paragraph and a merged cell."""
    delivery = tmp_path / "delivery" / "Product"
    delivery.mkdir(parents=True)

    ticket = docx.Document()
    ticket.add_paragraph("Dear team,")
    ticket.add_paragraph("")
    ticket.add_paragraph(
        "All customer data is hosted in data centres inside Saudi Arabia, and tenants are separated logically."
    )
    ticket.add_paragraph("يتم استضافة البيانات داخل المملكة العربية السعودية.")
    table = ticket.add_table(rows=2, cols=2)
    merged = table.cell(0, 0).merge(table.cell(0, 1))
    merged.text = "Control"
    table.cell(1, 0).text = "Backups"
    table.cell(1, 1).text = "Encrypted at rest and in transit"
    ticket.save(str(delivery / "ticket.docx"))

    sheet = openpyxl.Workbook()
    rows = sheet.active
    rows.title = "Answers"
    rows["A1"] = "Question"
    rows["B1"] = "Answer"
    rows["A2"] = "Is MFA enforced for administrators?"
    rows["B2"] = "Yes, through single sign-on."
    sheet.save(str(delivery / "answers.xlsx"))
    return tmp_path / "delivery"


def source(
    file: str = "Product/ticket.docx",
    where: str = "paragraph 2",
    quote: str = "hosted in data centres inside Saudi Arabia",
) -> dict:
    return {"file": file, "where": where, "quote": quote}


def fact(**changes) -> dict:
    item = {
        "id": "F-001",
        "topic": "Product and hosting",
        "statement": STATEMENT,
        "status": "standing",
        "scope": "product",
        "confidence": "high",
        "sources": [source()],
        "proposed": "keep",
    }
    return {**item, **changes}


def pair(**changes) -> dict:
    item = {
        "id": "QA-001",
        "question": "Is MFA enforced for administrators?",
        "answer": "Yes, through single sign-on.",
        "language": "en",
        "question_rebuilt": False,
        "scope": "product",
        "sources": [source("Product/answers.xlsx", "Answers!B2", "Yes, through single sign-on")],
        "proposed": "keep",
    }
    return {**item, **changes}


def batch(facts=None, pairs=None, asks=None) -> pd.Batch:
    return pd.Batch.model_validate(
        {
            "product": "Product",
            "prepared_on": "2026-10-18",
            "facts": [fact()] if facts is None else facts,
            "pairs": [pair()] if pairs is None else pairs,
            "asks": asks or [],
            "files": [
                {"file": "Product/ticket.docx", "decision": "used", "reason": "states hosting", "items": ["F-001"]}
            ],
        }
    )


# --- extraction --------------------------------------------------------------------


def test_a_document_is_read_in_order_with_locations(root: Path) -> None:
    blocks = list(pd.extract(root / "Product" / "ticket.docx"))
    assert blocks[:3] == [
        ("paragraph 1", "Dear team,"),
        (
            "paragraph 2",
            "All customer data is hosted in data centres inside Saudi Arabia, and tenants are separated logically.",
        ),
        ("paragraph 3", "يتم استضافة البيانات داخل المملكة العربية السعودية."),
    ], "empty paragraphs are skipped and not counted"
    cells = [b for b in blocks if b[0].startswith("table")]
    assert cells == [
        ("table 1 row 1 cell 1", "Control"),
        ("table 1 row 2 cell 1", "Backups"),
        ("table 1 row 2 cell 2", "Encrypted at rest and in transit"),
    ], "a merged cell is read once"


def test_a_sheet_is_read_cell_by_cell(root: Path) -> None:
    assert ("Answers!B2", "Yes, through single sign-on.") in list(pd.extract(root / "Product" / "answers.xlsx"))


def test_a_quote_survives_spacing_case_punctuation_and_arabic_marks() -> None:
    assert pd.quote_in("HOSTED in data-centres", "is hosted in data centres inside")
    assert pd.quote_in("استضافة البيانات", "يتم اسْتضافة البيانات داخل")
    assert not pd.quote_in("hosted outside", "is hosted in data centres inside")
    assert not pd.quote_in("host", "is hosted"), "whole words, not fragments"


# --- validation ----------------------------------------------------------------------


def test_a_clean_batch_passes(root: Path) -> None:
    assert pd.check(batch(), root) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"statement": "Ask ops@example.com about hosting in Saudi Arabia."}, "an email address"),
        ({"note": "Confirmed by phone on +966 55 123 4567."}, "a phone number"),
        ({"status": "dated"}, "needs as_of"),
        ({"status": "draft", "as_of": "2026-06", "proposed": "keep"}, "only a standing fact"),
        ({"topic": "Miscellaneous"}, "unknown topic"),
        ({"sources": [source(file="Product/missing.docx")]}, "no file"),
        ({"sources": [source(where="paragraph 9")]}, "no location"),
        ({"sources": [source(quote="hosted in Bahrain")]}, "the quote is not at"),
    ],
)
def test_a_fact_is_refused_for_each_rule(root: Path, changes: dict, expected: str) -> None:
    problems = pd.check(batch(facts=[fact(**changes)]), root)
    assert any(expected in problem for problem in problems), problems


def test_a_ticket_number_is_not_a_phone_number(root: Path) -> None:
    noted = fact(note="From Ticket#2026072082001318, dated 2026-07-20.")
    assert pd.check(batch(facts=[noted]), root) == []


def test_a_dated_fact_with_its_date_may_be_held(root: Path) -> None:
    held = fact(status="dated", as_of="2026-08", proposed="hold")
    assert pd.check(batch(facts=[held]), root) == []


def test_an_excluded_file_is_refused_by_its_content(root: Path, tmp_path: Path) -> None:
    held_out = tmp_path / "held-out"
    held_out.mkdir()
    (held_out / "renamed copy.xlsx").write_bytes((root / "Product" / "answers.xlsx").read_bytes())
    problems = pd.check(batch(), root, exclude=[held_out])
    assert problems == ["QA-001: 'Product/answers.xlsx' is an excluded file (held or held out)"]


def test_ids_are_unique_and_questions_for_the_team_point_at_real_items(root: Path) -> None:
    asks = [{"id": "Q-1", "question": "Which data centres?", "why": "conflict", "related": ["F-001", "F-404"]}]
    problems = pd.check(batch(facts=[fact(), fact()], asks=asks), root)
    assert "F-001: the id is used 2 times" in problems
    assert "Q-1: refers to unknown item F-404" in problems


# --- the review files ----------------------------------------------------------------


def test_the_workbook_has_a_sheet_per_kind_and_a_decision_column(root: Path, tmp_path: Path) -> None:
    out = tmp_path / "review.xlsx"
    pd.write_workbook(batch(), out)
    book = openpyxl.load_workbook(out)
    assert book.sheetnames == ["Read me", "Facts", "Q&A", "Questions for the team", "Files"]
    facts = book["Facts"]
    header = [cell.value for cell in facts[1]]
    assert "Decision" in header and "Sources" in header
    row = {h: c.value for h, c in zip(header, facts[2])}
    assert row["Statement"] == STATEMENT
    assert "Product/ticket.docx @ paragraph 2" in row["Sources"]
    assert facts.data_validations.dataValidation, "the decision is a choice"


def test_the_fact_sheet_holds_only_kept_standing_product_facts(root: Path, tmp_path: Path) -> None:
    facts = [
        fact(),
        fact(
            id="F-002",
            statement="A penetration test report is expected at the end of August.",
            status="dated",
            as_of="2026-07",
            proposed="hold",
        ),
        fact(id="F-003", statement="T2 is certified to ISO/IEC 27001 across the company.", scope="t2_wide"),
        fact(id="F-004", statement="Backups are kept on removable media in the office.", proposed="drop"),
    ]
    out = tmp_path / "facts.docx"
    assert pd.write_fact_sheet(batch(facts=facts), out, draft=True) == 1
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert f"{STATEMENT} [F-001]" in text
    assert "Product and hosting" in text and "DRAFT FOR REVIEW" in text
    assert "reviewed by the team" not in text, "a draft does not claim a review it has not had"
    for absent in ("August", "ISO/IEC 27001", "removable media", "ticket.docx"):
        assert absent not in text, absent

    pd.write_fact_sheet(batch(facts=facts), out)
    assert "reviewed by the team" in "\n".join(p.text for p in docx.Document(str(out)).paragraphs)


def test_the_command_line_checks_a_batch_file(root: Path, tmp_path: Path, capsys) -> None:
    path = tmp_path / "batch.json"
    path.write_text(
        json.dumps(batch(facts=[fact(sources=[source(quote="hosted in Bahrain")])]).model_dump()), encoding="utf-8"
    )
    assert pd.main(["check", str(path), "--root", str(root)]) == 1
    assert "PROBLEM F-001: the quote is not at" in capsys.readouterr().out


def test_a_rewritten_answer_says_so_in_the_workbook(root: Path, tmp_path: Path) -> None:
    out = tmp_path / "review.xlsx"
    pd.write_workbook(batch(pairs=[pair(rewritten=True)]), out)
    sheet = openpyxl.load_workbook(out)["Q&A"]
    row = {h.value: c.value for h, c in zip(sheet[1], sheet[2])}
    assert row["Answer rewritten"] == "yes" and row["Question rebuilt"] == "no"


def test_held_items_from_every_batch_go_into_one_workbook(root: Path, tmp_path: Path) -> None:
    """Only what is held, labelled with its product, plus live entries held rather than moved."""
    first = batch(facts=[fact(), fact(id="F-002", status="dated", as_of="2026-07", proposed="hold")])
    second = batch(pairs=[pair(), pair(id="QA-002", proposed="hold")])
    second.product = "Other"
    second.asks = [pd.Ask(id="Q-1", question="Which data centres?", why="conflict")]
    existing = [
        pd.Existing(
            entry_id="MEM-1", product="Other", from_file="form.xlsx", question="Q?", answer="Yes.", why="unclear"
        )
    ]
    out = tmp_path / "held.xlsx"
    assert pd.write_held([first, second], out, existing) == 4
    book = openpyxl.load_workbook(out)
    assert book.sheetnames == [
        "Read me",
        "Held facts",
        "Held answers",
        "Questions for the team",
        "Existing memory entries",
    ]
    facts = [[c.value for c in row] for row in book["Held facts"].iter_rows(min_row=2)]
    assert [(r[0], r[1]) for r in facts] == [("Product", "F-002")], "kept items are not held"
    answers = [[c.value for c in row] for row in book["Held answers"].iter_rows(min_row=2)]
    assert [(r[0], r[1]) for r in answers] == [("Other", "QA-002")]
    assert book["Existing memory entries"]["B2"].value == "MEM-1"


def test_the_shared_batch_writes_the_t2_wide_facts(root: Path, tmp_path: Path) -> None:
    facts = [
        fact(),
        fact(id="F-002", statement="T2 is certified to ISO/IEC 27001 across the company.", scope="t2_wide"),
    ]
    shared = batch(facts=facts)
    shared.product = pd.SHARED
    out = tmp_path / "shared.docx"
    assert pd.write_fact_sheet(shared, out) == 1
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert "T2: security and operations facts" in text and "whatever the product" in text
    assert "ISO/IEC 27001" in text and STATEMENT not in text, "the shared sheet takes T2-wide facts, not a product's"


def test_a_t2_wide_item_is_held_once_in_the_shared_batch_not_again_in_its_product(root: Path, tmp_path: Path) -> None:
    wide = fact(id="F-009", statement="T2 is certified to ISO/IEC 27001 across the company.", scope="t2_wide",
                status="dated", as_of="2026-08", proposed="hold")  # fmt: skip
    product = batch(facts=[fact(), wide])
    shared = batch(facts=[wide])
    shared.product = pd.SHARED
    out = tmp_path / "held.xlsx"
    pd.write_held([product, shared], out)
    rows = [[c.value for c in row] for row in openpyxl.load_workbook(out)["Held facts"].iter_rows(min_row=2)]
    assert [(r[0], r[1]) for r in rows] == [(pd.SHARED, "F-009")]
