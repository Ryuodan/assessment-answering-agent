"""Guideline documents for the demo corpus — the knowledge the agent answers from.

Every fact about Acme Cloud Services KSA (a fictional company) is stated in
exactly one voice across these policies, so a drafted answer can be traced back
to a specific clause. Five subjects are deliberately absent — post-quantum
cryptography, ISO 22301 certification, AI/LLM governance, FedRAMP and physical
penetration testing — so the demo exercises the "not covered" path as well.
"""

from __future__ import annotations

DISCLAIMER = (
    "Synthetic demo document. Acme Cloud Services KSA is a fictional company and "
    "the controls, certificates and figures below are invented for testing."
)

# --- G1: Information Security Policy (EN, PDF) -----------------------------

INFORMATION_SECURITY_POLICY = [
    ("title", "Information Security Policy"),
    ("para", "Acme Cloud Services KSA — Document ACS-POL-001, version 4.2, approved January 2026."),
    ("para", DISCLAIMER),

    ("heading", "1. Scope and governance"),
    ("para",
     "Acme Cloud Services KSA operates a certified Information Security Management System (ISMS) "
     "covering all production platforms, corporate IT, and the personnel who operate them. The ISMS "
     "is owned by the Chief Information Security Officer, who reports to the Board Risk Committee "
     "quarterly. The Information Security Steering Committee meets monthly and is the approval "
     "authority for policy exceptions."),
    ("para",
     "Every employee and contractor completes mandatory security awareness training on joining and "
     "annually thereafter. Quarterly simulated phishing campaigns are run against all staff; the "
     "measured click rate for 2025 was 3.2 percent, against an internal target of below 5 percent."),

    ("heading", "2. Certifications and independent assurance"),
    ("para",
     "Acme Cloud Services KSA holds ISO/IEC 27001:2022 certification, certificate ACS-27001-2024, "
     "issued by the Gulf Certification Bureau and valid from March 2025 to March 2028. The scope "
     "covers cloud hosting, managed platform services and supporting corporate functions."),
    ("bullet", "ISO/IEC 27017:2015 (cloud-specific controls) — certified June 2025."),
    ("bullet", "ISO/IEC 27018:2019 (protection of PII in public cloud) — certified June 2025."),
    ("bullet",
     "SOC 2 Type II — audited annually by Northgate Assurance LLP; the most recent report covers "
     "1 November 2024 to 31 October 2025 and was issued with no exceptions."),
    ("bullet",
     "PCI DSS v4.0 — Acme completes an annual SAQ D as a service provider. Acme is not a fully "
     "certified Level 1 service provider and does not store primary account numbers."),
    ("bullet",
     "NCA Essential Cybersecurity Controls (ECC-1:2018) — self-assessed at 92 percent compliance in "
     "the Q4 2025 cycle, with the remaining items tracked to closure by Q3 2026."),
    ("bullet",
     "NCA Cloud Cybersecurity Controls (CCC-1:2020) — assessed as compliant in the Cloud Service "
     "Provider tier in September 2025."),
    ("para",
     "Certificates and the SOC 2 report are available to customers under NDA through the Acme Trust "
     "Portal. Acme does not hold FedRAMP authorisation and has no plans to pursue it, as it serves "
     "no United States federal customers."),

    ("heading", "3. Cryptography"),
    ("para",
     "All customer data is encrypted at rest using AES-256-GCM. Encryption is applied at the storage "
     "volume and object layers, and separately at the database layer for fields classified as "
     "Confidential or Restricted. Data in transit is protected with TLS 1.3; TLS 1.2 is the minimum "
     "accepted version and is permitted only for named legacy integrations under a documented "
     "exception that expires in December 2026. SSL v3, TLS 1.0 and TLS 1.1 are disabled."),
    ("para",
     "Key management uses envelope encryption. Data encryption keys are wrapped by customer master "
     "keys held in AWS Key Management Service backed by hardware security modules validated to FIPS "
     "140-2 Level 3. Master keys are rotated annually and on any suspected compromise. Customers on "
     "the Enterprise tier may supply their own keys (BYOK). No Acme employee can export key material "
     "in plaintext; key administration requires two-person authorisation."),
    ("para",
     "Acme's cryptographic standard is reviewed annually against NCA and NIST guidance. The current "
     "approved algorithm set is AES-256, RSA-3072, ECDSA P-256 and SHA-256 or stronger."),

    ("heading", "4. Logging and monitoring"),
    ("para",
     "A 24/7 Security Operations Centre monitors the estate. Security events from infrastructure, "
     "applications, identity providers and network devices are forwarded to a central SIEM. Logs are "
     "retained for 36 months in total: 12 months in hot storage available for immediate query and a "
     "further 24 months in immutable cold storage. Log integrity is protected by write-once object "
     "locking, and administrator access to the logging platform is itself logged and reviewed."),
    ("para",
     "Mean time to detect for 2025 averaged 12 minutes, and mean time to respond for critical "
     "incidents averaged 3.5 hours."),

    ("heading", "5. Vulnerability and patch management"),
    ("para",
     "Infrastructure and container images are scanned continuously; application code is scanned on "
     "every merge with static analysis and software composition analysis. Findings are remediated "
     "against the following service levels, measured from the time of validation."),
    ("table", (
        ["Severity", "Remediation SLA", "2025 attainment"],
        [
            ["Critical (CVSS 9.0-10.0)", "7 calendar days", "99.1%"],
            ["High (CVSS 7.0-8.9)", "30 calendar days", "97.4%"],
            ["Medium (CVSS 4.0-6.9)", "90 calendar days", "95.0%"],
            ["Low (CVSS 0.1-3.9)", "180 calendar days", "93.8%"],
        ],
    )),
    ("para",
     "Critical operating system patches are deployed to production within 14 days of vendor release, "
     "or within 72 hours where a vulnerability is being actively exploited in the wild."),
    ("para",
     "An independent external penetration test of the production platform is commissioned annually "
     "from Cipherpoint Security; the most recent test concluded in October 2025 and all high findings "
     "were closed within 30 days. Internal penetration testing is performed quarterly. Acme also "
     "operates a private bug bounty programme. Physical penetration testing of the data centres is "
     "not performed by Acme, as the facilities are operated by the hosting provider."),

    ("heading", "6. Personnel and physical security"),
    ("para",
     "All employees undergo identity verification and criminal background screening before their "
     "start date, and sign a confidentiality agreement covering the duration of employment and five "
     "years thereafter. Staff with production access are re-screened every three years."),
    ("para",
     "Production workloads run in Riyadh with disaster recovery in Jeddah. Both facilities are "
     "Tier III, operated under ISO 27001 and SOC 2 certified physical security programmes, with "
     "biometric access control, 24/7 guarding and 90-day CCTV retention. Acme personnel do not have "
     "unescorted physical access to customer hardware."),
]


