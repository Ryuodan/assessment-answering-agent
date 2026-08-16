"""Assessment questionnaires for the demo corpus.

Two kinds:

  PRIOR_*  completed forms. Indexed as question/answer pairs, they teach the
           agent the house style — how Acme phrases a "yes", how much evidence
           it volunteers, when it qualifies an answer.
  NEW_*    blank forms with an empty answer column, which is what the question
           extractor keys on. These are the ones you submit for answering.

The new forms deliberately include questions the policies cannot answer, so a
demo run shows the low-confidence path alongside the confident one.
"""

from __future__ import annotations

NOTE = (
    "Synthetic demo document. Acme Cloud Services KSA is fictional and every "
    "answer below is invented for testing."
)


def _blank(rows: list[tuple[str, str]]) -> list[list[str]]:
    """Number a list of (question, section) pairs and leave the answer empty."""
    return [[str(i), question, section, ""] for i, (question, section) in enumerate(rows, 1)]


def _answered(rows: list[tuple[str, str]]) -> list[list[str]]:
    return [[str(i), question, answer] for i, (question, answer) in enumerate(rows, 1)]


# --- P1: completed vendor security assessment, 2024 (EN, DOCX) -------------

PRIOR_VENDOR_2024 = [
    ("title", "Vendor Security Assessment 2024 — Completed Response"),
    ("para", "Respondent: Acme Cloud Services KSA. Submitted to Meridian Bank, 14 November 2024."),
    ("para", NOTE),
    ("table", (
        ["#", "Question", "Response"],
        _answered([
            ("Do you hold a recognised information security certification?",
             "Yes. Acme is certified to ISO/IEC 27001:2022 under certificate ACS-27001-2024, issued by "
             "the Gulf Certification Bureau and valid from March 2025 to March 2028. We also hold "
             "ISO/IEC 27017 and ISO/IEC 27018, and undergo an annual SOC 2 Type II audit. Certificates "
             "are available under NDA through our Trust Portal."),
            ("How is customer data protected at rest?",
             "All customer data is encrypted at rest with AES-256-GCM. Keys are managed in AWS KMS "
             "backed by FIPS 140-2 Level 3 hardware security modules, rotated annually, and Enterprise "
             "customers may bring their own keys. No individual can export key material in plaintext."),
            ("How is data protected in transit?",
             "Data in transit is encrypted with TLS 1.3. TLS 1.2 is our minimum accepted version and is "
             "permitted only for a small number of named legacy integrations under a documented "
             "exception. TLS 1.1 and below are disabled."),
            ("Do you enforce multi-factor authentication for production access?",
             "Yes. MFA is mandatory for all users on all systems. Administrative and production access "
             "requires phishing-resistant FIDO2 or WebAuthn hardware keys; we do not accept SMS "
             "one-time passcodes anywhere in the estate."),
            ("How frequently are user access rights reviewed?",
             "Standard entitlements are recertified quarterly by the Head of Security with each role "
             "owner. Privileged and third-party accounts are reviewed monthly. Anything not "
             "affirmatively recertified within the window is revoked automatically."),
            ("Where is customer data stored, and does it leave the country?",
             "Customer data is stored and processed exclusively within the Kingdom of Saudi Arabia — "
             "primary region Riyadh, disaster recovery Jeddah. It is not transferred outside the "
             "Kingdom without the controller's written instruction and a completed PDPL transfer "
             "assessment."),
            ("ما هي مدة الاحتفاظ ببيانات العملاء؟",
             "يتم الاحتفاظ ببيانات العملاء لمدة سبع سنوات من انتهاء العقد وفقاً للمتطلبات التنظيمية، "
             "ثم يتم حذفها بشكل آمن وفق إرشادات NIST SP 800-88، مع إصدار شهادة إتلاف عند الطلب."),
            ("What is your incident notification commitment?",
             "We notify affected customers within 24 hours of confirming an incident, and we notify "
             "SDAIA within 72 hours where a personal data breach is confirmed. We issue initial notice "
             "on confirmation rather than waiting for the investigation to conclude."),
            ("Describe your backup regime and whether backups are tested.",
             "Backups run hourly incremental and daily full, retained 35 days, encrypted with AES-256 "
             "and written to immutable object-locked storage that cannot be deleted within the "
             "retention window. Restores are tested quarterly against a randomly selected tenant."),
            ("What are your recovery time and recovery point objectives?",
             "For the Enterprise platform, RTO is 4 hours and RPO is 15 minutes, against a 99.95 "
             "percent monthly availability commitment. A full failover to Jeddah is exercised annually."),
            ("Do you perform penetration testing?",
             "Yes. An independent external penetration test of the production platform is commissioned "
             "annually from Cipherpoint Security, and internal testing is performed quarterly. We also "
             "run a private bug bounty. Summary letters are available under NDA."),
            ("What are your vulnerability remediation timelines?",
             "Critical findings are remediated within 7 days, high within 30 days, medium within 90 and "
             "low within 180. Critical operating system patches reach production within 14 days, or "
             "within 72 hours where a vulnerability is being actively exploited."),
            ("Do you use sub-processors, and how are customers informed of changes?",
             "Yes. Our sub-processor register is published on the Trust Portal and customers receive 30 "
             "days' written notice before a new sub-processor is engaged, with a right to object in "
             "that period."),
            ("Are your staff screened before employment?",
             "Yes. All employees undergo identity verification and criminal background screening before "
             "their start date and sign a confidentiality agreement. Staff with production access are "
             "re-screened every three years."),
        ]),
    )),
]


