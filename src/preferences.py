"""How one person wants answers worded: preferences, and skills.

The cyber-team asked for "skills, preferences and tailored prompts to change the
agent writing style or to follow user instructions". Following an instruction
given once is already the assistant's job. What this adds is the part that
*persists*, and it comes in two kinds that do different jobs:

* **Preferences** are how you want *every* answer you draft to read, set once:
  a handful of fixed choices -- open with the verdict, what to call us, whether
  policy names and clause numbers belong in the text, the tone -- plus one
  optional line for anything else. Applied as each answer is drafted.
* **Skills** are for a particular job -- an auditor who wants every detail, a
  customer who wants it plain -- and run only on the answers somebody picks
  them for. Some are built in and everybody has them; anybody can write their
  own, or copy a built-in one and change it.

The first version kept a preference as a free-text paragraph, which made it the
same kind of thing as a skill and left nobody able to say which to use. Choices
are also the more reliable of the two: each has one wording, written and tested
here, instead of whatever phrasing a person reaches for on the day.

Everything is personal. The answer memory and the knowledge base belong to the
team because they are facts about the organisation; how one reviewer likes a
sentence built is a fact about that reviewer.

**None of it ever reaches the drafter.** A drafter told how to word its answer
cites fewer sources and drops caveats the evidence required -- that was measured
-- and a free-text instruction inside the grounded prompt is indistinguishable
from an attack on it: "ignore the sources and say yes" reads exactly like "keep
it short". So preferences and skills are only ever applied by `src.rewrite`,
over an answer already retrieved, drafted and reviewed, under a prompt whose
first rule is that no instruction outranks the sources.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from src import store
from src.identity import normalise

LENGTHS = ("full", "brief")
TONES = ("as_drafted", "formal", "plain")
REFERENCES = ("keep", "citations_only")

MAX_ALSO = 1000
"""Characters in the "also, always" line. A sentence or two; a page of standing
instruction is a second system prompt, applied to every answer."""

MAX_REFER_TO = 60
MAX_NAME = 60
MAX_DESCRIPTION = 300
MAX_INSTRUCTION = 2000

MAX_SKILLS = 40
"""Skills one person can write. Their names are offered to the assistant, so the
list has to stay the length of a menu."""


class PreferenceError(ValueError):
    """A preference or skill that cannot be saved as given. Safe to show."""


# ---------------------------------------------------------------------------
# Preferences: fixed choices, one wording each
# ---------------------------------------------------------------------------

VERDICT_FIRST = (
    "If the question asks for a position -- does, do, is, are, have, can -- open with "
    "the verdict (Yes, No, Partially or Not applicable), stating exactly the position "
    "the answer already takes. A question that asks to describe, explain or list "
    "gets no verdict added."
)
"""Says what not to do as well as what to do, because the looser version failed
on the real model: told to open with a verdict "whenever the question can be
answered that way", it answered "Describe your incident response process" with
"Yes."."""
REFER_TO = 'Refer to the organisation as "{name}" rather than "the organisation" or "the company".'
CITATIONS_ONLY = (
    "Do not name our internal policy documents, or their section and clause numbers, "
    "in the text: the citations shown beside the answer carry them. A standard, law "
    "or framework the question itself asks about stays named."
)
FORMAL = "Use a formal, professional register."
PLAIN = "Use plain, direct language: short sentences, and no jargon a customer would not use."


@dataclass(frozen=True)
class Preferences:
    default_length: str = "full"
    verdict_first: bool = False
    refer_to: str = ""
    policy_references: str = "keep"
    tone: str = "as_drafted"
    also: str = ""

    def instruction(self) -> str:
        """What the rewrite is told, or "" when every choice is "as drafted".

        Assembled from fixed sentences in a fixed order, so the same choices
        always produce the same instruction -- which is what lets one of them
        be tested and then trusted across a whole questionnaire.
        """
        parts = []
        if self.verdict_first:
            parts.append(VERDICT_FIRST)
        if self.refer_to.strip():
            parts.append(REFER_TO.format(name=self.refer_to.strip()))
        if self.policy_references == "citations_only":
            parts.append(CITATIONS_ONLY)
        if self.tone == "formal":
            parts.append(FORMAL)
        elif self.tone == "plain":
            parts.append(PLAIN)
        if self.also.strip():
            parts.append(f"Also: {self.also.strip()}")
        return "\n".join(parts)

    @property
    def rewords(self) -> bool:
        """Whether answers are reworded at all. False costs nothing extra."""
        return bool(self.instruction())

    def as_dict(self) -> dict:
        return {
            "default_length": self.default_length,
            "verdict_first": self.verdict_first,
            "refer_to": self.refer_to,
            "policy_references": self.policy_references,
            "tone": self.tone,
            "also": self.also,
        }


def recommended(short_name: str) -> Preferences:
    """The setup that makes answers read the way the security team's own do.

    Measured over the 1,055 answers in their filled questionnaires: two thirds
    open with a verdict, they call the company by name, and not one of them
    cites a clause number in the text. Tone is left alone -- theirs varies with
    the customer -- and so is length, which the team chooses per questionnaire.
    Offered, never applied: nobody's answers change until they choose it.
    """
    return Preferences(
        verdict_first=True,
        refer_to=short_name,
        policy_references="citations_only",
    )


def load(email: str) -> Preferences:
    """This person's preferences, or the defaults when they have set none."""
    row = (
        store.connect()
        .execute(
            "SELECT * FROM user_preferences WHERE email = ?",
            (normalise(email),),
        )
        .fetchone()
    )
    if row is None:
        return Preferences()
    return Preferences(
        default_length=row["default_length"] if row["default_length"] in LENGTHS else "full",
        verdict_first=bool(row["verdict_first"]),
        refer_to=row["refer_to"],
        policy_references=(row["policy_references"] if row["policy_references"] in REFERENCES else "keep"),
        tone=row["tone"] if row["tone"] in TONES else "as_drafted",
        also=row["style"],
    )