# --- G2: Access Control Policy (EN, DOCX) ----------------------------------

ACCESS_CONTROL_POLICY = [
    ("title", "Identity and Access Control Policy"),
    ("para", "Acme Cloud Services KSA — Document ACS-POL-002, version 3.1, approved November 2025."),
    ("para", DISCLAIMER),

    ("heading", "1. Principles"),
    ("para",
     "Access to Acme systems is granted on the principles of least privilege and need to know. "
     "Entitlements are assigned to roles, never to individuals, and every role has a named business "
     "owner accountable for its contents. Shared and generic accounts are prohibited; where a "
     "platform cannot support individual accounts, the exception is registered and compensating "
     "logging is applied."),

    ("heading", "2. Authentication"),
    ("para",
     "Multi-factor authentication is mandatory for all users on all systems, without exception for "
     "seniority or convenience. Administrative and production access requires phishing-resistant "
     "FIDO2 or WebAuthn hardware authenticators; SMS one-time passcodes are not accepted anywhere in "
     "the estate. Single sign-on through the corporate identity provider is required for all "
     "business applications, and any application that cannot federate must be approved by the CISO."),
    ("para",
     "Passphrases must be at least 14 characters, are checked against a breached-credential corpus "
     "at the point of setting, and are not subject to routine expiry. Accounts lock after five failed "
     "attempts and unlock only through verified self-service or the service desk."),

    ("heading", "3. Privileged access"),
    ("para",
     "Standing administrative privilege is not permitted. Privileged sessions are brokered through a "
     "privileged access management vault which issues just-in-time credentials valid for a maximum "
     "of four hours, tied to an approved change or incident ticket. All privileged sessions are "
     "recorded in full and retained for 12 months. Break-glass accounts exist for two systems, are "
     "held in sealed escrow, and any use triggers an immediate alert to the CISO and a post-use "
     "review within one business day."),

    ("heading", "4. Joiners, movers and leavers"),
    ("para",
     "Access is provisioned from the HR system of record. On a role change, previous entitlements are "
     "revoked before new ones are granted, so privilege does not accumulate. On termination, all "
     "access is revoked within four hours of the leaving record being set, and within 30 minutes for "
     "involuntary terminations."),

    ("heading", "5. Access reviews"),
    ("para",
     "Access reviews are performed quarterly by the Head of Security together with each role owner. "
     "Privileged entitlements and third-party accounts are reviewed monthly. Any entitlement not "
     "affirmatively recertified within the review window is automatically revoked. Review evidence is "
     "retained for three years to support ISO 27001 and NCA ECC audits."),
    ("table", (
        ["Review", "Population", "Frequency", "Owner"],
        [
            ["Standard entitlement recertification", "All employees and contractors", "Quarterly", "Head of Security"],
            ["Privileged access recertification", "Vault-brokered admin roles", "Monthly", "Head of Security"],
            ["Third-party and service accounts", "Vendor and machine identities", "Monthly", "Head of Security"],
            ["Segregation-of-duties conflict scan", "Finance and production roles", "Quarterly", "Internal Audit"],
        ],
    )),

    ("heading", "6. Remote access and network segmentation"),
    ("para",
     "Remote access to production is available only from managed devices meeting the endpoint "
     "baseline, through an authenticated zero-trust access proxy; traditional flat VPN access to "
     "production was decommissioned in 2024. The production network is segmented from corporate IT "
     "with default-deny controls between zones. A zero-trust architecture programme is under way and "
     "was approximately 70 percent complete at the end of 2025, with corporate workloads scheduled "
     "for completion during 2026."),
]


