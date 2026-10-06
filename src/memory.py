"""The answer memory: what this organisation has actually said, and which of it still stands.

Measured on 135 held-out questions against 698 remembered answers, having this
at all is worth about seventeen points of agreement with the security team --
the largest single effect anywhere in this system. It earns that by being what
the team really wrote to a real assessor, so the value is entirely in it staying
true, which is what this module is for.

Two relationships between remembered answers matter, and they are not the same:

**Supersession.** A later answer replaces an earlier one about the same
question. Either it says something different, or it says more -- an audit that
has since happened, a certification since issued, a control since implemented.
The earlier answer was not wrong; it was true then. So it is kept and marked,
never deleted: an assessor's question about what we said last year has an answer,
and a memory that quietly rewrites its own history cannot be audited.

**Contradiction.** Two answers about the same question that disagree on the
verdict, where neither is obviously later. This is not a versioning problem, it
is two people believing different things, and no rule here can decide which is
right. It is raised for a person.

Both are found at ingest rather than at answer time. By the time a questionnaire
is being answered it is too late to be useful -- whichever entry retrieval
happened to rank first has already gone into a customer's file -- and the person
who could resolve it is not the person filling in the form.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SAME_QUESTION = 0.88
"""How close two questions must embed to be treated as the same question.

Measured rather than chosen. Pairing each of 135 held-out questions with its
nearest remembered one and asking whether the remembered answer answered it:
91% above 0.90, 88% between 0.85 and 0.90, 54% between 0.80 and 0.85, and 21%
below 0.75. The usable band ends around 0.85, and this sits just inside it
because the cost of the two errors is not symmetric -- wrongly treating two
questions as one supersedes an answer that should have stood, while missing a
pair only leaves a duplicate for somebody to notice later.

Similarity alone cannot do the whole job. "Do you conduct business-continuity
drills annually" and "do you perform the incident-response drill at least
annually" embed at 0.793 and are different controls; "have you signed a DPA with
sub-processors" and "do you have DPAs with all your sub-processors" embed at
0.808 and are one question. Nothing in the number separates those, which is why
a pair this finds is confirmed by a model before anything is marked.
"""

PROPOSE = 0.80
"""How close two questions must embed before a model is asked about them.

Lower than `SAME_QUESTION` on purpose. Nothing is marked on similarity alone,
so the number's only job here is to decide which pairs are worth one model
call, and the two errors are again asymmetric: a pair proposed and rejected
costs a few hundred tokens, a pair never proposed is a contradiction nobody
ever sees. Sweeping the 698 imported answers, 0.88 proposes 2 pairs and 0.80
proposes 19 -- and the wider band is where the real cross-customer conflicts
were, mixed in with shared question stems the model then rejects.
"""

_VERDICT = re.compile(
    r"^\s*[\"'(]?\s*(yes|no|not applicable|n/?a|fully compliant|partially compliant|"
    r"non[- ]compliant|compliant|implemented|not implemented|نعم|لا)\b",
    re.I,
)

_AFFIRMATIVE = {"yes", "fully compliant", "compliant", "implemented", "applicable", "نعم"}
_NEGATIVE = {"no", "non-compliant", "non compliant", "not implemented", "not applicable", "n/a", "لا"}


def verdict_of(answer: str) -> str:
    """The yes/no an answer opens with, or "" when it does not open with one.

    Only the opening word counts. An answer that says "Yes, ... although X is
    not yet in place" is a yes with a caveat, and reading the whole text for
    negations would make it a no.
    """
    match = _VERDICT.match(answer or "")
    if not match:
        return ""
    word = match.group(1).casefold()
    if word in _AFFIRMATIVE:
        return "yes"
    if word in _NEGATIVE or word.startswith("not ") or word.startswith("non"):
        return "no"
    return ""


def disagree(earlier: str, later: str) -> bool:
    """Whether two answers assert opposite verdicts.

    Deliberately narrow. Two answers that both say yes and differ in detail are
    an update, not a disagreement, and treating them as one would put a person
    in front of every ordinary revision.
    """
    a, b = verdict_of(earlier), verdict_of(later)
    return bool(a and b and a != b)


@dataclass
class Entry:
    """One remembered answer, and whether it still stands."""

    entry_id: str
    question: str
    answer: str

    approved_by: str = ""
    """Who put their name to it. Empty only for the historical import."""

    approved_on: str = ""
    """When they did, ISO-8601. Empty only for the historical import.

    The ordering key for supersession, and deliberately *approval* time rather
    than upload time: an answer becomes ours when somebody accepts it, not when
    a file lands on a disk. The 698 imported answers carry neither field,
    because the questionnaires they came from record neither -- so they all sort
    equal, and the first properly dated answer supersedes any of them it
    matches. That is the right outcome and worth saying out loud.
    """

    from_file: str = ""
    section: str = ""

    origin: str = "import"
    """Where it came from: `import`, `approved` on a card, or `manual`.

    Kept because the three are trusted differently by the people reading them.
    An imported answer is what somebody sent an assessor at some point; an
    approved one is what a named reviewer accepted here, this week.
    """

    superseded_by: str = ""
    """The entry that replaced this one. Empty while it stands."""

    conflicts_with: list[str] = field(default_factory=list)
    """Entries this disagrees with, unresolved. Raised for a person."""

    team_id: str = ""
    """The team whose memory this is. Entries are only ever compared within one."""

    product_id: str = ""
    """The product whose memory this is; empty for the team's shared memory (plan 022)."""

    @property
    def stands(self) -> bool:
        return not self.superseded_by

    def is_later_than(self, other: Entry) -> bool:
        """Whether this was approved after `other`.

        An entry with no date is never later than one with a date: the import
        has no dates, so it must not displace an answer somebody has actually
        approved. Two undated entries are not ordered at all.
        """
        if not self.approved_on:
            return False
        if not other.approved_on:
            return True
        return self.approved_on > other.approved_on


