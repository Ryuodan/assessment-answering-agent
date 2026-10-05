"""Reading an answer's position, for the dropdown beside it.

The drafter states its position first -- "Yes.", "No.", "Partially." -- and the
preference for a verdict first asks for exactly that. The rest of the answer is
prose about controls, and prose about controls is full of "no longer required",
"are not left in use", "none of", "will be reviewed". Searched for those before
the opening word was looked at, 19 of 1,088 drafted answers that began "Yes"
were read as No -- so the dropdown beside an answer saying yes would have said
Non Compliant -- and 16 that began "No" were read as saying nothing.
"""

from __future__ import annotations

import pytest

from src.forms.status import Stance, choose, stance_of

COMPLIANCE = ["Fully Compliant", "Partially Compliant", "Non Compliant", "Not Applicable"]


@pytest.mark.parametrize(
    "answer",
    [
        # Drafted answers from the deployment's own runs.
        "Yes. Access privileges that are no longer required for a user's role are revoked, "
        "as required by the Identity and Access Management Policy (5.1).",
        "Yes. Our policies require that default credentials are not left in use – default "
        "supplier credentials must be changed, disabled or removed.",
        "Yes. Our organization removes client data from production systems whenever the data is no longer required.",
        "**Yes.** T2 Business Research implements a comprehensive data-security programme.",
        # And from the team's own answers.
        "Yes, T2 applies processes to manage, monitor, log, review, and revoke developer and "
        "privileged access when no longer required",
        "Yes, the Cybersecurity Strategy is approved, reviewed, and implemented according to the roadmap.",
        "Yes, none of the personal data leaves the Kingdom.",
        "Yes. Access rights will be revoked immediately on termination.",
        "نعم، لا يتم منح الوصول إلا بعد الموافقة.",
    ],
)
def test_an_answer_that_opens_with_yes_is_a_yes(answer):
    assert stance_of(answer) is Stance.YES
    assert choose(answer, COMPLIANCE).value == "Fully Compliant"


@pytest.mark.parametrize(
    "answer",
    [
        "No; the standard contractual clauses do not grant a right of access.",
        "NO",
        "No",
        "No. T2 does not use sub-processors outside the Kingdom.",
        "لا، لا تتم مشاركة البيانات مع أطراف ثالثة.",
    ],
)
def test_an_answer_that_opens_with_no_is_a_no(answer):
    assert stance_of(answer) is Stance.NO
    assert choose(answer, COMPLIANCE).value == "Non Compliant"


@pytest.mark.parametrize(
    "answer, stance",
    [
        ("Partially. Encryption at rest is in place for production systems only.", Stance.PARTIAL),
        ("Yes, partially: only production systems are covered.", Stance.PARTIAL),
        ("Not applicable. T2 does not process card data.", Stance.NOT_APPLICABLE),
        ("N/A – no card data is processed.", Stance.NOT_APPLICABLE),
        ("لا ينطبق، لا تعالج الشركة بيانات البطاقات.", Stance.NOT_APPLICABLE),
    ],
)
def test_other_opening_positions(answer, stance):
    assert stance_of(answer) is stance


@pytest.mark.parametrize(
    "answer, stance",
    [
        # No opening word: the phrases still decide, as they always did.
        ("We do not share personal data with third parties.", Stance.NO),
        ("We maintain an approved information security policy.", Stance.YES),
        ("Encryption at rest is currently implementing across all systems.", Stance.PARTIAL),
        ("T2 provides regular cybersecurity awareness training.", Stance.UNCLEAR),
    ],
)
def test_without_an_opening_word_the_prose_is_read_as_before(answer, stance):
    assert stance_of(answer) is stance


def test_a_word_that_merely_starts_with_no_is_not_a_no():
    assert stance_of("Nothing in our policies prevents this; we maintain an approved process.") is Stance.YES
    assert stance_of("Notably, we do not retain logs beyond one year.") is Stance.NO