# --- P2: completed NCA ECC self-assessment, 2025 (EN, PDF) -----------------

PRIOR_NCA_ECC_2025 = [
    ("title", "NCA ECC-1:2018 Self-Assessment — 2025 Cycle"),
    ("para", "Acme Cloud Services KSA. Internal self-assessment completed 18 December 2025."),
    ("para", NOTE),
    ("table", (
        ["#", "Question", "Response"],
        _answered([
            ("What is your overall assessed compliance against the NCA Essential Cybersecurity Controls?",
             "92 percent for the Q4 2025 cycle. The residual items are the completion of zero-trust "
             "architecture for corporate workloads, targeted at Q4 2026, and ISO 22301 certification, "
             "which the Steering Committee has decided not to pursue."),
            ("Who is accountable for cybersecurity governance, and to whom do they report?",
             "The Chief Information Security Officer owns the ISMS and reports to the Board Risk "
             "Committee quarterly. The Information Security Steering Committee meets monthly and is the "
             "approval authority for policy exceptions."),
            ("How are cybersecurity risks identified and tracked? (ECC 1-3)",
             "A central risk register is reviewed monthly by the Steering Committee, with each risk "
             "assigned an owner, a treatment plan and a review date."),
            ("Describe your network security controls. (ECC 2-5)",
             "The production network is segmented from corporate IT with default-deny controls between "
             "zones, fronted by a WAF and DDoS protection. Remote access is through an authenticated "
             "zero-trust proxy from managed devices only; flat VPN access to production was "
             "decommissioned in 2024. The zero-trust programme is approximately 70 percent complete."),
            ("How long are security event logs retained? (ECC 2-10)",
             "36 months in total — 12 months hot for immediate query and 24 months in immutable cold "
             "storage. Log integrity is protected by write-once object locking, and administrator "
             "access to the logging platform is itself logged and reviewed."),
            ("What is your mean time to detect and respond?",
             "Mean time to detect averaged 12 minutes across 2025. Mean time to respond for P1 critical "
             "incidents averaged 3.5 hours."),
            ("How often is the incident response plan tested? (ECC 2-11)",
             "Twice a year through tabletop exercises involving Engineering, Legal, Communications and "
             "Executive management. The November 2025 exercise simulated ransomware in a shared "
             "platform service and raised four improvement actions, all closed by January 2026."),
            ("How many security incidents did you record in the reporting period?",
             "34 events met the incident threshold during 2025. None was a reportable personal data "
             "breach, and no reportable breach occurred in 2024 either."),
            ("How is compliance with the Cloud Cybersecurity Controls demonstrated? (ECC 4-2)",
             "Acme was assessed as compliant with NCA CCC-1:2020 in the Cloud Service Provider tier in "
             "September 2025. Tenant isolation is enforced at the network, compute and storage layers "
             "with separate encryption keys per tenant, and is tested in the annual external "
             "penetration test."),
            ("How do you govern third-party cybersecurity risk? (ECC 4-1)",
             "Suppliers are tiered at onboarding by data sensitivity and criticality. Tier 1 suppliers "
             "require a full assessment, evidence review, a signed data processing agreement, a "
             "right-to-audit clause and a 24-hour incident notification obligation, and are reassessed "
             "annually."),
            ("What is your secure configuration baseline? (ECC 2-3)",
             "Hardened build baselines derived from CIS benchmarks, with EDR deployed on all endpoints "
             "and servers. Cloud security posture management runs continuously; the current score "
             "against the CIS AWS Foundations Benchmark is 96 percent."),
            ("Is infrastructure change managed through a controlled pipeline?",
             "Yes. Infrastructure is defined as code and deployed through a reviewed pipeline. Manual "
             "changes to production are blocked by policy-as-code and generate an alert."),
        ]),
    )),
]