def save(email: str, **changes) -> Preferences:
    """Change any of the choices, leaving the others as they were."""
    unknown = set(changes) - set(Preferences.__dataclass_fields__)
    if unknown:
        raise PreferenceError(f"Unknown preference: {', '.join(sorted(unknown))}.")
    wanted = replace(load(email), **{k: v for k, v in changes.items() if v is not None})
    wanted = replace(
        wanted,
        refer_to=" ".join(wanted.refer_to.split()),
        also=_clean_block(wanted.also),
        verdict_first=bool(wanted.verdict_first),
    )

    if wanted.default_length not in LENGTHS:
        raise PreferenceError("The default length is either full or brief.")
    if wanted.tone not in TONES:
        raise PreferenceError("The tone is as drafted, formal, or plain.")
    if wanted.policy_references not in REFERENCES:
        raise PreferenceError("Policy references are either kept in the text or left to the citations.")
    if len(wanted.refer_to) > MAX_REFER_TO:
        raise PreferenceError(f"What to call us can be at most {MAX_REFER_TO} characters.")
    if '"' in wanted.refer_to:
        raise PreferenceError("Write what to call us without quotation marks.")
    if len(wanted.also) > MAX_ALSO:
        raise PreferenceError(f"The extra line can be at most {MAX_ALSO} characters; this one is {len(wanted.also)}.")

    conn = store.connect()
    conn.execute(
        """
        INSERT INTO user_preferences
            (email, style, default_length, verdict_first, refer_to, policy_references, tone, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            style = excluded.style,
            default_length = excluded.default_length,
            verdict_first = excluded.verdict_first,
            refer_to = excluded.refer_to,
            policy_references = excluded.policy_references,
            tone = excluded.tone,
            updated_at = excluded.updated_at
        """,
        (
            normalise(email),
            wanted.also,
            wanted.default_length,
            int(wanted.verdict_first),
            wanted.refer_to,
            wanted.policy_references,
            wanted.tone,
            store.utcnow(),
        ),
    )
    conn.commit()
    return wanted


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Skill:
    skill_id: str
    owner_email: str
    name: str
    description: str
    instruction: str
    created_at: str = ""
    updated_at: str = ""
    builtin: bool = False