# --- G3: Data Protection and PDPL Policy (EN + AR, PDF) --------------------

DATA_PROTECTION_POLICY = [
    ("title", "Data Protection and Privacy Policy (PDPL)"),
    ("para", "Acme Cloud Services KSA — Document ACS-POL-003, version 2.6, approved February 2026."),
    ("para", DISCLAIMER),

    ("heading", "1. Regulatory basis"),
    ("para",
     "This policy implements the Personal Data Protection Law of the Kingdom of Saudi Arabia and its "
     "Implementing Regulations, as supervised by the Saudi Data and AI Authority (SDAIA). Where Acme "
     "processes personal data on behalf of a customer, Acme acts as a processor and the customer "
     "remains the controller. Acme has appointed a Data Protection Officer, registered with SDAIA, "
     "reachable at dpo@acme-cloud.example."),

    ("heading", "2. Lawful basis and purpose limitation"),
    ("para",
     "Personal data is processed only on documented instructions from the controller, or where a "
     "lawful basis under the PDPL applies. Acme does not use customer personal data to train machine "
     "learning models, does not sell personal data, and does not process it for its own marketing."),

    ("heading", "3. Data residency and cross-border transfer"),
    ("para",
     "Customer personal data is stored and processed exclusively within the Kingdom of Saudi Arabia, "
     "in the Riyadh primary region with disaster recovery in Jeddah. Data is not transferred outside "
     "the Kingdom without the controller's written instruction and a transfer assessment carried out "
     "under the PDPL transfer provisions. Two sub-processors provide support tooling from outside the "
     "Kingdom; both are covered by transfer assessments and neither has access to customer content."),

    ("heading", "4. Retention and secure deletion"),
    ("para",
     "Customer data is retained for seven years from the end of the contract term, in line with "
     "regulatory record-keeping requirements, and is then securely deleted. Deletion follows NIST SP "
     "800-88 purge guidance, and a certificate of destruction is issued to the customer on request. "
     "Backups containing deleted data age out within the 35-day backup retention window. Security and "
     "audit logs are retained for 36 months. Recruitment records are retained for 12 months."),
    ("table", (
        ["Data category", "Retention period", "Disposal method"],
        [
            ["Customer content", "7 years after contract end", "Cryptographic erasure plus NIST 800-88 purge"],
            ["Security and audit logs", "36 months", "Automated expiry from immutable store"],
            ["Backups", "35 days rolling", "Automated expiry, object-lock released"],
            ["Employee HR records", "Term of employment plus 5 years", "Secure shredding and verified deletion"],
            ["CCTV footage", "90 days", "Automated overwrite"],
            ["Recruitment records", "12 months", "Verified deletion"],
        ],
    )),

    ("heading", "5. Data subject rights"),
    ("para",
     "Acme supports controllers in meeting data subject requests for access, rectification, "
     "destruction, and objection. Requests received directly by Acme are forwarded to the relevant "
     "controller within two business days. Acme's contractual commitment is to provide the technical "
     "assistance needed for a controller to respond within the 30-day statutory period."),

    ("heading", "6. Breach notification"),
    ("para",
     "A confirmed personal data breach is notified to SDAIA within 72 hours of Acme becoming aware of "
     "it, in the form required by the Implementing Regulations. Affected controllers are notified "
     "within 24 hours of confirmation, ahead of the regulatory deadline, so that they can meet their "
     "own obligations to data subjects. Notification includes the nature of the breach, the "
     "categories and approximate volume of records affected, the likely consequences, and the "
     "measures taken. Acme maintains a breach register; no reportable personal data breach occurred "
     "during 2024 or 2025."),

    ("heading", "7. Privacy by design"),
    ("para",
     "A data protection impact assessment is required before any new processing activity involving "
     "sensitive personal data, large-scale profiling, or a new cross-border flow. Assessments are "
     "reviewed by the DPO and re-run when the processing materially changes."),

    ("heading", "8. سياسة حماية البيانات — ملخص بالعربية"),
    ("para",
     "تلتزم شركة أكمي للخدمات السحابية بنظام حماية البيانات الشخصية في المملكة العربية السعودية "
     "ولوائحه التنفيذية، وتخضع لإشراف الهيئة السعودية للبيانات والذكاء الاصطناعي. تعمل الشركة بصفة "
     "معالج للبيانات نيابة عن العميل الذي يظل هو المتحكم في البيانات."),
    ("para",
     "تُخزَّن البيانات الشخصية للعملاء ومعالجتها داخل المملكة العربية السعودية حصراً، في منطقة "
     "الرياض الأساسية مع موقع تعافٍ من الكوارث في جدة. ولا تُنقل البيانات خارج المملكة إلا بتعليمات "
     "خطية من المتحكم وبعد إجراء تقييم للنقل."),
    ("para",
     "يتم الاحتفاظ ببيانات العملاء لمدة سبع سنوات من انتهاء العقد وفقاً للمتطلبات التنظيمية، ثم يتم "
     "حذفها بشكل آمن وفق إرشادات NIST SP 800-88، مع إصدار شهادة إتلاف عند الطلب. أما سجلات الأمن "
     "والتدقيق فيتم الاحتفاظ بها لمدة ستة وثلاثين شهراً."),
    ("para",
     "في حال وقوع اختراق مؤكد للبيانات الشخصية، تُبلَّغ الهيئة السعودية للبيانات والذكاء الاصطناعي "
     "خلال اثنتين وسبعين ساعة من العلم بالحادثة، ويُبلَّغ العملاء المتأثرون خلال أربع وعشرين ساعة من "
     "تأكيد الحادثة. وقد عيّنت الشركة مسؤولاً لحماية البيانات مسجلاً لدى الهيئة."),
]