# --- P3: completed PDPL review, 2025 (AR, DOCX) ----------------------------

PRIOR_PDPL_2025_AR = [
    ("title", "مراجعة الالتزام بنظام حماية البيانات الشخصية — ٢٠٢٥"),
    ("para", "الجهة المستجيبة: شركة أكمي للخدمات السحابية. تاريخ التسليم: ٢٢ سبتمبر ٢٠٢٥."),
    ("para",
     "وثيقة تجريبية اصطناعية. شركة أكمي للخدمات السحابية شركة وهمية وجميع الإجابات مُصطنعة "
     "لأغراض الاختبار."),
    ("table", (
        ["م", "السؤال", "الإجابة"],
        _answered([
            ("ما صفتكم النظامية في معالجة البيانات الشخصية؟",
             "تعمل الشركة بصفة معالج للبيانات الشخصية نيابة عن العميل، ويظل العميل هو المتحكم في "
             "البيانات. ولا تُعالَج البيانات إلا بناءً على تعليمات موثقة من المتحكم."),
            ("هل عيّنتم مسؤولاً لحماية البيانات؟",
             "نعم. عيّنت الشركة مسؤولاً لحماية البيانات مسجلاً لدى الهيئة السعودية للبيانات والذكاء "
             "الاصطناعي، ويمكن التواصل معه عبر البريد dpo@acme-cloud.example."),
            ("أين تُخزَّن البيانات الشخصية للعملاء؟",
             "تُخزَّن البيانات وتُعالَج داخل المملكة العربية السعودية حصراً، في منطقة الرياض الأساسية "
             "مع موقع التعافي من الكوارث في جدة."),
            ("هل تُنقل البيانات خارج المملكة؟",
             "لا تُنقل بيانات العملاء خارج المملكة إلا بتعليمات خطية من المتحكم وبعد إجراء تقييم "
             "للنقل وفق أحكام النظام. ويوجد مورّدان من الباطن يقدّمان أدوات مساندة من خارج المملكة، "
             "وكلاهما مشمول بتقييم نقل، ولا يملك أي منهما صلاحية الوصول إلى محتوى العملاء."),
            ("ما هي مدة الاحتفاظ ببيانات العملاء وكيفية إتلافها؟",
             "يتم الاحتفاظ ببيانات العملاء لمدة سبع سنوات من انتهاء العقد وفقاً للمتطلبات التنظيمية، "
             "ثم تُحذف بشكل آمن وفق إرشادات NIST SP 800-88، وتُصدر شهادة إتلاف عند الطلب. وتنتهي "
             "صلاحية النسخ الاحتياطية المحتوية على البيانات المحذوفة خلال خمسة وثلاثين يوماً."),
            ("كيف تتعاملون مع طلبات أصحاب البيانات؟",
             "تدعم الشركة المتحكمين في تلبية طلبات الاطلاع والتصحيح والإتلاف والاعتراض. وتُحال أي "
             "طلبات ترد إلى الشركة مباشرة إلى المتحكم المعني خلال يومي عمل، مع تقديم الدعم الفني "
             "اللازم للرد خلال المهلة النظامية البالغة ثلاثين يوماً."),
            ("ما هي مدة إبلاغ الجهة التنظيمية عند وقوع اختراق للبيانات الشخصية؟",
             "تُبلَّغ الهيئة السعودية للبيانات والذكاء الاصطناعي خلال اثنتين وسبعين ساعة من العلم "
             "بالاختراق المؤكد، ويُبلَّغ العملاء المتأثرون خلال أربع وعشرين ساعة من تأكيد الحادثة."),
            ("هل وقعت لديكم حوادث اختراق للبيانات الشخصية؟",
             "لم تقع أي حادثة اختراق مؤكدة للبيانات الشخصية تستوجب الإبلاغ خلال عامي ٢٠٢٤ و٢٠٢٥. "
             "وتحتفظ الشركة بسجل للاختراقات وفق متطلبات اللائحة التنفيذية."),
            ("هل تُستخدم بيانات العملاء في تدريب نماذج الذكاء الاصطناعي؟",
             "لا. لا تستخدم الشركة البيانات الشخصية للعملاء في تدريب نماذج التعلم الآلي، ولا تبيعها، "
             "ولا تعالجها لأغراضها التسويقية."),
            ("متى يُشترط إجراء تقييم أثر على حماية البيانات؟",
             "يُشترط إجراء تقييم أثر قبل أي نشاط معالجة جديد يشمل بيانات شخصية حساسة أو تحليلاً "
             "واسع النطاق أو تدفقاً جديداً عبر الحدود، ويراجعه مسؤول حماية البيانات ويُعاد إجراؤه "
             "عند أي تغيير جوهري."),
        ]),
    )),
]


