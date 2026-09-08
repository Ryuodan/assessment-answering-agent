"""Building .xlsx files in the shapes the real questionnaires actually use.

The customer questionnaires cannot be committed -- they are other banks'
confidential forms -- so the layouts that made detection hard are reproduced
here instead, each one named after the problem it caused. A test that fails
should say which real-world shape stopped working.

The builder writes just enough of the format for `xlsx_package` to read: a
workbook part, a worksheet per sheet, and optional validations and formulas.
Deliberately not a spreadsheet library -- a fixture that needed one would be
testing the library rather than our reader.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{sheets}
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="xl/workbook.xml"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>
</Relationships>"""


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


class SheetSpec:
    """One worksheet: cells keyed by reference, plus the awkward extras."""

    def __init__(
        self,
        name: str,
        cells: dict[str, str],
        *,
        hidden: bool = False,
        merges: tuple[str, ...] = (),
        validations: tuple[tuple[str, str], ...] = (),
        formulas: tuple[str, ...] = (),
    ):
        self.name = name
        self.cells = cells
        self.hidden = hidden
        self.merges = merges
        self.validations = validations
        """(sqref, formula1) -- e.g. ('C2:C40', '"Yes,No"') or a range reference."""

        self.formulas = formulas
        """Refs that should carry a formula, so write-back has something to refuse."""

    def xml(self) -> str:
        rows: dict[int, list[str]] = {}
        for ref, text in self.cells.items():
            number = int("".join(character for character in ref if character.isdigit()))
            rows.setdefault(number, []).append(ref)

        body = []
        for number in sorted(rows):
            cells = []
            for ref in sorted(rows[number], key=_column_key):
                text = self.cells[ref]
                if ref in self.formulas:
                    cells.append(f'<c r="{ref}"><f>SUM(A1:A2)</f><v>{_escape(text)}</v></c>')
                else:
                    cells.append(
                        f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">'
                        f"{_escape(text)}</t></is></c>"
                    )
            body.append(f'<row r="{number}">{"".join(cells)}</row>')

        merges = ""
        if self.merges:
            spans = "".join(f'<mergeCell ref="{span}"/>' for span in self.merges)
            merges = f'<mergeCells count="{len(self.merges)}">{spans}</mergeCells>'

        validations = "".join(
            f'<dataValidation type="list" sqref="{sqref}">'
            f"<formula1>{_escape(formula)}</formula1></dataValidation>"
            for sqref, formula in self.validations
        )
        if validations:
            validations = f'<dataValidations count="{len(self.validations)}">{validations}</dataValidations>'

        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(body)}</sheetData>{merges}{validations}</worksheet>'
        )


def _column_key(ref: str) -> int:
    letters = "".join(character for character in ref if character.isalpha())
    value = 0
    for character in letters:
        value = value * 26 + (ord(character) - 64)
    return value


