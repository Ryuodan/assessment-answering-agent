"""Mark each indexed document as ours or as a requirement we are subject to.

    python -m scripts.classify_corpus            # show what it would do
    python -m scripts.classify_corpus --apply    # write it

Everything indexed before the distinction existed is marked "ours", which is
what the drafter was already assuming and is wrong for about forty percent of
this corpus: the PDPL and its implementing regulation, the NCA's ECC guide, and
SDAIA's data and AI material are law we are subject to, not policy we wrote.

The classification is by document, listed explicitly rather than inferred. A
file name is not evidence -- "DataClassificationPolicy.pdf" in this corpus is
SDAIA's and reads exactly like one of ours -- and a rule that guesses wrong puts
a regulation back in the drafter's mouth as our own control, which is the whole
thing this exists to stop. A name that matches nothing here stays "ours" and is
listed for somebody to check.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import configure_logging
from src.knowledge import get_store

# Saudi national law, regulator guidance, and other people's frameworks. These
# say what we are required to do; they are not evidence that we do it.
EXTERNAL = {
    "AIAdoptionFramework.pdf",
    "CertificatesControllersProcessorsAuditingInspectionPersonalDataProcessingActivities.pdf",
    "CommitteeWorkingRules.pdf",
    "CommonRulesBCRForPersonalDataTransferEN.pdf",
    "DataClassificationPolicy.pdf",
    "DataManagementPersonalDataProtectionStandards (1).pdf",
    "DataManagementPersonalDataProtectionStandards (2).pdf",
    "DataManagementPersonalDataProtectionStandards (3).pdf",
    "DataManagementPersonalDataProtectionStandards (4).pdf",
    "DataManagementPersonalDataProtectionStandards.pdf",
    "DataMonetizationPolicy.pdf",
    "DataSharingPolicyEN.pdf",
    "FreedomOfInformationPolicy.pdf",
    "GenAIGuidelinesForGovernmentENCompressed.pdf",
    "GeneralRulesForSecondaryUseOfData_EN.pdf",
    "GenerativeAIPublicEN.pdf",
    "Guide-to-Essential-Cybersecurity-Controls-(ECC)-Implementation-en.pdf",
    "ImplementingRegulationPersonalDataProtectionLaw.pdf",
    "MinmumPDGuideline.pdf",
    "OpenDataPolicy.pdf",
    "PersonalDataBreachIncidents.pdf",
    "PersonalDataDestructionAnonymizationAndEncryptionGuideline.pdf",
    "PersonalDataDisclosureCasesGuideline.pdf",
    "PersonalDataProcessingActivitiesRecordsGuideline.pdf",
    "PersonalDataProtectionLaw.pdf",
    "PrivacyPolicyGuideline.pdf",
    "RegulationonPersonalDataEN.pdf",
    "RisksTransferringDataOutsideKingdomEn.pdf",
    "RulesGoverningIssuanceAccreditationCertificatesControllersProcessers.pdf",
    "RulesforAppointingPersonalDataProtectionOfficer.pdf",
    "StandardContractualClausesForPersonalDataTransferEN.pdf",
    "TheRulesGoverningTheNationalRegisterOfControllersWithinTheKingdomPublicEN.pdf",
    "ai-principles.pdf",
    # Scanned SDAIA uploads, confirmed by the team.
    "File0001.pdf",
    "File0002.pdf",
    "File0003.pdf",
}

# Nothing is left unclassified. The three scanned uploads this list used to
# hold -- File0001-0003.pdf -- were confirmed as SDAIA material and moved into
# EXTERNAL above.
UNSURE: set[str] = set()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the change")
    args = parser.parse_args()
    configure_logging()

    store = get_store()
    indexed = set(store.documents_indexed())

    external = sorted(EXTERNAL & indexed)
    ours = sorted(indexed - EXTERNAL)
    missing = sorted(EXTERNAL - indexed)

    print(f"{len(indexed)} documents indexed")
    print(f"  {len(ours):3d} ours       (what we wrote and are bound by)")
    print(f"  {len(external):3d} external   (law, regulation, other frameworks)")
    if missing:
        print(f"\n  {len(missing)} listed as external but not indexed:")
        for name in missing:
            print(f"      {name[:72]}")
    unsure = sorted(UNSURE & indexed)
    if unsure:
        print(f"\n  {len(unsure)} left as ours because nobody has said otherwise:")
        for name in unsure:
            print(f"      {name}")

    if not args.apply:
        print("\nNothing written. Pass --apply.")
        return 0

    changed = store.set_authority(external, "external")
    print(f"\nMarked {changed} chunk(s) across {len(external)} document(s) as external.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