@dataclass
class Finding:
    """What arrived when a new answer met one already remembered."""

    kind: str
    """`supersedes`, `superseded_by`, or `conflict`."""

    other_id: str
    other_question: str
    other_answer: str
    because: str

    @property
    def needs_a_person(self) -> bool:
        return self.kind == "conflict"


def compare(new: Entry, existing: Entry, *, same_question: bool) -> Finding | None:
    """What the arrival of `new` means for `existing`. None when nothing.

    `same_question` comes from outside: an embedding proposes the pair and a
    model confirms it, because the number alone cannot separate a rephrasing
    from a neighbouring control.
    """
    if not same_question or new.entry_id == existing.entry_id:
        return None

    if new.answer.strip().casefold() == existing.answer.strip().casefold():
        return None  # the same answer twice is not news

    if disagree(existing.answer, new.answer):
        # A disagreement between two dated answers is still a supersession --
        # somebody changed our position, which is allowed and is exactly what
        # dates are for. It is a conflict only when nothing says which came
        # later, because then there is no answer to "which is true now".
        if new.is_later_than(existing):
            return Finding(
                kind="supersedes",
                other_id=existing.entry_id,
                other_question=existing.question,
                other_answer=existing.answer,
                because="our position on this changed",
            )
        if existing.is_later_than(new):
            return Finding(
                kind="superseded_by",
                other_id=existing.entry_id,
                other_question=existing.question,
                other_answer=existing.answer,
                because="a later answer already says the opposite",
            )
        return Finding(
            kind="conflict",
            other_id=existing.entry_id,
            other_question=existing.question,
            other_answer=existing.answer,
            because="the two answers disagree and nothing says which is current",
        )

    # Same verdict, different words: an update. The later one is the current
    # position -- it is the one that says more, or says it as things now stand.
    if new.is_later_than(existing):
        return Finding(
            kind="supersedes",
            other_id=existing.entry_id,
            other_question=existing.question,
            other_answer=existing.answer,
            because="a newer answer to the same question",
        )
    if existing.is_later_than(new):
        return Finding(
            kind="superseded_by",
            other_id=existing.entry_id,
            other_question=existing.question,
            other_answer=existing.answer,
            because="a later answer to the same question already stands",
        )
    return None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
