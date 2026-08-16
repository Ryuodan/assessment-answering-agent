"""Tabular demo datasets.

The app ingests only PDF and DOCX (`src.documents.SUPPORTED_SUFFIXES`), so
these registers are emitted twice: as CSV for spreadsheet use, and rendered
into a DOCX register that can actually be uploaded as a guideline.
"""

from __future__ import annotations

ASSET_INVENTORY = (
    ["Asset ID", "Asset", "Classification", "Environment", "Owner", "Region", "Encryption"],
    [
        ["AST-0001", "Tenant object storage", "Restricted", "Production", "Platform Engineering", "Riyadh", "AES-256-GCM"],
        ["AST-0002", "Tenant metadata database", "Restricted", "Production", "Platform Engineering", "Riyadh", "AES-256-GCM + field level"],
        ["AST-0003", "Identity provider", "Confidential", "Production", "Security Engineering", "Riyadh", "AES-256-GCM"],
        ["AST-0004", "Privileged access vault", "Restricted", "Production", "Security Engineering", "Riyadh", "AES-256-GCM (HSM)"],
        ["AST-0005", "SIEM and log lake", "Confidential", "Production", "Security Operations", "Riyadh", "AES-256-GCM (object lock)"],
        ["AST-0006", "Backup vault", "Restricted", "Production", "Platform Engineering", "Riyadh + Jeddah", "AES-256-GCM (immutable)"],
        ["AST-0007", "DR replica cluster", "Restricted", "DR", "Platform Engineering", "Jeddah", "AES-256-GCM"],
        ["AST-0008", "CI/CD pipeline", "Confidential", "Production", "Platform Engineering", "Riyadh", "AES-256-GCM"],
        ["AST-0009", "Corporate email and collaboration", "Internal", "Corporate", "IT Services", "Riyadh", "Provider managed"],
        ["AST-0010", "Trust Portal", "Public", "Production", "Compliance", "Riyadh", "TLS 1.3 only"],
        ["AST-0011", "Staging environment", "Internal", "Non-production", "Platform Engineering", "Riyadh", "AES-256-GCM (synthetic data only)"],
        ["AST-0012", "Customer support desk", "Confidential", "Corporate", "Customer Success", "Riyadh", "Provider managed"],
    ],
)

SECURITY_INCIDENTS_2025 = (
    ["Incident ID", "Date", "Severity", "Category", "Summary", "Personal data breach", "Time to detect", "Time to resolve", "Status"],
    [
        ["INC-2025-004", "2025-02-11", "P2", "Phishing", "Credential phishing against three staff; MFA blocked all attempts", "No", "8 min", "2h 10m", "Closed"],
        ["INC-2025-009", "2025-03-27", "P3", "Misconfiguration", "Staging bucket briefly public; synthetic data only, no customer content", "No", "22 min", "1h 05m", "Closed"],
        ["INC-2025-014", "2025-05-02", "P1", "Availability", "Storage controller failure degraded one tenant for 41 minutes", "No", "3 min", "3h 40m", "Closed"],
        ["INC-2025-018", "2025-06-19", "P3", "Vulnerability", "Critical CVE in third-party library; patched across estate in 4 days", "No", "1h 15m", "4d", "Closed"],
        ["INC-2025-021", "2025-07-08", "P2", "Insider risk", "Departing employee attempted bulk export; DLP blocked and access revoked", "No", "6 min", "5h 30m", "Closed"],
        ["INC-2025-026", "2025-09-14", "P4", "Physical", "Tailgating attempt at Riyadh facility; stopped by guard, reported by provider", "No", "Immediate", "1d", "Closed"],
        ["INC-2025-030", "2025-10-30", "P2", "DDoS", "Volumetric attack peaking at 340 Gbps absorbed with no customer impact", "No", "2 min", "1h 50m", "Closed"],
        ["INC-2025-034", "2025-12-06", "P3", "Third party", "Sub-processor disclosed a vulnerability; assessed as not exploitable at Acme", "No", "n/a", "6d", "Closed"],
    ],
)