# --- P4: completed bilingual customer due diligence, 2025 (EN+AR, DOCX) ----

PRIOR_BILINGUAL_2025 = [
    ("title", "Cloud Customer Due Diligence 2025 — Completed / استبيان العناية الواجبة"),
    ("para", "Respondent: Acme Cloud Services KSA. Submitted to Tawasul Telecom, 5 August 2025."),
    ("para", NOTE),
    ("table", (
        ["#", "Question", "Response"],
        _answered([
            ("How is tenant data segregated in your multi-tenant platform?",
             "Customer environments are logically segregated by tenant with separate encryption keys "
             "per tenant, and isolation enforced at the network, compute and storage layers. "
             "Multi-tenancy isolation is explicitly tested during the annual external penetration test."),
            ("هل تلتزمون بالضوابط الأساسية للأمن السيبراني الصادرة عن الهيئة الوطنية للأمن السيبراني؟",
             "نعم. بلغت نسبة الالتزام ٩٢٪ في دورة تقييم الربع الرابع من عام ٢٠٢٥، كما تم تقييم "
             "الشركة كملتزمة بضوابط الأمن السيبراني للحوسبة السحابية CCC-1:2020 ضمن فئة مقدم "
             "الخدمة السحابية في سبتمبر ٢٠٢٥."),
            ("What availability do you commit to contractually?",
             "99.95 percent monthly for the Enterprise platform and 99.9 percent monthly for the "
             "Standard platform, with service credits defined in the service level agreement."),
            ("هل يحق للعميل تدقيق ضوابطكم الأمنية؟",
             "نعم. يحق لعملاء فئة Enterprise إجراء تدقيق مرة واحدة سنوياً بإشعار مدته ثلاثون يوماً، "
             "أو بوتيرة أعلى عقب أي حادثة جوهرية. كما تتوفر تقارير SOC 2 Type II وشهادات آيزو "
             "وملخصات اختبار الاختراق بموجب اتفاقية عدم إفصاح."),
            ("Do you carry cyber liability insurance?",
             "Yes, with a limit of 10 million United States dollars per claim, covering incident "
             "response costs, regulatory defence and third-party liability. The certificate is "
             "available on request."),
            ("How quickly do you respond to customer security questionnaires?",
             "Within 15 business days of receipt. Standard evidence packs are available immediately "
             "from the Trust Portal under NDA."),
            ("ما هي إجراءاتكم عند إنهاء العقد فيما يخص البيانات؟",
             "عند انتهاء العقد تُتاح للعميل فترة لاسترجاع بياناته، ثم يبدأ سريان مدة الاحتفاظ "
             "النظامية البالغة سبع سنوات، وبعدها تُحذف البيانات بشكل آمن وتُصدر شهادة إتلاف عند الطلب."),
            ("Are administrative sessions recorded?",
             "Yes. All privileged sessions are brokered through a privileged access management vault, "
             "recorded in full, and the recordings are retained for 12 months. Standing administrative "
             "privilege is not permitted; credentials are issued just in time for a maximum of four "
             "hours against an approved ticket."),
            ("هل لديكم خطة لاستمرارية الأعمال ومتى تم اختبارها؟",
             "نعم. يبلغ هدف زمن الاستعادة أربع ساعات وهدف نقطة الاستعادة خمس عشرة دقيقة لمنصة "
             "Enterprise. وقد نُفِّذ تمرين تحوّل كامل إلى موقع جدة في أكتوبر ٢٠٢٥ واكتمل خلال ساعتين "
             "وعشر دقائق. البرنامج متوافق مع معيار آيزو ٢٢٣٠١ إلا أن الشركة غير حاصلة على شهادته."),
            ("Which sub-processors have access to customer content?",
             "None. Acme uses nine sub-processors as of February 2026; seven operate wholly within the "
             "Kingdom and two provide tooling from outside it under completed transfer assessments. "
             "Neither of the two has access to customer content."),
        ]),
    )),
]