# --- G4: Incident Response and Business Continuity (EN, DOCX) --------------

INCIDENT_RESPONSE_POLICY = [
    ("title", "Incident Response and Business Continuity Policy"),
    ("para", "Acme Cloud Services KSA — Document ACS-POL-004, version 3.4, approved December 2025."),
    ("para", DISCLAIMER),

    ("heading", "1. Incident response capability"),
    ("para",
     "Acme operates a 24/7 Security Operations Centre staffed by its own analysts, supported by a "
     "retained incident response firm under a pre-signed engagement with a four-hour response "
     "commitment. The incident response plan follows the NIST SP 800-61 lifecycle of preparation, "
     "detection and analysis, containment, eradication and recovery, and post-incident activity."),
    ("para",
     "The plan is tested twice a year through tabletop exercises involving Engineering, Legal, "
     "Communications and Executive management. The most recent exercise, in November 2025, simulated "
     "ransomware in a shared platform service; four improvement actions were raised and all were "
     "closed by January 2026."),

    ("heading", "2. Severity classification and response targets"),
    ("table", (
        ["Severity", "Definition", "Acknowledge", "Customer notification"],
        [
            ["P1 Critical", "Confirmed breach of customer data, or full service outage", "15 minutes", "Within 24 hours of confirmation"],
            ["P2 High", "Partial outage, or credible threat to customer data", "30 minutes", "Within 48 hours if customer-affecting"],
            ["P3 Medium", "Degraded service, contained security event", "4 hours", "In the monthly service report"],
            ["P4 Low", "Isolated event, no customer impact", "1 business day", "Not routinely notified"],
        ],
    )),
    ("para",
     "During 2025 Acme recorded 34 security events that met the incident threshold. None was a "
     "reportable personal data breach. Mean time to respond for P1 incidents was 3.5 hours."),

    ("heading", "3. Regulatory and customer notification"),
    ("para",
     "Confirmed personal data breaches are notified to SDAIA within 72 hours under the PDPL. "
     "Cybersecurity incidents meeting the National Cybersecurity Authority reporting threshold are "
     "reported to the NCA through the designated channel. Affected customers are notified within 24 "
     "hours of confirmation. Acme will not withhold notification pending completion of the "
     "investigation; initial notice is issued on confirmation and updated as facts are established."),

    ("heading", "4. Backup and recovery"),
    ("para",
     "Customer data is backed up hourly on an incremental basis and daily in full. Backups are "
     "retained for 35 days, encrypted with AES-256, and written to immutable object storage with "
     "object-lock enabled so that they cannot be altered or deleted within the retention window, "
     "including by an administrator. Backups are replicated between the Riyadh and Jeddah regions and "
     "never leave the Kingdom."),
    ("para",
     "Restore tests are performed quarterly against a randomly selected customer tenant, and the "
     "results are recorded as ISMS evidence. The most recent test, in January 2026, restored a "
     "1.4 terabyte tenant in 2 hours and 41 minutes."),

    ("heading", "5. Continuity objectives"),
    ("table", (
        ["Service tier", "RTO", "RPO", "Availability commitment"],
        [
            ["Enterprise platform", "4 hours", "15 minutes", "99.95% monthly"],
            ["Standard platform", "8 hours", "1 hour", "99.9% monthly"],
            ["Corporate IT services", "24 hours", "24 hours", "Best effort"],
        ],
    )),
    ("para",
     "A full disaster recovery failover to the Jeddah region is exercised annually; the October 2025 "
     "exercise achieved failover in 2 hours 10 minutes against the 4-hour objective. Acme's business "
     "continuity programme is aligned to ISO 22301 but Acme is not certified against ISO 22301 and "
     "has no current plan to seek certification."),

    ("heading", "6. Cyber insurance"),
    ("para",
     "Acme carries cyber liability insurance with a limit of 10 million United States dollars per "
     "claim, covering incident response costs, regulatory defence, and third-party liability. The "
     "certificate of insurance is available to customers on request."),
]


