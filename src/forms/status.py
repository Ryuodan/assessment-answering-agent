"""Turning a written answer into the word a form's dropdown will accept.

The pipeline writes prose. Most of these questionnaires also want a status
picked from a list the file itself defines, and no two files agree on the list:

    Fully Compliant · Partially Compliant · Non Compliant · Not Applicable
    Fully Implemented · Partially Implemented · Not Implemented · Not Applicable
    Yes · No · Not Applicable
    FC · PC · NC · NA
    Applicable · Not Applicable

So the mapping runs in two steps. First read the **stance** of the answer --
does it say yes, no, partly, or not applicable -- and then find the option in
*this* file's vocabulary that means that. Neither half needs a model: the
drafter has already committed to a position in the first clause of its answer,
and the vocabularies are small and formulaic.

Where the stance is unclear, or the vocabulary has nothing for it, nothing is
written and the reason is recorded. A blank dropdown is a question somebody
looks at; a confidently wrong one is a question nobody looks at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Stance(str, Enum):
    """What an answer commits to, before it is mapped to any file's wording."""

    YES = "yes"
    NO = "no"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"
    UNCLEAR = "unclear"


# Read against the opening of the answer, where the drafter states its position.
# Order matters within each tuple only for reporting; order *between* the checks
# in `stance_of` is what resolves overlaps.
_NOT_APPLICABLE = (
    "not applicable", "n/a", "not relevant", "does not apply", "out of scope",
    "لا ينطبق", "غير منطبق",
)
_PARTIAL = (
    "partially", "in part", "partly", "in progress", "planned", "roadmap",
    "will be", "is being", "currently implementing", "under implementation",
    "جزئي", "قيد التنفيذ", "مخطط",
)
_NEGATIVE = (
    "no,", "no.", "no ", "not implemented", "we do not", "we don't", "do not have",
    "does not have", "is not", "are not", "none", "never",
    "لا،", "لا ", "لا يوجد", "غير",
)
_AFFIRMATIVE = ("yes", "we have", "we do", "we maintain", "we enforce", "نعم", "لدينا", "يتم")

_LEAD = 160
"""Characters of the answer to read. The position is stated up front or not at all."""


def stance_of(answer: str) -> Stance:
    """What the answer commits to.

    Negation is tested before affirmation, because 'No, we do not...' contains
    'we do' and would otherwise read as a yes. 'Not applicable' is tested first
    of all, because it contains 'not' and would otherwise read as a no.
    """
    text = " ".join(answer.split()).lower()[:_LEAD]
    if not text:
        return Stance.UNCLEAR
    if any(phrase in text for phrase in _NOT_APPLICABLE):
        return Stance.NOT_APPLICABLE
    if any(phrase in text for phrase in _PARTIAL):
        return Stance.PARTIAL
    if any(text.startswith(phrase) or f" {phrase}" in text for phrase in _NEGATIVE):
        return Stance.NO
    if any(text.startswith(phrase) or f" {phrase}" in text for phrase in _AFFIRMATIVE):
        return Stance.YES
    return Stance.UNCLEAR


# What each stance looks like in a form's own words. Every entry is matched
# against a *normalised* option -- lower case, punctuation stripped -- and the
# longest match wins, so 'not implemented' beats 'implemented' rather than
# racing it.
_WORDS: dict[Stance, tuple[str, ...]] = {
    Stance.NOT_APPLICABLE: ("not applicable", "n a", "na", "not relevant", "لا ينطبق"),
    Stance.NO: ("non compliant", "not implemented", "not compliant", "no", "nc", "non compliance"),
    Stance.PARTIAL: ("partially compliant", "partially implemented", "partial compliance",
                     "partially", "partial", "pc"),
    Stance.YES: ("fully compliant", "fully implemented", "full compliance", "compliant",
                 "implemented", "yes", "fc", "applicable", "نعم"),
}


def _normalise(option: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9؀-ۿ ]+", " ", option.lower()).split())


def _says(text: str, word: str) -> bool:
    return bool(re.search(rf"(^|\s){re.escape(word)}($|\s)", text))


def stance_of_option(option: str) -> Stance | None:
    """What one of a form's own words means, or None if it means none of them.

    The longest phrase across *all* stances wins, which is what keeps the
    overlaps straight: 'Not Applicable' contains 'applicable', 'Not Implemented'
    contains 'implemented', and 'Non Compliant' contains 'compliant'. Racing
    them stance by stance mapped every yes to 'Not Applicable' in the one
    workbook whose options are Yes / No / Not Applicable.

    'Not Answered' matches nothing and is never chosen, which is right -- it is
    a form's way of recording that nobody replied.
    """
    text = _normalise(option)
    best: Stance | None = None
    longest = 0
    for stance, words in _WORDS.items():
        for word in words:
            if len(word) > longest and _says(text, word):
                best, longest = stance, len(word)
    return best


@dataclass(frozen=True)
class Choice:
    """The option chosen for one status target, or the reason there is none."""

    value: str = ""
    stance: Stance = Stance.UNCLEAR
    because: str = ""

    @property
    def chosen(self) -> bool:
        return bool(self.value)


def choose(answer: str, vocabulary: list[str]) -> Choice:
    """Pick the option in `vocabulary` that matches what `answer` says.

    Returns an empty choice rather than a guess when the answer takes no clear
    position, or when the file offers no word for the position it takes. Both
    happen: one workbook's only options are 'Applicable' and 'Not Applicable',
    which have nothing to say about whether a control is in place.
    """
    if not vocabulary:
        return Choice(because="the column offers no list to choose from")

    stance = stance_of(answer)
    if stance is Stance.UNCLEAR:
        return Choice(stance=stance, because="the answer takes no clear yes/no position")

    for option in vocabulary:
        if stance_of_option(option) is stance:
            return Choice(value=option, stance=stance, because=f"the answer says {stance.value}")

    return Choice(
        stance=stance,
        because=f"the answer says {stance.value}, and this column offers no option for that",
    )
