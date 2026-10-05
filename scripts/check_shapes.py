"""Exercise the chunker against many document shapes, not just one corpus."""

import sys

sys.path.insert(0, "/home/claude/work/repo")

from src.chunking import chunk_document

RLM = "\u200f"

SHAPES = {}

SHAPES["markdown headings + stem + subclauses"] = """# MDS-CS-STD-004 Logging and Monitoring Standard

## 7 Monitoring

7.1 The SIEM shall ingest events from all in-scope systems.
7.2 The following shall generate an alert triaged at severity High or above:
7.2.1 Break-glass authentication.
7.2.2 Use of a shared administrative account.
7.2.3 Bypass of the privileged access workflow.
7.2.4 Disabling of endpoint protection.
7.3 Alerts shall be acknowledged within fifteen minutes.
"""

SHAPES["bold clause numbers (Docling markdown)"] = """## **7** Monitoring

**7.1** The SIEM shall ingest events from all in-scope systems.
**7.2** The following shall generate an alert:
**7.2.1** Break-glass authentication.
**7.2.2** Use of a shared administrative account.
**7.2.3** Bypass of the privileged access workflow.
"""

SHAPES["no headings, clause-numbered only"] = """ACS-POL-001 Information Security Policy

3. Cryptography
3.1 All data at rest shall use AES-256-GCM.
3.2 The approved algorithm set is:
3.2.1 AES-256
3.2.2 RSA-3072
3.2.3 ECDSA P-256
4. Logging
4.1 Logs are retained for 36 months.
"""

SHAPES["legal style: Article + letter items"] = """# Data Protection Regulation

Article 5 Principles of processing

Personal data shall be:
(a) processed lawfully, fairly and transparently;
(b) collected for specified, explicit and legitimate purposes;
(c) adequate, relevant and limited to what is necessary;
(d) accurate and, where necessary, kept up to date;
(e) kept in a form permitting identification no longer than necessary;
(f) processed in a manner ensuring appropriate security.

Article 6 Lawfulness
Processing is lawful only if at least one basis applies.
"""

SHAPES["unnumbered headings + bullets"] = """# Vendor Security Requirements

## Access control

Suppliers must meet all of the following before connecting to our estate:

- Multi-factor authentication on every administrative account.
- Unique named accounts, with no shared credentials.
- Quarterly access reviews with evidence retained.
- Session recording for privileged access.
- Removal of access within 24 hours of termination.

## Incident notification

Suppliers must notify us within 24 hours of a confirmed incident.
"""

SHAPES["markdown table inside a section"] = """## 7.4 Remediation windows

Vulnerabilities shall be remediated within the following windows:

| Severity | Internet-facing | Internal |
| --- | --- | --- |
| Critical | 24 hours | 72 hours |
| High | 7 days | 14 days |
| Medium | 30 days | 60 days |
| Low | 90 days | 180 days |

Exceptions require CISO approval.
"""

SHAPES["Arabic clauses, Arabic-Indic digits, RLM"] = f"""# MDS-CS-STD-004 معيار المراقبة

## ٧ المراقبة

{RLM}٧.١ يجب أن يستوعب النظام الأحداث من جميع الأنظمة.
{RLM}٧.٢ يجب إصدار تنبيه للحالات التالية:
{RLM}٧.٢.١ المصادقة الطارئة.
{RLM}٧.٢.٢ استخدام حساب إداري مشترك.
{RLM}٧.٢.٣ تجاوز مسار الوصول المتميز.
"""

SHAPES["flat prose, no structure at all"] = (
    "Our security programme covers access control, encryption and monitoring. " * 60
)

SHAPES["deep nesting, many levels"] = """# Standard

## 5 Development

### 5.1 Source control

5.1.1 All code lives in the central repository.
5.1.2 Force-push to protected branches is disabled.

### 5.2 Review

5.2.1 Two approvals are required.
5.2.2 The author may not approve their own change.

### 5.3 Release gates

5.3.1 Static analysis clean.
5.3.2 Dependency scan clean.
5.3.3 Coverage threshold met.
"""

SHAPES["DOCX shape: bullets, no numbers in text"] = """# MDS-CS-STD-003 Standard

## 8.3 Compensating controls

Where a control cannot be applied, the following compensating controls apply:

- Network segmentation isolating the asset.
- Enhanced logging with 12-month retention.
- Weekly vulnerability rescanning.
- Quarterly manual review by the security team.
- Documented exception approved by the CISO.
- Compensating control effectiveness tested annually.
- Removal plan with a target date.
"""


def show(name, text, chunk_size=1800):
    print("=" * 78)
    print(name)
    print("=" * 78)
    chunks = chunk_document(text, source_name="doc.pdf", chunk_size=chunk_size)
    for chunk in chunks:
        meta = chunk.metadata
        span = meta["clause_start"]
        if meta["clause_end"] and meta["clause_end"] != span:
            span = f"{span}-{meta['clause_end']}"
        print(
            f"  [{meta['chunk']}] {meta['kind']:6} clause={span or '-':10} "
            f"items={meta['item_count']} unit={meta['unit_id'].split(':')[-1]} "
            f"part={meta['part']}/{meta['parts']} len={len(chunk.text)}"
        )
        head = chunk.text.replace("\n", " | ")
        print(f"        {head[:120]}")
    print()
    return chunks


if __name__ == "__main__":
    for name, text in SHAPES.items():
        show(name, text)