# --- G5: Third Party and Cloud Security (EN, PDF) --------------------------

THIRD_PARTY_POLICY = [
    ("title", "Third-Party and Cloud Security Policy"),
    ("para", "Acme Cloud Services KSA — Document ACS-POL-005, version 2.2, approved October 2025."),
    ("para", DISCLAIMER),

    ("heading", "1. Vendor tiering"),
    ("para",
     "Every supplier is tiered at onboarding according to the sensitivity of the data it can reach "
     "and its criticality to service delivery. The tier sets the depth of due diligence and the "
     "frequency of reassessment."),
    ("table", (
        ["Tier", "Criteria", "Due diligence", "Reassessment"],
        [
            ["Tier 1 Critical", "Processes customer data, or a single point of failure", "Full assessment, evidence review, right-to-audit clause", "Annual"],
            ["Tier 2 Important", "Access to internal systems, no customer data", "Questionnaire plus certification review", "Every 2 years"],
            ["Tier 3 Standard", "No system or data access", "Baseline screening", "Every 3 years"],
        ],
    )),
    ("para",
     "No Tier 1 supplier is engaged without a completed assessment, a signed data processing "
     "agreement, and confirmation that its own security certifications are current. Contracts with "
     "Tier 1 suppliers include a right to audit, a security incident notification obligation of 24 "
     "hours, and a requirement to flow equivalent obligations down to their own sub-processors."),

    ("heading", "2. Sub-processors"),
    ("para",
     "Acme maintains a published sub-processor register on the Trust Portal. Customers receive 30 "
     "days' written notice before a new sub-processor is engaged and may object in that period. As of "
     "February 2026 Acme uses nine sub-processors: seven operate wholly within the Kingdom and two "
     "provide tooling from outside it under completed transfer assessments, neither with access to "
     "customer content."),

    ("heading", "3. Cloud controls"),
    ("para",
     "Acme is assessed as compliant with the NCA Cloud Cybersecurity Controls (CCC-1:2020) in the "
     "Cloud Service Provider tier. Customer environments are logically segregated by tenant, with "
     "separate encryption keys per tenant and enforced isolation at the network, compute and storage "
     "layers. Multi-tenancy isolation is tested as part of the annual external penetration test."),
    ("para",
     "Infrastructure is defined as code and deployed through a reviewed pipeline; manual changes to "
     "production are blocked by policy-as-code and generate an alert. Cloud security posture "
     "management runs continuously against CIS benchmarks, with a current compliance score of 96 "
     "percent against the CIS AWS Foundations Benchmark."),

    ("heading", "4. Customer assurance"),
    ("para",
     "Customers may request the SOC 2 Type II report, ISO certificates, penetration test summary "
     "letters, and the annual NCA ECC self-assessment summary under NDA. Enterprise customers have a "
     "contractual right to audit Acme once per year with 30 days' notice, or more frequently "
     "following a material incident. Acme responds to customer security questionnaires within 15 "
     "business days."),
]