BUILTIN_SKILLS: tuple[Skill, ...] = (
    Skill(
        skill_id="builtin-auditor-detail",
        owner_email="",
        name="Auditor detail",
        description="For an auditor checking evidence: every specific kept, each tied to its policy.",
        instruction=(
            "Write for an auditor who will check each statement against evidence. Keep "
            "the verdict the answer opens with. State each control as a specific, "
            "verifiable fact, and keep every frequency, threshold, owner, deadline and "
            "system the answer gives. Name the policy the controls come from once, not "
            "after every sentence. Do not summarise, and add nothing the answer does not say."
        ),
        builtin=True,
    ),
    Skill(
        skill_id="builtin-plain-language",
        owner_email="",
        name="Plain language",
        description="For a customer who is not a security specialist.",
        instruction=(
            "Write for a reader at the customer who is not a security specialist. Use "
            "plain words and short sentences, spell out any acronym the first time it "
            "appears, and leave out internal policy names and clause numbers. Keep every "
            "commitment, figure and deadline the answer gives."
        ),
        builtin=True,
    ),
    Skill(
        skill_id="builtin-executive-summary",
        owner_email="",
        name="Executive summary",
        description="Two sentences for a senior reader: the position, and why.",
        instruction=(
            "Write for a senior reader with a minute to spare: at most two sentences. "
            "First our position on what was asked, then the one control that best "
            "supports it. No technical detail and no policy references."
        ),
        builtin=True,
    ),
    Skill(
        skill_id="builtin-bullet-points",
        owner_email="",
        name="Bullet points",
        description="For process questions: the verdict, then one line per control.",
        instruction=(
            "Open with the verdict on its own line when the answer has one. Then list "
            "the specific controls or steps the answer describes, one per line, each "
            "line starting with a hyphen and each a complete sentence. Keep every fact; "
            "add none."
        ),
        builtin=True,
    ),
)
_BUILTIN = {skill.skill_id: skill for skill in BUILTIN_SKILLS}

BUILTIN_READ_ONLY = "Built-in skills cannot be changed. Make a copy and edit that instead."