VENDOR_REGISTER = (
    ["Vendor ID", "Vendor", "Service", "Tier", "Customer data access", "Location", "Certifications", "Last assessed", "Next review"],
    [
        ["VND-001", "Northwind Cloud Infrastructure", "IaaS hosting", "Tier 1 Critical", "Encrypted at rest only", "Riyadh, KSA", "ISO 27001, ISO 27017, SOC 2", "2025-11-03", "2026-11-03"],
        ["VND-002", "Cipherpoint Security", "Penetration testing", "Tier 1 Critical", "Time-boxed test access", "Riyadh, KSA", "CREST, ISO 27001", "2025-10-12", "2026-10-12"],
        ["VND-003", "Northgate Assurance LLP", "SOC 2 audit", "Tier 2 Important", "Evidence only", "Riyadh, KSA", "Licensed audit firm", "2025-09-01", "2027-09-01"],
        ["VND-004", "Sahab Managed DNS", "DNS and DDoS", "Tier 1 Critical", "None", "Riyadh, KSA", "ISO 27001", "2025-08-20", "2026-08-20"],
        ["VND-005", "Meridian Observability", "APM tooling", "Tier 2 Important", "Metrics and traces, no content", "Frankfurt, Germany", "ISO 27001, SOC 2", "2025-07-15", "2027-07-15"],
        ["VND-006", "Helpdesk Systems Co", "Ticketing platform", "Tier 2 Important", "Support metadata", "Dubai, UAE", "ISO 27001", "2025-06-30", "2027-06-30"],
        ["VND-007", "Jusoor Payroll Services", "Payroll", "Tier 2 Important", "Employee data, no customer data", "Riyadh, KSA", "ISO 27001", "2025-05-18", "2027-05-18"],
        ["VND-008", "Riyadh Secure Shredding", "Media destruction", "Tier 3 Standard", "Decommissioned media", "Riyadh, KSA", "NAID AAA", "2025-04-02", "2028-04-02"],
        ["VND-009", "Falcon Threat Intel", "Threat intelligence feed", "Tier 3 Standard", "None", "Riyadh, KSA", "ISO 27001", "2025-03-11", "2028-03-11"],
    ],
)

VULNERABILITY_FINDINGS = (
    ["Finding ID", "Discovered", "Severity", "CVSS", "Asset", "Source", "SLA (days)", "Days to close", "Within SLA"],
    [
        ["VLN-2026-011", "2026-01-06", "Critical", "9.8", "Tenant metadata database", "Container scan", "7", "3", "Yes"],
        ["VLN-2026-014", "2026-01-09", "High", "8.1", "CI/CD pipeline", "SCA", "30", "11", "Yes"],
        ["VLN-2026-019", "2026-01-15", "Medium", "6.4", "Trust Portal", "DAST", "90", "34", "Yes"],
        ["VLN-2026-023", "2026-01-21", "High", "7.5", "Identity provider", "External pen test", "30", "18", "Yes"],
        ["VLN-2026-027", "2026-02-02", "Low", "3.1", "Staging environment", "Infrastructure scan", "180", "62", "Yes"],
        ["VLN-2026-031", "2026-02-10", "Critical", "9.1", "Tenant object storage", "Threat intel advisory", "7", "2", "Yes"],
        ["VLN-2026-036", "2026-02-18", "Medium", "5.3", "Corporate endpoint fleet", "EDR posture", "90", "95", "No"],
        ["VLN-2026-041", "2026-03-01", "High", "7.9", "Backup vault", "Internal pen test", "30", "26", "Yes"],
    ],
)

ACCESS_REVIEW_Q1_2026 = (
    ["Review ID", "Population", "Identities reviewed", "Entitlements revoked", "Exceptions raised", "Completed", "Reviewer"],
    [
        ["ACR-2026Q1-01", "All employees and contractors", "412", "37", "2", "2026-01-28", "Head of Security"],
        ["ACR-2026Q1-02", "Privileged vault roles (January)", "48", "6", "0", "2026-01-14", "Head of Security"],
        ["ACR-2026Q1-03", "Privileged vault roles (February)", "47", "3", "1", "2026-02-13", "Head of Security"],
        ["ACR-2026Q1-04", "Privileged vault roles (March)", "45", "2", "0", "2026-03-13", "Head of Security"],
        ["ACR-2026Q1-05", "Third-party and service accounts", "96", "11", "3", "2026-03-19", "Head of Security"],
        ["ACR-2026Q1-06", "Segregation-of-duties conflict scan", "412", "4", "1", "2026-03-25", "Internal Audit"],
    ],
)

DATASETS = {
    "asset_inventory": ("Asset Inventory", ASSET_INVENTORY),
    "security_incidents_2025": ("Security Incident Log 2025", SECURITY_INCIDENTS_2025),
    "vendor_register": ("Third-Party Vendor Register", VENDOR_REGISTER),
    "vulnerability_findings_2026q1": ("Vulnerability Findings Q1 2026", VULNERABILITY_FINDINGS),
    "access_reviews_2026q1": ("Access Review Log Q1 2026", ACCESS_REVIEW_Q1_2026),
}