# --- G6: NCA ECC / SAMA CSF control mapping (EN + AR headers, PDF) ---------

CONTROL_MAPPING = [
    ("title", "NCA ECC and SAMA CSF Control Mapping"),
    ("para", "Acme Cloud Services KSA — Document ACS-REG-001, Q4 2025 assessment cycle."),
    ("para", DISCLAIMER),
    ("para",
     "This register maps the National Cybersecurity Authority Essential Cybersecurity Controls "
     "(ECC-1:2018) and the SAMA Cyber Security Framework to Acme's implemented controls and the "
     "internal policy that governs each one. Overall assessed compliance for the Q4 2025 cycle was "
     "92 percent. Items marked Partial carry a remediation date."),
    ("table", (
        ["Control", "Domain", "Acme implementation", "Status", "Policy"],
        [
            ["ECC 1-1", "Cybersecurity governance and strategy",
             "CISO reports to Board Risk Committee quarterly; strategy approved annually", "Compliant", "ACS-POL-001"],
            ["ECC 1-3", "Cybersecurity risk management",
             "Risk register reviewed monthly by the Steering Committee", "Compliant", "ACS-POL-001"],
            ["ECC 1-5", "Cybersecurity in human resources",
             "Pre-employment screening, NDA, annual training, 3-yearly re-screening", "Compliant", "ACS-POL-001"],
            ["ECC 2-2", "Identity and access management",
             "MFA everywhere, FIDO2 for admins, JIT privilege, quarterly recertification", "Compliant", "ACS-POL-002"],
            ["ECC 2-3", "Information system protection",
             "Hardened baselines, EDR on all endpoints and servers, CIS benchmarks", "Compliant", "ACS-POL-001"],
            ["ECC 2-5", "Network security management",
             "Segmentation, default-deny, WAF, DDoS protection; zero-trust 70% complete", "Partial — Q4 2026", "ACS-POL-002"],
            ["ECC 2-7", "Cryptography",
             "AES-256-GCM at rest, TLS 1.3 in transit, FIPS 140-2 Level 3 HSM key custody", "Compliant", "ACS-POL-001"],
            ["ECC 2-8", "Backup and recovery management",
             "Hourly incremental, 35-day immutable retention, quarterly restore tests", "Compliant", "ACS-POL-004"],
            ["ECC 2-10", "Cybersecurity event logs and monitoring",
             "24/7 SOC, central SIEM, 36-month immutable log retention", "Compliant", "ACS-POL-001"],
            ["ECC 2-11", "Cybersecurity incident management",
             "NIST 800-61 lifecycle, biannual tabletop, NCA and SDAIA reporting paths", "Compliant", "ACS-POL-004"],
            ["ECC 2-12", "Physical security",
             "Tier III facilities, biometric access, 90-day CCTV; operated by hosting provider", "Compliant", "ACS-POL-001"],
            ["ECC 3-1", "Business continuity management",
             "RTO 4h / RPO 15min, annual DR failover exercise; ISO 22301 aligned, not certified", "Partial — no plan", "ACS-POL-004"],
            ["ECC 4-1", "Third-party cybersecurity",
             "Vendor tiering, right-to-audit for Tier 1, 30-day sub-processor notice", "Compliant", "ACS-POL-005"],
            ["ECC 4-2", "Cloud computing cybersecurity",
             "CCC-1:2020 CSP tier assessed compliant September 2025", "Compliant", "ACS-POL-005"],
            ["SAMA 3.3.5", "Identity and access management",
             "Equivalent to ECC 2-2; assessed at maturity level 3 for financial-sector clients", "Compliant", "ACS-POL-002"],
            ["SAMA 3.3.9", "Cryptography",
             "Equivalent to ECC 2-7; annual key rotation, BYOK for Enterprise tier", "Compliant", "ACS-POL-001"],
            ["SAMA 3.3.14", "Threat management",
             "Threat intelligence feeds, annual external and quarterly internal penetration testing", "Compliant", "ACS-POL-001"],
            ["SAMA 3.4.1", "Third-party cyber security",
             "Equivalent to ECC 4-1; DPA and security schedule required before onboarding", "Compliant", "ACS-POL-005"],
        ],
    )),
    ("heading", "Known gaps carried into 2026 / الثغرات المعروفة"),
    ("para",
     "Two control areas remain partially implemented and are tracked in the ISMS improvement plan: "
     "completion of the zero-trust architecture for corporate workloads, targeted at Q4 2026, and "
     "ISO 22301 certification, which the Steering Committee has decided not to pursue at this time. "
     "Acme has no post-quantum cryptography migration roadmap, and no formal governance policy for "
     "the internal use of generative AI; a draft of the latter is scheduled for approval in Q3 2026."),
]


