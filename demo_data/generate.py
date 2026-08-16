#!/usr/bin/env python
"""Generate the demo corpus.

    python -m demo_data.generate            # writes demo_data/{guidelines,...}
    python -m demo_data.generate --clean    # remove generated files first

Outputs are deterministic, so regenerating after a content edit produces a
clean diff. Requires the `demo` extra: pip install -e ".[demo]"
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from demo_data import content_assessments as qa
from demo_data import content_datasets as ds
from demo_data import content_policies as pol
from demo_data.builders import build_csv, build_docx, build_pdf

ROOT = Path(__file__).resolve().parent
GUIDELINES = ROOT / "guidelines"
PRIOR = ROOT / "prior_assessments"
NEW = ROOT / "new_assessments"
DATASETS = ROOT / "datasets"

# (directory, filename, blocks, format)
DOCUMENTS = [
    (GUIDELINES, "information_security_policy.pdf", pol.INFORMATION_SECURITY_POLICY, "pdf"),
    (GUIDELINES, "access_control_policy.docx", pol.ACCESS_CONTROL_POLICY, "docx"),
    (GUIDELINES, "data_protection_pdpl_policy.pdf", pol.DATA_PROTECTION_POLICY, "pdf"),
    (GUIDELINES, "incident_response_bcdr_policy.docx", pol.INCIDENT_RESPONSE_POLICY, "docx"),
    (GUIDELINES, "third_party_cloud_security_policy.pdf", pol.THIRD_PARTY_POLICY, "pdf"),
    (GUIDELINES, "nca_ecc_sama_control_mapping.pdf", pol.CONTROL_MAPPING, "pdf"),
    (GUIDELINES, "siyasat_amn_almaalumat_ar.docx", pol.ARABIC_SECURITY_POLICY, "docx"),

    (PRIOR, "vendor_security_assessment_2024_completed.docx", qa.PRIOR_VENDOR_2024, "docx"),
    (PRIOR, "nca_ecc_self_assessment_2025_completed.pdf", qa.PRIOR_NCA_ECC_2025, "pdf"),
    (PRIOR, "pdpl_review_2025_completed_ar.docx", qa.PRIOR_PDPL_2025_AR, "docx"),
    (PRIOR, "cloud_due_diligence_2025_completed_bilingual.docx", qa.PRIOR_BILINGUAL_2025, "docx"),

    (NEW, "vendor_security_assessment_2026.docx", qa.NEW_VENDOR_2026, "docx"),
    (NEW, "pdpl_compliance_questionnaire_2026_ar.docx", qa.NEW_PDPL_2026_AR, "docx"),
    (NEW, "third_party_cyber_risk_review_2026_bilingual.pdf", qa.NEW_BANK_TPRM_2026, "pdf"),
    (NEW, "cloud_security_questionnaire_2026.pdf", qa.NEW_CLOUD_2026, "pdf"),
]


def _register_document(title: str, header: list[str], rows: list[list]) -> list[tuple]:
    """Wrap a dataset as an uploadable guideline document."""
    return [
        ("title", title),
        ("para", f"Acme Cloud Services KSA — operational register, extracted {title.split()[-1]}."),
        ("para", pol.DISCLAIMER),
        ("table", (header, rows)),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="delete generated directories first")
    args = parser.parse_args()

    if args.clean:
        for directory in (GUIDELINES, PRIOR, NEW, DATASETS):
            shutil.rmtree(directory, ignore_errors=True)

    written: list[Path] = []

    for directory, name, blocks, fmt in DOCUMENTS:
        path = directory / name
        written.append(build_pdf(path, blocks) if fmt == "pdf" else build_docx(path, blocks))

    # Registers: CSV for spreadsheets, plus one DOCX the app can actually ingest.
    register_blocks: list[tuple] = [
        ("title", "Operational Security Registers"),
        ("para", pol.DISCLAIMER),
    ]
    for slug, (title, (header, rows)) in ds.DATASETS.items():
        written.append(build_csv(DATASETS / f"{slug}.csv", header, rows))
        register_blocks.append(("heading", title))
        register_blocks.append(("table", (header, rows)))
    written.append(build_docx(GUIDELINES / "operational_security_registers.docx", register_blocks))

    for path in written:
        print(f"  {path.relative_to(ROOT.parent)}  ({path.stat().st_size:,} bytes)")
    print(f"\n{len(written)} files written.")


if __name__ == "__main__":
    main()
