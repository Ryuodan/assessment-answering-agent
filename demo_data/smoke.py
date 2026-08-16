#!/usr/bin/env python
"""Generate the smoke-test corpus.

    python -m demo_data.smoke

A deliberately tiny counterpart to `demo_data.generate`: one guideline, one
completed assessment and one six-question blank assessment, sized so a full
run is a handful of LLM calls rather than sixty. Each question in the blank
assessment targets a different branch of the answering graph — see
`NEW_QUESTIONS` below, where every row carries the branch it exercises.

Both DOCX and Markdown are written from the same content. DOCX is what the app
ingests; the Markdown is for pasting into a canvas or a text-only loader.

Unlike `builders.py` this module has no PDF path, so it needs only python-docx
and runs anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

OUT = Path(__file__).resolve().parent / "smoke"
ARABIC_RE = re.compile(r"[؀-ۿ]")


# ---------------------------------------------------------------------------
# Content — one fictional organisation, every fact checkable
# ---------------------------------------------------------------------------

GUIDELINE = [
    ("title", "Northwind Data Systems — Information Security Summary"),
    ("para",
     "Fictional reference material for testing only. Northwind Data Systems is a fictional "
     "cloud provider; nothing below describes a real organisation."),

    ("heading", "1. Certification"),
    ("para",
     "Northwind is certified against ISO/IEC 27001:2022 under certificate NW-27001-4471, valid "
     "until 14 March 2027. An independent SOC 2 Type II audit is performed annually; the most "
     "recent report was issued on 30 September 2025 and covers a twelve-month observation window."),

    ("heading", "2. Cryptography"),
    ("para",
     "Customer data is encrypted at rest with AES-256 and in transit with TLS 1.3. Keys are held "
     "in an FIPS 140-2 Level 3 hardware security module and rotated every 12 months. Customer-managed "
     "keys (BYOK) are supported on the Enterprise tier only."),

    ("heading", "3. Access control"),
    ("para",
     "Multi-factor authentication is mandatory for all administrative access. Accepted factors are "
     "FIDO2 hardware security keys and TOTP applications; SMS is not accepted. Standing privileged "
     "access is not permitted — administrators request time-bound elevation, and every privileged "
     "session is recorded."),
    ("para",
     "User access rights are reviewed quarterly by the system owner. Entitlements that are not "
     "recertified within the review window are revoked automatically within five working days."),

    ("heading", "4. Data residency and retention"),
    ("para",
     "All customer data is stored in the Kingdom of Saudi Arabia across the Riyadh and Jeddah "
     "regions. Data does not leave the Kingdom except where a customer explicitly enables "
     "cross-border replication in writing."),
    ("para",
     "تُحتفظ بيانات العملاء لمدة تسعين (٩٠) يوماً بعد انتهاء العقد، ثم تُتلف باستخدام المحو "
     "التشفيري، وتُصدر شهادة إتلاف للعميل عند الطلب."),

    ("heading", "5. Incident response and resilience"),
    ("para",
     "Confirmed personal data breaches are notified to SDAIA within 72 hours of confirmation, and "
     "to affected customers within 24 hours. The recovery time objective is 4 hours and the "
     "recovery point objective is 15 minutes. Regional failover was last exercised in September 2025 "
     "and completed in 2 hours 41 minutes."),

    ("heading", "6. Vulnerability management"),
    ("para",
     "Critical vulnerabilities are remediated within 7 days, high within 30 days, medium within 90 "
     "days. External penetration testing is performed twice a year by an independent CREST-accredited "
     "firm."),
]


PRIOR_ANSWERS = [
    ("title", "Northwind Data Systems — Vendor Security Assessment 2025 (Completed)"),
    ("para", "Returned to Meridian Bank on 12 November 2025. Fictional content, for testing only."),
    ("table", (
        ["#", "Question", "Answer"],
        [
            ["1",
             "Is multi-factor authentication required for administrative access, and which factors "
             "are accepted?",
             "Yes. MFA is mandatory for every administrative account with no exceptions. We accept "
             "FIDO2 hardware security keys and TOTP authenticator applications. SMS-based one-time "
             "passwords are explicitly not accepted. Standing privileged access is not permitted; "
             "elevation is time-bound and every privileged session is recorded."],
            ["2",
             "Where is customer data stored, and under what circumstances does it leave the Kingdom?",
             "All customer data resides in the Kingdom of Saudi Arabia, replicated between our Riyadh "
             "and Jeddah regions. Data leaves the Kingdom only where the customer has explicitly "
             "enabled cross-border replication in writing; this is off by default and requires a "
             "signed amendment."],
            ["3",
             "ما هي المدة النظامية لإبلاغ الهيئة عند وقوع اختراق مؤكد للبيانات الشخصية؟",
             "نلتزم بإبلاغ الهيئة السعودية للبيانات والذكاء الاصطناعي خلال ٧٢ ساعة من تأكيد وقوع "
             "الاختراق، ويتم إشعار العملاء المتأثرين خلال ٢٤ ساعة."],
            ["4",
             "How many subprocessors do you use, and how many can access customer content?",
             "We use eleven subprocessors. Three of them can access customer content, and each is "
             "assessed annually against our third-party security standard. Customers receive 30 days' "
             "notice before a new subprocessor with content access is added."],
        ],
    )),
]


# (question, branch this row is designed to exercise)
NEW_QUESTIONS = [
    ("Is multi-factor authentication required for administrative access, and which factors "
     "are accepted?",
     "prior-answer reuse — expect the 2025 wording back, confidence > 0.8"),

    ("What is your recovery time objective and recovery point objective, and when was failover "
     "last exercised?",
     "guideline-only grounding — 4h / 15min / September 2025"),

    ("Are you certified against a recognised information security standard? State the certificate "
     "number and validity period.",
     "verbatim fact recall — NW-27001-4471, valid to 14 March 2027"),

    ("Do you support customer-managed encryption keys (BYOK)? Choose one.",
     "choice constraint — the answer must use one option exactly"),

    ("كم عدد المورّدين من الباطن لديكم، وكم منهم يملك صلاحية الوصول إلى محتوى العملاء؟",
     "per-question language — Arabic question, Arabic answer, English source"),

    ("Describe your post-quantum cryptography migration roadmap and the target date for "
     "deprecating RSA-2048.",
     "not covered — expect the refine loop, then a plain admission and needs_review = true"),
]

NEW_ASSESSMENT = [
    ("title", "Northwind Data Systems — Security Questionnaire 2026"),
    ("para",
     "Issued by Meridian Bank — Third-Party Risk Management. Complete every row. "
     "Answer in the language of the question."),
    ("table", (
        ["#", "Question", "Options", "Answer"],
        [
            ["1", NEW_QUESTIONS[0][0], "", ""],
            ["2", NEW_QUESTIONS[1][0], "", ""],
            ["3", NEW_QUESTIONS[2][0], "", ""],
            # Options are separated with ";" not "|": the DOCX loader renders each
            # table row as pipe-delimited text, so a pipe here would read as a
            # column break and split the row.
            ["4", NEW_QUESTIONS[3][0],
             "Supported on all tiers; Supported on Enterprise tier only; Not supported", ""],
            ["5", NEW_QUESTIONS[4][0], "", ""],
            ["6", NEW_QUESTIONS[5][0], "", ""],
        ],
    )),
]


DOCUMENTS = [
    ("smoke_guideline", GUIDELINE),
    ("smoke_prior_answers", PRIOR_ANSWERS),
    ("smoke_new_assessment", NEW_ASSESSMENT),
]


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _has_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text))


def write_docx(path: Path, blocks: list[tuple]) -> Path:
    """Write a DOCX from ('title'|'heading'|'para'|'table', payload) blocks."""
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    for kind, payload in blocks:
        if kind == "title":
            document.add_heading(payload, level=0)
        elif kind == "heading":
            document.add_heading(payload, level=1)
        elif kind == "para":
            paragraph = document.add_paragraph(payload)
            if _has_arabic(payload):
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif kind == "table":
            header, rows = payload
            table = document.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            for cell, text in zip(table.rows[0].cells, header):
                cell.text = str(text)
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            for row in rows:
                cells = table.add_row().cells
                for cell, text in zip(cells, row):
                    cell.text = str(text)
                    if _has_arabic(str(text)):
                        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            document.add_paragraph()
        else:
            raise ValueError(f"unknown block kind: {kind}")

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path


def write_markdown(path: Path, blocks: list[tuple]) -> Path:
    """Write the same content as Markdown, tables included."""
    lines: list[str] = []
    for kind, payload in blocks:
        if kind == "title":
            lines += [f"# {payload}", ""]
        elif kind == "heading":
            lines += [f"## {payload}", ""]
        elif kind == "para":
            lines += [payload, ""]
        elif kind == "table":
            header, rows = payload
            lines.append("| " + " | ".join(str(c) for c in header) + " |")
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            for row in rows:
                cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def main() -> None:
    written: list[Path] = []
    for name, blocks in DOCUMENTS:
        written.append(write_docx(OUT / f"{name}.docx", blocks))
        written.append(write_markdown(OUT / f"{name}.md", blocks))

    for path in written:
        print(f"  {path.relative_to(OUT.parent.parent)}  ({path.stat().st_size:,} bytes)")
    print(f"\n{len(written)} files written to {OUT.relative_to(OUT.parent.parent)}/")


if __name__ == "__main__":
    main()