def _blank3(questions: list[str]) -> list[list[str]]:
    return [[str(i), question, ""] for i, question in enumerate(questions, 1)]


# --- N1: new vendor security assessment 2026 (EN, DOCX) --------------------

NEW_VENDOR_2026 = [
    ("title", "Vendor Security Assessment 2026"),
    ("para", "Issued by Meridian Bank — Third-Party Risk Management. Return within 15 business days."),
    ("para", "Complete every row. Where a control is not implemented, say so and state the plan."),
    ("table", (
        ["#", "Question", "Domain", "Answer"],
        _blank([
            ("Is your organisation certified against a recognised information security standard? "
             "State the certificate number and validity period.", "Governance"),
            ("Do you undergo an independent SOC 2 Type II audit, and when was the most recent report issued?",
             "Governance"),
            ("Describe how customer data is encrypted at rest and in transit, including key management.",
             "Cryptography"),
            ("Do you support customer-managed encryption keys (BYOK)?", "Cryptography"),
            ("Is multi-factor authentication required for administrative access, and what factors are accepted?",
             "Access control"),
            ("How is standing privileged access controlled, and are privileged sessions recorded?",
             "Access control"),
            ("How frequently are user access rights reviewed, and what happens to entitlements that are not recertified?",
             "Access control"),
            ("Where is customer data stored, and under what circumstances does it leave the Kingdom?",
             "Data residency"),
            ("How long is customer data retained after contract termination, and how is it destroyed?",
             "Data lifecycle"),
            ("What is your regulatory breach notification commitment, and to which authority?",
             "Incident response"),
            ("State your recovery time objective and recovery point objective, and when the failover was last exercised.",
             "Resilience"),
            ("Are you certified against ISO 22301 for business continuity management?", "Resilience"),
            ("What are your vulnerability remediation service levels by severity?", "Vulnerability management"),
            ("Describe your post-quantum cryptography migration roadmap and target dates.", "Cryptography"),
            ("Do you hold FedRAMP authorisation?", "Governance"),
        ]),
    )),
]


# --- N2: new PDPL compliance questionnaire 2026 (AR, DOCX) -----------------

