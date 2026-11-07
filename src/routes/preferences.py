"""The preferences and skills routes, and the interface's language (plan 038).

Moved out of `src/api.py` unchanged and included where they were, to make room
for the language route beside them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src import events, interface_language, preferences, rewrite
from src.errors import NotFound
from src.extraction import detect_question_language
from src.identity import User
from src.models import AnsweredQuestion, Question
from src.routes.auth import current_user
from src.routes.pages import page

router = APIRouter()


# ---------------------------------------------------------------------------
# Preferences and skills
#
# Personal, unlike everything above: how one reviewer likes an answer worded is
# a fact about that reviewer, not about the organisation. So every route here
# acts on the signed-in person's own record and nobody else's, and a skill id
# that belongs to a colleague answers exactly as one that does not exist.
#
# Nothing here reaches the drafter. See `src.preferences`.
# ---------------------------------------------------------------------------


def skill_payload(skill: preferences.Skill) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "instruction": skill.instruction,
        "builtin": skill.builtin,
        "updated_at": skill.updated_at,
    }


@router.get("/preferences", include_in_schema=False)
def preferencespage() -> HTMLResponse:
    return page("preferences.html")


@router.get("/api/preferences")
def get_preferences(user: User = Depends(current_user)) -> dict[str, Any]:
    """Preferences, what they add up to, and every skill this person can use."""
    from src import organisation

    mine = preferences.load(user.email)
    return {
        "preferences": mine.as_dict(),
        "instruction": mine.instruction(),
        "recommended": preferences.recommended(organisation.load().short_name).as_dict(),
        "skills": [skill_payload(skill) for skill in preferences.skills(user.email)],
        "limits": {
            "also": preferences.MAX_ALSO,
            "refer_to": preferences.MAX_REFER_TO,
            "name": preferences.MAX_NAME,
            "description": preferences.MAX_DESCRIPTION,
            "instruction": preferences.MAX_INSTRUCTION,
            "skills": preferences.MAX_SKILLS,
        },
    }


class PreferencesRequest(BaseModel):
    default_length: str | None = Field(default=None, pattern="^(full|brief)$")
    verdict_first: bool | None = None
    refer_to: str | None = Field(default=None, max_length=preferences.MAX_REFER_TO)
    policy_references: str | None = Field(default=None, pattern="^(keep|citations_only)$")
    tone: str | None = Field(default=None, pattern="^(as_drafted|formal|plain)$")
    also: str | None = Field(default=None, max_length=preferences.MAX_ALSO)


@router.put("/api/preferences")
def save_preferences(body: PreferencesRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    saved = preferences.save(user.email, **body.model_dump())
    events.record(
        user,
        events.PREFERENCES_CHANGED,
        subject_type="preferences",
        subject_id=user.email,
        rewords=saved.rewords,
        **{k: v for k, v in saved.as_dict().items() if k != "also"},
    )
    return get_preferences(user)


@router.post("/api/preferences/compose")
def compose_preferences(body: PreferencesRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    """What a set of choices would tell the rewrite, without saving them.

    So the page can show the instruction as the choices change, and try it on a
    sample, from the one place that assembles it -- a copy of that logic in the
    browser would drift from the one that actually runs.
    """
    try:
        candidate = preferences.Preferences(
            **{
                **preferences.load(user.email).as_dict(),
                **{k: v for k, v in body.model_dump().items() if v is not None},
            }
        )
    except TypeError as bad:
        raise preferences.PreferenceError("Those preferences could not be applied.") from bad
    return {"instruction": candidate.instruction()}


class TryStyleRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=preferences.MAX_INSTRUCTION)
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=20000)


@router.post("/api/preferences/try")
async def try_a_style(body: TryStyleRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    """What an instruction does to one answer, before it is let loose on all of them.

    Preferences are applied to every answer somebody drafts and a skill to a
    whole selection, so a badly worded one reaches a questionnaire at once.
    This is the same rewrite over one sample, stored nowhere, so the person sees
    the effect first.
    """
    sample = AnsweredQuestion(
        question=Question(
            id="sample",
            text=body.question,
            language=detect_question_language(body.question),
        ),
        answer=body.answer,
        confidence=1.0,
    )
    reworded = await rewrite.rewrite(sample, body.instruction, note="Tried out.")
    return {
        "before": body.answer,
        "after": reworded.answer,
        "changed": reworded is not sample and reworded.answer.strip() != body.answer.strip(),
        "failed": reworded is sample,
    }


class SkillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=preferences.MAX_NAME)
    description: str = Field(default="", max_length=preferences.MAX_DESCRIPTION)
    instruction: str = Field(min_length=1, max_length=preferences.MAX_INSTRUCTION)


class SkillEditRequest(BaseModel):
    name: str | None = Field(default=None, max_length=preferences.MAX_NAME)
    description: str | None = Field(default=None, max_length=preferences.MAX_DESCRIPTION)
    instruction: str | None = Field(default=None, max_length=preferences.MAX_INSTRUCTION)


@router.post("/api/skills")
def add_skill(body: SkillRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    skill = preferences.add_skill(
        user.email,
        body.name,
        body.instruction,
        body.description,
    )
    events.record(
        user,
        events.SKILL_ADDED,
        subject_type="skill",
        subject_id=skill.skill_id,
        name=skill.name,
    )
    return skill_payload(skill)


@router.patch("/api/skills/{skill_id}")
def edit_skill(skill_id: str, body: SkillEditRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    skill = preferences.update_skill(
        user.email,
        skill_id,
        name=body.name,
        description=body.description,
        instruction=body.instruction,
    )
    if skill is None:
        raise NotFound("You have no skill like that.", code="skill_not_found")
    events.record(
        user,
        events.SKILL_EDITED,
        subject_type="skill",
        subject_id=skill_id,
        name=skill.name,
    )
    return skill_payload(skill)


@router.delete("/api/skills/{skill_id}")
def remove_skill(skill_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    if not preferences.remove_skill(user.email, skill_id):
        raise NotFound("You have no skill like that.", code="skill_not_found")
    events.record(user, events.SKILL_REMOVED, subject_type="skill", subject_id=skill_id)
    return {"deleted": skill_id}


@router.post("/api/skills/{skill_id}/copy")
def copy_skill(skill_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """A skill of your own, starting from a built-in one or another of yours."""
    skill = preferences.copy_skill(user.email, skill_id)
    if skill is None:
        raise NotFound("You have no skill like that.", code="skill_not_found")
    events.record(
        user,
        events.SKILL_ADDED,
        subject_type="skill",
        subject_id=skill.skill_id,
        name=skill.name,
        copied_from=skill_id,
    )
    return skill_payload(skill)


class LanguageRequest(BaseModel):
    language: str = Field(pattern="^(en|ar)$")


@router.put("/api/preferences/language")
def choose_language(body: LanguageRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    """The language this person sees the pages in, English or Arabic (plan 038). Answers are not changed."""
    return {"interface_language": interface_language.choose(user.email, body.language)}