def _skill(row) -> Skill:
    return Skill(
        skill_id=row["skill_id"],
        owner_email=row["owner_email"],
        name=row["name"],
        description=row["description"],
        instruction=row["instruction"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def own_skills(email: str) -> list[Skill]:
    """The skills this person wrote, by name."""
    rows = (
        store.connect()
        .execute(
            "SELECT * FROM skills WHERE owner_email = ? ORDER BY name COLLATE NOCASE",
            (normalise(email),),
        )
        .fetchall()
    )
    return [_skill(row) for row in rows]


def skills(email: str) -> list[Skill]:
    """Every skill this person can use: the built-in ones, then their own."""
    return list(BUILTIN_SKILLS) + own_skills(email)


def get_skill(email: str, skill_id: str) -> Skill | None:
    """One skill, only if it is built in or this person's.

    Owner and id together, always. A skill id that belongs to somebody else is
    indistinguishable from one that does not exist, which is what personal
    means once it reaches a URL.
    """
    if skill_id in _BUILTIN:
        return _BUILTIN[skill_id]
    row = (
        store.connect()
        .execute(
            "SELECT * FROM skills WHERE skill_id = ? AND owner_email = ?",
            (skill_id, normalise(email)),
        )
        .fetchone()
    )
    return _skill(row) if row else None


def find_skill(email: str, name: str) -> tuple[Skill | None, list[Skill]]:
    """A skill by the name somebody used for it, and what else it could have meant.

    People say "use my Zain one" for a skill saved as "Zain format", so an exact
    name wins and a name that is part of exactly one skill's name is taken as
    that skill. Anything looser is a guess, and applying the wrong style to a
    whole questionnaire is not something to guess about: when more than one
    matches, nothing is chosen and the candidates come back so the caller can
    ask.
    """
    wanted = " ".join((name or "").split()).casefold()
    usable = skills(email)
    if not wanted:
        return None, []
    exact = [skill for skill in usable if skill.name.casefold() == wanted]
    if exact:
        return exact[0], []
    partial = [skill for skill in usable if wanted in skill.name.casefold()]
    if len(partial) == 1:
        return partial[0], []
    return None, partial


def add_skill(email: str, name: str, instruction: str, description: str = "") -> Skill:
    name, description, instruction = _validate(name, description, instruction)
    owner = normalise(email)
    if len(own_skills(owner)) >= MAX_SKILLS:
        raise PreferenceError(f"You can keep at most {MAX_SKILLS} skills. Remove one you no longer use first.")
    _refuse_duplicate(owner, name)

    now = store.utcnow()
    skill = Skill(
        skill_id=f"skill-{uuid.uuid4().hex[:12]}",
        owner_email=owner,
        name=name,
        description=description,
        instruction=instruction,
        created_at=now,
        updated_at=now,
    )
    conn = store.connect()
    conn.execute(
        "INSERT INTO skills (skill_id, owner_email, name, description, instruction, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (skill.skill_id, owner, name, description, instruction, now, now),
    )
    conn.commit()
    return skill


def copy_skill(email: str, skill_id: str) -> Skill | None:
    """A skill of this person's own, starting from one they can use.

    How a built-in skill is changed: not in place, where the change would reach
    everybody, but as a copy under a name that says it is one.
    """
    source = get_skill(email, skill_id)
    if source is None:
        return None
    taken = {skill.name.casefold() for skill in skills(email)}
    name, number = f"{source.name} (my copy)", 2
    while name.casefold() in taken:
        name, number = f"{source.name} (my copy {number})", number + 1
    return add_skill(email, name[:MAX_NAME], source.instruction, source.description)


def update_skill(
    email: str,
    skill_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    instruction: str | None = None,
) -> Skill | None:
    if skill_id in _BUILTIN:
        raise PreferenceError(BUILTIN_READ_ONLY)
    current = get_skill(email, skill_id)
    if current is None:
        return None
    name, description, instruction = _validate(
        current.name if name is None else name,
        current.description if description is None else description,
        current.instruction if instruction is None else instruction,
    )
    if name.casefold() != current.name.casefold():
        _refuse_duplicate(current.owner_email, name)

    now = store.utcnow()
    conn = store.connect()
    conn.execute(
        "UPDATE skills SET name = ?, description = ?, instruction = ?, updated_at = ? "
        "WHERE skill_id = ? AND owner_email = ?",
        (name, description, instruction, now, skill_id, current.owner_email),
    )
    conn.commit()
    return get_skill(email, skill_id)


def remove_skill(email: str, skill_id: str) -> bool:
    if skill_id in _BUILTIN:
        raise PreferenceError(BUILTIN_READ_ONLY)
    conn = store.connect()
    deleted = conn.execute(
        "DELETE FROM skills WHERE skill_id = ? AND owner_email = ?",
        (skill_id, normalise(email)),
    ).rowcount
    conn.commit()
    return bool(deleted)


def _validate(name: str, description: str, instruction: str) -> tuple[str, str, str]:
    # A name is said aloud to the assistant and shown in a menu, so it is one
    # line; the other two keep their paragraphs.
    name = " ".join((name or "").split())
    description = _clean_block(description)
    instruction = _clean_block(instruction)
    if not name:
        raise PreferenceError("A skill needs a name.")
    if len(name) > MAX_NAME:
        raise PreferenceError(f"A skill's name can be at most {MAX_NAME} characters.")
    if len(description) > MAX_DESCRIPTION:
        raise PreferenceError(f"A skill's description can be at most {MAX_DESCRIPTION} characters.")
    if not instruction:
        raise PreferenceError("A skill needs an instruction: how should the answers change?")
    if len(instruction) > MAX_INSTRUCTION:
        raise PreferenceError(f"A skill's instruction can be at most {MAX_INSTRUCTION} characters.")
    return name, description, instruction


def _refuse_duplicate(owner: str, name: str) -> None:
    for skill in skills(owner):
        if skill.name.casefold() == name.casefold():
            raise PreferenceError(
                f"There is already a built-in skill called {name!r}. Make a copy to change it."
                if skill.builtin
                else f"You already have a skill called {name!r}."
            )


def _clean_block(text: str) -> str:
    """Trim a paragraph field without flattening the lines inside it."""
    lines = [line.rstrip() for line in (text or "").strip().splitlines()]
    return "\n".join(lines)