NEW_PDPL_2026_AR = [
    ("title", "استبيان الالتزام بنظام حماية البيانات الشخصية — ٢٠٢٦"),
    ("para", "صادر عن إدارة الالتزام. يُرجى الإجابة على جميع الأسئلة وعدم ترك أي حقل فارغاً."),
    ("table", (
        ["م", "السؤال", "الإجابة"],
        _blank3([
            "ما صفتكم النظامية في معالجة البيانات الشخصية، ومن هو المتحكم؟",
            "هل عيّنتم مسؤولاً لحماية البيانات ومسجلاً لدى الهيئة السعودية للبيانات والذكاء الاصطناعي؟",
            "أين تُخزَّن البيانات الشخصية للعملاء وهل تغادر المملكة العربية السعودية؟",
            "ما هي مدة الاحتفاظ ببيانات العملاء وما آلية الإتلاف الآمن المتبعة؟",
            "ما هي المدة النظامية لإبلاغ الهيئة عند وقوع اختراق مؤكد للبيانات الشخصية؟",
            "كيف تدعمون المتحكم في تلبية طلبات أصحاب البيانات خلال المهلة النظامية؟",
            "هل تُستخدم بيانات العملاء الشخصية في تدريب نماذج الذكاء الاصطناعي؟",
            "متى يُشترط إجراء تقييم أثر على حماية البيانات لديكم؟",
            "ما هي سياستكم المعتمدة لحوكمة استخدام الذكاء الاصطناعي التوليدي داخل المنشأة؟",
            "كم عدد المورّدين من الباطن لديكم، وكم منهم يملك صلاحية الوصول إلى محتوى العملاء؟",
        ]),
    )),
]


# --- N3: new bank third-party risk review 2026 (EN + AR, PDF) --------------

NEW_BANK_TPRM_2026 = [
    ("title", "Third-Party Cyber Risk Review 2026 / مراجعة مخاطر الأطراف الثالثة"),
    ("para",
     "Issued under the SAMA Cyber Security Framework. Answer in the language of the question. "
     "يُرجى الإجابة بلغة السؤال."),
    ("table", (
        ["#", "Question / السؤال", "Answer / الإجابة"],
        _blank3([
            "What is your assessed compliance level against the NCA Essential Cybersecurity Controls?",
            "ما هي ضوابط عزل البيانات بين المستأجرين في منصتكم متعددة المستأجرين؟",
            "Describe your security event logging and how long logs are retained.",
            "ما هو زمن الكشف المتوسط وزمن الاستجابة المتوسط للحوادث الحرجة لديكم؟",
            "How often is your incident response plan tested, and what was the outcome of the last exercise?",
            "هل يحق للعميل تدقيق ضوابطكم الأمنية، وما هي شروط ذلك؟",
            "Do you carry cyber liability insurance, and what is the limit per claim?",
            "كيف تُدار مخاطر المورّدين من الباطن وما هي مدة الإشعار قبل إضافة مورّد جديد؟",
            "What penetration testing do you perform, and by whom?",
            "هل تُجرون اختبار اختراق مادي لمراكز البيانات؟",
            "Describe your network segmentation and the status of any zero-trust programme.",
            "ما هي التزاماتكم التعاقدية بشأن توافر الخدمة؟",
        ]),
    )),
]


# --- N4: new cloud security questionnaire 2026 (EN, PDF) -------------------

NEW_CLOUD_2026 = [
    ("title", "Cloud Service Provider Security Questionnaire 2026"),
    ("para", "Issued by Tawasul Telecom — Procurement Security Review. All rows are mandatory."),
    ("table", (
        ["#", "Question", "Domain", "Answer"],
        _blank([
            ("Are you assessed against the NCA Cloud Cybersecurity Controls (CCC-1:2020), and in which tier?",
             "Cloud compliance"),
            ("How are customer environments isolated from one another?", "Tenant isolation"),
            ("Is infrastructure deployed as code through a reviewed pipeline, and are manual production changes prevented?",
             "Change management"),
            ("What is your current cloud security posture score against CIS benchmarks?", "Configuration"),
            ("Describe your backup schedule, retention and immutability guarantees.", "Resilience"),
            ("When were your backups last restore-tested, and what was the result?", "Resilience"),
            ("How many security incidents did you record last year, and how many were reportable breaches?",
             "Incident response"),
            ("What screening do staff with production access undergo, and how often is it repeated?",
             "Personnel security"),
            ("Describe physical security at your data centres, including CCTV retention.", "Physical security"),
            ("Do Acme personnel have unescorted physical access to customer hardware?", "Physical security"),
            ("What is your policy on using customer data to train machine learning models?", "Data usage"),
            ("How quickly are critical operating system patches deployed to production?", "Vulnerability management"),
        ]),
    )),
]