def build(path: Path, sheets: list[SheetSpec], *, extra_parts: dict[str, bytes] | None = None) -> Path:
    """Write a workbook. `extra_parts` stands in for drawings and comments.

    Those extras are the whole point of the fidelity test: they are exactly what
    a load-and-save through a spreadsheet library discards, so a fixture without
    them could not catch it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    overrides = "\n".join(
        f'  <Override PartName="/xl/worksheets/sheet{index + 1}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(len(sheets))
    )

    entries = []
    for index, sheet in enumerate(sheets):
        state = ' state="hidden"' if sheet.hidden else ""
        entries.append(
            f'<sheet name="{_escape(sheet.name)}" sheetId="{index + 1}"'
            f'{state} r:id="rId{index + 1}"/>'
        )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(entries)}</sheets></workbook>'
    )
    relationships = "".join(
        f'<Relationship Id="rId{index + 1}" Target="worksheets/sheet{index + 1}.xml" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
        for index in range(len(sheets))
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{relationships}</Relationships>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml", CONTENT_TYPES.format(sheets=overrides))
        out.writestr("_rels/.rels", ROOT_RELS)
        out.writestr("xl/workbook.xml", workbook)
        out.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for index, sheet in enumerate(sheets):
            out.writestr(f"xl/worksheets/sheet{index + 1}.xml", sheet.xml())
        for name, payload in (extra_parts or {}).items():
            out.writestr(name, payload)
    return path


# --- the shapes that were hard ---------------------------------------------


def simple(path: Path) -> Path:
    """Number, question, answer. The layout everything else deviates from."""
    return build(path, [SheetSpec("Questionnaire", {
        "A1": "S.No", "B1": "Vendor Due Diligence Questions", "C1": "Vendor Response",
        "A2": "1.0", "B2": "Does the vendor have documented information security policies?",
        "A3": "2.0", "B3": "Does the vendor review those policies at least annually?",
        "A4": "3.0", "B4": "Are staff bound by non-disclosure agreements?",
        "A5": "4.0", "B5": "Is multi-factor authentication enforced on privileged accounts?",
    })])


def header_below_preamble(path: Path) -> Path:
    """A title, a vendor name and a date above the real headings."""
    return build(path, [SheetSpec("RA Questionarie", {
        "B1": "نموذج استبيان أمن المعلومات",
        "B5": "Vendor name :", "D5": "date :",
        "A8": "S.No", "B8": "Vendor Due Diligence Questions", "C8": "Vendor Response",
        "D8": "Compliance (To be updated by BAB)",
        "A9": "1.0", "B9": "Does the vendor have documented information security policies?",
        "A10": "2.0", "B10": "Does the vendor review those policies at least annually?",
        "A11": "3.0", "B11": "Are staff bound by non-disclosure agreements?",
        "A12": "4.0", "B12": "هل يتم تشفير البيانات الحساسة أثناء النقل والتخزين؟",
    })])


def status_and_comment(path: Path) -> Path:
    """A dropdown whose words live on a hidden sheet, plus a comment column."""
    return build(path, [
        SheetSpec("Human Resources", {
            "B1": "HR Security", "C1": "Compliance Status", "D1": "Additional Comments",
            "A2": "1.0", "B2": "Has the human resources process been defined and approved?",
            "A3": "2.0", "B3": "Do employees receive regular cybersecurity awareness training?",
            "A4": "3.0", "B4": "Are access rights revoked immediately on termination?",
            "A5": "4.0", "B5": "Do you perform background checks before hiring?",
        }, validations=(("C2:C5", "Score!$B$2:$B$5"),)),
        SheetSpec("Score", {
            "B1": "Compliance Status",
            "B2": "Fully Compliant", "B3": "Partially Compliant",
            "B4": "Non Compliant", "B5": "Not Applicable",
            "C7": "133",
        }, hidden=True, formulas=("C7",)),
    ])


def ownership_banner(path: Path) -> Path:
    """Who owns which column is declared in a merged banner above the headings."""
    return build(path, [SheetSpec("General Information", {
        "C3": "General Information",
        "D4": "To be Filled by the Service Provider/ Third Party",
        "F4": "To be Filled by Bank Albilad",
        "A5": "#", "B5": "Question", "C5": "Description", "D5": "Answer",
        "E5": "Additional Information to Support the Answer",
        "F5": "Compliance Code\n(Give a compliance level code that best suits the answer)",
        "G5": "Comments and Required Next Steps",
        "A6": "GI.1.1", "B6": "Organization's legal name", "C6": "Specify your company's legal name",
        "A7": "GI.1.2", "B7": "Industry", "C7": "What industry are you in?",
        "A8": "GI.1.3", "B8": "Address of the organization", "C8": "Specify the full mailing address",
        "A9": "GI.1.4", "B9": "Transfer of personal data inside or outside the Kingdom?",
        "C9": "Provide the processing and hosting location",
    }, merges=("D4:E4", "F4:G4"))])


def headless_numbered(path: Path) -> Path:
    """No headings anywhere: a section title, then numbered questions."""
    return build(path, [SheetSpec("2. Environment", {
        "B7": "Part 2:", "C7": "Environment, Health & Safety",
        "B8": "A)", "C8": "Health, Safety & Environment",
        "B9": "A.1", "C9": "Does the company have a management system in place for HS&E?", "H9": "Yes\nNo",
        "B10": "A.2", "C10": "Is the management system compliant with ISO 14001?", "H10": "Yes\nNo",
        "B11": "A.3", "C11": "Company Name:",
        "B12": "A.4", "C12": "Are environmental expectations communicated to staff?", "H12": "Yes\nNo",
        "B13": "A.5",
        "C13": 'If "Yes", please provide the information below, and attach a copy of the certificate',
        "B14": "A.6", "C14": "Certificate Type:",
    })])


def legend_sheet(path: Path) -> Path:
    """A ratings legend beside a real questionnaire. Prose in a column, no numbers."""
    return build(path, [
        SheetSpec("Compliance Levels", {
            "A2": "Category", "B2": "Code", "C2": "Description", "D2": "Action",
            "A3": "Full Compliance", "B3": "FC",
            "C3": "The vendor fully meets all the specified requirements and standards.",
            "D3": "Continue to monitor and maintain this vendor relationship.",
            "A4": "Partial Compliance", "B4": "PC",
            "C4": "The vendor meets some, but not all, of the specified requirements.",
            "D4": "Vendor to submit a detailed corrective action plan.",
            "A5": "Non Compliance", "B5": "NC",
            "C5": "The vendor fails to meet the specified requirements and standards.",
            "D5": "Immediate action is required to address non-compliance.",
        }),
        SheetSpec("Questions", {
            "A1": "S.No", "B1": "Question", "C1": "Response",
            "A2": "1.0", "B2": "Does the vendor have documented information security policies?",
            "A3": "2.0", "B3": "Does the vendor review those policies at least annually?",
            "A4": "3.0", "B4": "Are staff bound by non-disclosure agreements?",
            "A5": "4.0", "B5": "Is multi-factor authentication enforced?",
        }),
    ])


def with_extra_parts(path: Path) -> Path:
    """A questionnaire carrying the parts a library round-trip would drop."""
    return build(
        path,
        [SheetSpec("Questionnaire", {
            "A1": "S.No", "B1": "Question", "C1": "Response",
            "A2": "1.0", "B2": "Does the vendor have documented information security policies?",
            "A3": "2.0", "B3": "Does the vendor review those policies at least annually?",
            "A4": "3.0", "B4": "Are staff bound by non-disclosure agreements?",
        })],
        extra_parts={
            "xl/drawings/drawing1.xml": b"<xdr:wsDr>a drawing we do not understand</xdr:wsDr>",
            "xl/comments1.xml": b"<comments>the bank's own instructions</comments>",
            "xl/media/image1.png": b"\x89PNG\r\n\x1a\n not really a png",
        },
    )

def two_row_header(path: Path) -> Path:
    """A header split over two rows, which no single row scores as a header.

    Row 4 carries the group names -- 'Control', 'Supplier response' merged over
    two columns -- and row 5 the fields themselves. Neither row alone has two
    recognisable labels sitting over the right columns, so the rules find no
    header at all and skip the sheet. It is the shape the model fallback exists
    for, and it is real: two of the customer workbooks head their answer block
    this way.
    """
    return build(path, [SheetSpec("Assessment", {
        "A1": "Supplier Cyber Assessment 2026",
        "A4": "Control", "C4": "Supplier response",
        "A5": "Ref", "B5": "Description", "C5": "Compliance", "D5": "Notes",
        "A6": "1.1", "B6": "Is there a documented information security policy?",
        "A7": "1.2", "B7": "Is the policy reviewed and approved annually?",
        "A8": "1.3", "B8": "Are staff required to acknowledge the policy?",
        "A9": "2.1", "B9": "Is multi-factor authentication enforced for remote access?",
        "A10": "2.2", "B10": "Are privileged accounts reviewed quarterly?",
    }, merges=("C4:D4",), validations=(("C6:C10", '"Yes,No,Partial"'),))])

def reference_column_headed_id(path: Path) -> Path:
    """The reference column is headed `ID`, and the questions are short.

    Two sheets of one real workbook, and one root cause. Without `ID` in the
    reference-column headings there is no numbering column, and a question is
    only recognised when it ends in a question mark or runs past fifty
    characters -- so `Organisation name` and `Email address` are lost entirely,
    and so is `Do you maintain an incident register`, at thirty-six characters
    with a full stop.

    The second sheet also carries the two-row header the same workbook uses:
    the group names on row 1, the fields themselves on row 2.
    """
    return build(path, [
        SheetSpec("Vendor Info", {
            "A1": "Please complete the below questions.",
            "A3": "ID", "B3": "Question", "F3": "Answer", "G3": "Notes",
            "A4": "GQ1", "B4": "Organisation name",
            "A5": "GQ2", "B5": "Year established",
            "A6": "GQ3", "B6": "Office locations and Country",
            "A7": "GQ4", "B7": "Email address",
            "A8": "GQ5", "B8": "Contact Number",
        }),
        SheetSpec("Questionnaire", {
            "A1": "Security Domain", "B1": "ID", "C1": "Question", "D1": "Main Response",
            "C2": "Description", "D2": "Response", "E2": "Further Guidance",
            "A3": "General", "B3": "GE-01",
            "C3": "Are the services that your organisation provides located in the Kingdom?",
            "A4": "Incident Response", "B4": "IR-01",
            "C4": "Do you have an incident management policy or crisis management plan?",
            "B5": "IR-03", "C5": "Do you maintain an incident register",
            "B6": "IR-04", "C6": "Do you undertake a post incident review?",
        }),
    ])


def headless_typo_header(path: Path) -> Path:
    """A header row one typo away from being recognised, and no numbering.

    `Queations | Answer`: only one of the two headings is a word any rule knows,
    so the row does not qualify as a header and the sheet is read headless. That
    is survivable while the answer column is empty -- the questions are the only
    prose on the sheet. Once it is filled it holds *more* prose than they do,
    takes their place, and the half-answered file re-opens with nothing in it.

    Measured on the real workbook: 32 questions written, re-opened as 0.
    """
    cells = {"A1": "Queations", "B1": "Answer"}
    questions = [
        "What is the name of the vendor?",
        "Who is the internal owner responsible for this relationship?",
        "Provide a brief description of the product or service supplied.",
        "What is the PII data collection?",
        "How does the vendor ensure data minimization?",
        "What is the retention period for each data category?",
        "Describe the data deletion or anonymization process in place.",
        "Does the vendor support Single Sign-On and Multi-Factor Authentication?",
        "When did the vendor last carry out penetration testing?",
        "Describe the incident management process for a data breach.",
    ]
    for index, text in enumerate(questions, start=2):
        cells[f"A{index}"] = text
    return build(path, [SheetSpec("Sheet1", cells)])
