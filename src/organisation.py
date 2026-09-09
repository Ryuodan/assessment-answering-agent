"""Who this system is answering on behalf of.

The drafting prompt used to open "You fill in assessment questionnaires on
behalf of an organisation" and never say which one. That is a bigger hole than
it reads as, and it showed up as wrong answers rather than as bland ones.

Assessment questionnaires address the responder in the third person -- "Does the
Third-party have documented security policies?", "Does the vendor conduct
background checks?" -- because they are written by the company doing the
assessing. Without being told who it is, the drafter reads "the Third-party" as
somebody *else's* supplier, goes looking in our own Third-Party Cybersecurity
Policy (which describes what we require *of* vendors), finds nothing about a
third party's own controls, and answers "No -- the documentation does not state
that the third-party has..." Measured against the security team's own answers,
five of ten contradictions were exactly this, every one of them turning a Yes
into a No about our own security posture.

So the profile is short and the identity statement is the important half. It is
kept in a file rather than in the prompt so that it can be corrected without a
deploy, and it is deliberately small: everything here is asserted to the drafter
as true, so it holds what somebody is willing to stand behind and nothing else.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

PROFILE_PATH = PROJECT_ROOT / "data" / "organisation.json"


@dataclass
class Organisation:
    """The facts about ourselves that every answer may rely on."""

    legal_name: str = "Business Research and Development"
    short_name: str = "T2"
    sector: str = "technology solutions"
    country: str = "Saudi Arabia"
    locations: str = "Riyadh, Saudi Arabia"

    certifications: list[str] = field(default_factory=list)
    """Certifications actually held. Empty means *unknown*, never *none*.

    That distinction was learned the expensive way. This field was first
    written on the reading that an empty list meant the organisation held
    nothing, and the drafter was told to say so plainly -- which produced
    "No. T2 does not hold any information-security certifications" at 0.85
    confidence, on its way into a customer's file, while the security team's
    own answers in fourteen real questionnaires said ISO 27001 and SOC 2.

    Denying a certification understates the organisation to an assessor and is
    very hard to walk back. Not knowing is a normal state for a profile nobody
    has filled in yet, and the honest response to a question you cannot answer
    is not the opposite answer.
    """

    notes: str = ""
    """Anything else worth asserting. Free text, added to the prompt verbatim."""

    def describe(self) -> str:
        """The block the drafter is given. Plain sentences, no headings."""
        lines = [
            f"You are answering on behalf of {self.legal_name} ("
            f"\"{self.short_name}\"), a {self.sector} company based in {self.locations}.",
            f"Write as {self.short_name} -- \"we\", \"our\", or \"{self.short_name}\". "
            "Never write \"the organisation\" as though describing somebody else.",
        ]
        if self.certifications:
            lines.append(
                f"{self.short_name} holds: {', '.join(self.certifications)}. "
                "Claim no certification that is not on that list, and do not describe "
                "a policy as though it were one."
            )
        else:
            # Stated as a fact, not as a posture. The instructional version of
            # this -- "do not claim, do not deny, say it is not documented, set
            # confidence low" -- was a paragraph about how to avoid answering,
            # sitting at the top of the prompt, and it generalised: hedging went
            # from 10% to 27% and verdicts fell 13 points across questions that
            # had nothing to do with certifications. One sentence of fact leaves
            # the grounding rules below to do the work they already do, and they
            # already forbid asserting what the sources do not support -- which
            # a denial is.
            lines.append(
                "Which certifications this organisation holds is not in your sources, "
                "so neither holding one nor lacking one is something you can state."
            )
        if self.notes.strip():
            lines.append(self.notes.strip())
        return "\n".join(lines)


ADDRESSED_AS = """A questionnaire addresses you in the third person, because the company sending it wrote it about their supplier. "Does the Third-party...", "Does the vendor...", "Has the supplier...", "Your organisation" -- every one of these means US, the organisation you are answering for. They are never a question about somebody else's supplier, and never a question about what we require of our own vendors.

This matters more than it sounds. Asked "Does the Third-party have documented information security policies?", the wrong reading sends you to our Third-Party Cybersecurity Policy -- which says what we demand *of* the vendors we buy from -- where you will find nothing about a third party's own controls and conclude the answer is no. It is our policies that answer the question, and the answer is about us."""
"""Who "the vendor" is. The single highest-value sentence in the drafting prompt.

Not configuration: it is true of every organisation this system could serve, and
it is the thing that turned Yes into No on five of ten measured contradictions.
"""


def load(path: Path | str = PROFILE_PATH) -> Organisation:
    """The profile on disk, or the defaults when there is none.

    A missing or unreadable file is not an error worth failing a run over -- the
    defaults describe the organisation this system was built for, and a broken
    profile should degrade to them rather than stop anybody answering.
    """
    path = Path(path)
    if not path.exists():
        return Organisation()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Organisation(**{
            key: value for key, value in data.items()
            if key in Organisation.__dataclass_fields__
        })
    except Exception:  # noqa: BLE001 - a bad profile falls back, it does not stop a run
        logger.exception("Could not read %s; using the built-in profile", path)
        return Organisation()


def save(profile: Organisation, path: Path | str = PROFILE_PATH) -> None:
    """Write the profile, so it can be corrected without a deploy."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "legal_name": profile.legal_name, "short_name": profile.short_name,
                "sector": profile.sector, "country": profile.country,
                "locations": profile.locations,
                "certifications": profile.certifications, "notes": profile.notes,
            },
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