# --- G7: Arabic information security policy (AR, DOCX) ---------------------

ARABIC_SECURITY_POLICY = [
    ("title", "سياسة أمن المعلومات"),
    ("para", "شركة أكمي للخدمات السحابية — وثيقة رقم ACS-POL-001-AR، الإصدار 4.2، معتمدة في يناير 2026."),
    ("para",
     "وثيقة تجريبية اصطناعية. شركة أكمي للخدمات السحابية شركة وهمية، وجميع الضوابط والشهادات "
     "والأرقام الواردة أدناه مُصطنعة لأغراض الاختبار."),

    ("heading", "١. النطاق والحوكمة"),
    ("para",
     "تُطبِّق شركة أكمي للخدمات السحابية نظام إدارة أمن المعلومات المعتمد وفق معيار آيزو ٢٧٠٠١:٢٠٢٢، "
     "ويغطي جميع المنصات الإنتاجية وتقنية المعلومات المؤسسية والعاملين عليها. يتولى الرئيس التنفيذي "
     "لأمن المعلومات مسؤولية النظام ويرفع تقاريره إلى لجنة المخاطر في مجلس الإدارة بشكل ربع سنوي."),
    ("para",
     "يخضع جميع الموظفين والمتعاقدين لبرنامج توعية بأمن المعلومات عند الالتحاق وسنوياً بعد ذلك، "
     "وتُنفَّذ حملات تصيّد تجريبية بشكل ربع سنوي، وقد بلغت نسبة الاستجابة لها ٣٫٢٪ خلال عام ٢٠٢٥."),

    ("heading", "٢. الشهادات والاعتمادات"),
    ("para",
     "تحمل الشركة شهادة آيزو ٢٧٠٠١:٢٠٢٢ رقم ACS-27001-2024 الصادرة عن مكتب الخليج للاعتماد وسارية "
     "من مارس ٢٠٢٥ حتى مارس ٢٠٢٨، إضافة إلى شهادتي آيزو ٢٧٠١٧ وآيزو ٢٧٠١٨ الصادرتين في يونيو ٢٠٢٥، "
     "وتقرير SOC 2 Type II السنوي. كما بلغت نسبة الالتزام بالضوابط الأساسية للأمن السيبراني "
     "الصادرة عن الهيئة الوطنية للأمن السيبراني ٩٢٪ في دورة تقييم الربع الرابع من عام ٢٠٢٥."),

    ("heading", "٣. التشفير"),
    ("para",
     "تُشفَّر بيانات العملاء أثناء التخزين باستخدام خوارزمية AES-256-GCM، وأثناء النقل باستخدام "
     "بروتوكول TLS 1.3، مع اعتماد الإصدار TLS 1.2 كحد أدنى للتكاملات القديمة المستثناة. تُدار "
     "المفاتيح عبر وحدات أمنية مادية معتمدة وفق معيار FIPS 140-2 المستوى الثالث، ويتم تدوير "
     "المفاتيح الرئيسية سنوياً وعند الاشتباه في أي اختراق."),

    ("heading", "٤. إدارة الهوية والدخول"),
    ("para",
     "المصادقة متعددة العوامل إلزامية لجميع المستخدمين دون استثناء، ويُشترط استخدام مفاتيح مادية "
     "من نوع FIDO2 للدخول الإداري وللأنظمة الإنتاجية. ولا يُسمح بالصلاحيات الإدارية الدائمة، بل "
     "تُمنح عند الحاجة ولمدة أقصاها أربع ساعات مرتبطة بتذكرة تغيير أو حادثة معتمدة. تُراجع الصلاحيات "
     "بشكل ربع سنوي من قبل رئيس قسم الأمن، وتُراجع الصلاحيات المميزة شهرياً."),

    ("heading", "٥. الاحتفاظ بالبيانات وحذفها"),
    ("para",
     "يتم الاحتفاظ ببيانات العملاء لمدة سبع سنوات من انتهاء العقد وفقاً للمتطلبات التنظيمية، ثم "
     "يتم حذفها بشكل آمن وفق إرشادات NIST SP 800-88. وتُحفظ سجلات الأمن والتدقيق لمدة ستة وثلاثين "
     "شهراً، بينما تُحفظ النسخ الاحتياطية لمدة خمسة وثلاثين يوماً في تخزين غير قابل للتعديل."),

    ("heading", "٦. الاستجابة للحوادث واستمرارية الأعمال"),
    ("para",
     "يعمل مركز العمليات الأمنية على مدار الساعة طوال أيام الأسبوع. وفي حال وقوع اختراق مؤكد "
     "للبيانات الشخصية، تُبلَّغ الهيئة السعودية للبيانات والذكاء الاصطناعي خلال اثنتين وسبعين ساعة، "
     "ويُبلَّغ العملاء المتأثرون خلال أربع وعشرين ساعة. ويبلغ هدف زمن الاستعادة أربع ساعات، وهدف "
     "نقطة الاستعادة خمس عشرة دقيقة، مع تنفيذ تمرين تحوّل كامل إلى موقع جدة سنوياً."),

    ("heading", "٧. موقع البيانات"),
    ("para",
     "تُخزَّن بيانات العملاء وتُعالَج داخل المملكة العربية السعودية حصراً، في مركز البيانات الرئيسي "
     "بالرياض ومركز التعافي من الكوارث بجدة، ولا تُنقل خارج المملكة إلا بتعليمات خطية من العميل "
     "وبعد استكمال تقييم النقل المطلوب نظاماً."),
]
