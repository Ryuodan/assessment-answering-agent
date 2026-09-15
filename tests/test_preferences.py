"""Preferences and skills: how one person wants their answers worded.

Three promises are tested here, in order of how badly breaking them would hurt:

1. **Nothing personal reaches the drafter.** Preferences and skills are applied
   by rewording an answer that was already grounded and reviewed; the answering
   pipeline is never handed them.
2. **Nobody else's words are touched.** Preferences and your own skills belong
   to one person, and a sentence somebody wrote by hand is not reworded under a
   blanket instruction.
3. **A rewording never costs an answer.** It is applied after drafting, keeps
   the draft, can be undone, and one that fails leaves the draft in place.

And one about the two kinds themselves: a preference is a fixed choice with one
tested wording, and a skill is a named instruction for a particular job.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, batches, events, identity, preferences, tools
from src.agents import assistant
from src.api import app
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes

ALICE = "m.alsaif@t2.sa"
BOB = "mohammed.sa.alsaif@gmail.com"
CODE = "TEAM-CODE-FOR-TESTS"
BUILTIN_NAMES = {skill.name for skill in preferences.BUILTIN_SKILLS}


@pytest.fixture
def user():
    return identity.local_user()


@pytest.fixture
def batch(user, tmp_path):
    return tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))


@pytest.fixture
def drafted(monkeypatch):
    """Stand in for the pipeline, recording exactly what it was handed."""
    seen: dict = {"calls": []}

    async def fake(questions, language=None, run_id=None, **extra):
        seen["calls"].append({"questions": list(questions), "language": language, **extra})
        return [
            AnsweredQuestion(
                question=question,
                answer=f"Yes. The organisation reviews access quarterly (section 3.1). [{question.id}]",
                confidence=0.9,
                needs_review=False,
                citations=["T2 - Access Control Policy.pdf §3.1"],
            )
            for question in questions
        ]

    monkeypatch.setattr(tools.service, "answer_questions", fake)
    return seen


@pytest.fixture
def reworded(monkeypatch):
    """Stand in for the rewrite: records its instructions, returns a marked copy."""
    seen: dict = {"instructions": [], "notes": [], "languages": []}

    async def fake(answered, instruction, language=None, *, note=""):
        seen["instructions"].append(instruction)
        seen["notes"].append(note)
        seen["languages"].append(language)
        revised = answered.model_copy(deep=True)
        revised.answer = f"STYLED: {answered.answer}"
        revised.by_hand = False
        return revised

    monkeypatch.setattr(tools.rewrite, "rewrite", fake)
    return seen


def choose(email: str, **choices) -> str:
    """Save some preferences and return what they add up to."""
    return preferences.save(email, **choices).instruction()


# --- preferences are choices ----------------------------------------------------


def test_everything_starts_as_drafted_and_costs_nothing():
    mine = preferences.load(ALICE)
    assert mine == preferences.Preferences()
    assert mine.instruction() == "" and not mine.rewords


def test_each_choice_has_one_wording_in_a_fixed_order():
    instruction = choose(
        ALICE, verdict_first=True, refer_to="T2", policy_references="citations_only", tone="formal",
        also="Write Not applicable, never N/A.",
    )
    assert instruction.splitlines() == [
        preferences.VERDICT_FIRST,
        preferences.REFER_TO.format(name="T2"),
        preferences.CITATIONS_ONLY,
        preferences.FORMAL,
        "Also: Write Not applicable, never N/A.",
    ]
    assert choose(ALICE, verdict_first=True, refer_to="T2", policy_references="citations_only",
                  tone="formal", also="Write Not applicable, never N/A.") == instruction, "the same every time"


def test_the_verdict_wording_says_what_not_to_add():
    """The looser wording answered "Describe your incident response process"
    with "Yes." on the real model."""
    assert "describe, explain or list" in preferences.VERDICT_FIRST
    assert "gets no verdict added" in preferences.VERDICT_FIRST


def test_removing_references_keeps_what_the_question_asks_about():
    """"Are you ISO 27001 certified?" cannot be answered without naming it."""
    assert "the question itself asks about stays named" in preferences.CITATIONS_ONLY


def test_setting_one_choice_leaves_the_others_alone():
    preferences.save(ALICE, tone="plain")
    preferences.save(ALICE, default_length="brief")
    mine = preferences.load(ALICE)
    assert mine.tone == "plain" and mine.default_length == "brief"


def test_preferences_are_one_persons_and_addresses_are_not_case_sensitive():
    preferences.save(ALICE, refer_to="T2")
    assert preferences.load(ALICE.upper()).refer_to == "T2"
    assert preferences.load(BOB).refer_to == ""


@pytest.mark.parametrize("bad", [
    {"default_length": "medium"},
    {"tone": "sarcastic"},
    {"policy_references": "sometimes"},
    {"refer_to": "x" * (preferences.MAX_REFER_TO + 1)},
    {"refer_to": 'the "company"'},
    {"also": "x" * (preferences.MAX_ALSO + 1)},
    {"colour": "blue"},
])
def test_a_choice_that_does_not_exist_is_refused(bad):
    with pytest.raises(preferences.PreferenceError):
        preferences.save(ALICE, **bad)


def test_the_extra_line_keeps_its_lines():
    preferences.save(ALICE, also="  Write Not applicable.\n\nNever N/A.   \n")
    assert preferences.load(ALICE).also == "Write Not applicable.\n\nNever N/A."


def test_an_instruction_saved_before_preferences_were_choices_still_applies(user):
    """Migration 8 kept a paragraph; migration 9 keeps it as the extra line."""
    from src import store

    conn = store.connect()
    conn.execute(
        "INSERT INTO user_preferences (email, style, default_length, updated_at) VALUES (?, ?, 'full', '')",
        (ALICE, "Open with Yes or No."),
    )
    conn.commit()

    assert preferences.load(ALICE).instruction() == "Also: Open with Yes or No."


def test_the_recommended_setup_is_how_the_team_writes_and_is_only_offered():
    offer = preferences.recommended("T2")
    assert offer.verdict_first and offer.refer_to == "T2" and offer.policy_references == "citations_only"
    assert offer.tone == "as_drafted" and offer.default_length == "full"
    assert preferences.load(ALICE) == preferences.Preferences(), "offering it changes nobody's answers"


# --- skills: built in, and your own ---------------------------------------------


def test_everybody_has_the_built_in_skills():
    assert {s.name for s in preferences.skills(ALICE)} == BUILTIN_NAMES
    assert {s.name for s in preferences.skills(BOB)} == BUILTIN_NAMES
    assert all(s.builtin for s in preferences.BUILTIN_SKILLS)
    assert preferences.own_skills(ALICE) == []


def test_a_built_in_skill_cannot_be_changed_or_removed_but_can_be_copied():
    auditor = next(s for s in preferences.BUILTIN_SKILLS if s.name == "Auditor detail")

    with pytest.raises(preferences.PreferenceError, match="Make a copy"):
        preferences.update_skill(ALICE, auditor.skill_id, instruction="Anything.")
    with pytest.raises(preferences.PreferenceError, match="Make a copy"):
        preferences.remove_skill(ALICE, auditor.skill_id)

    copy = preferences.copy_skill(ALICE, auditor.skill_id)
    again = preferences.copy_skill(ALICE, auditor.skill_id)

    assert copy.name == "Auditor detail (my copy)" and not copy.builtin
    assert again.name == "Auditor detail (my copy 2)"
    assert copy.instruction == auditor.instruction
    assert [s.name for s in preferences.own_skills(BOB)] == [], "a copy is the copier's"


def test_your_own_skill_is_kept_found_changed_and_removed():
    skill = preferences.add_skill(ALICE, "Zain format", "One sentence, verdict first.", "Zain's forms")
    assert [s.name for s in preferences.own_skills(ALICE)] == ["Zain format"]

    changed = preferences.update_skill(ALICE, skill.skill_id, instruction="Two sentences.")
    assert changed.instruction == "Two sentences." and changed.name == "Zain format"

    assert preferences.remove_skill(ALICE, skill.skill_id) is True
    assert preferences.own_skills(ALICE) == []
    assert preferences.remove_skill(ALICE, skill.skill_id) is False


def test_no_two_skills_share_a_name_whatever_the_case():
    preferences.add_skill(ALICE, "Zain format", "One sentence.")
    with pytest.raises(preferences.PreferenceError, match="already have"):
        preferences.add_skill(ALICE, "zain FORMAT", "Something else.")
    with pytest.raises(preferences.PreferenceError, match="built-in"):
        preferences.add_skill(ALICE, "executive SUMMARY", "Mine.")

    other = preferences.add_skill(ALICE, "Auditor notes", "Full detail.")
    with pytest.raises(preferences.PreferenceError, match="already have"):
        preferences.update_skill(ALICE, other.skill_id, name="Zain Format")


def test_a_skill_needs_a_name_and_an_instruction():
    with pytest.raises(preferences.PreferenceError, match="name"):
        preferences.add_skill(ALICE, "   ", "One sentence.")
    with pytest.raises(preferences.PreferenceError, match="instruction"):
        preferences.add_skill(ALICE, "Zain format", "  \n ")


def test_there_is_a_limit_to_how_many_skills_one_person_writes(monkeypatch):
    monkeypatch.setattr(preferences, "MAX_SKILLS", 2)
    preferences.add_skill(ALICE, "One", "a")
    preferences.add_skill(ALICE, "Two", "b")
    with pytest.raises(preferences.PreferenceError, match="at most 2"):
        preferences.add_skill(ALICE, "Three", "c")


def test_your_own_skills_are_personal():
    """A colleague's skill id is indistinguishable from one that does not exist."""
    mine = preferences.add_skill(ALICE, "Zain format", "One sentence.")

    assert preferences.own_skills(BOB) == []
    assert preferences.get_skill(BOB, mine.skill_id) is None
    assert preferences.update_skill(BOB, mine.skill_id, name="Stolen") is None
    assert preferences.remove_skill(BOB, mine.skill_id) is False
    assert preferences.copy_skill(BOB, mine.skill_id) is None
    assert preferences.get_skill(ALICE, mine.skill_id).name == "Zain format"


def test_a_skill_is_found_by_the_name_somebody_actually_says():
    zain = preferences.add_skill(ALICE, "Zain format", "One sentence.")
    preferences.add_skill(ALICE, "Auditor notes", "Short.")

    assert preferences.find_skill(ALICE, "zain format")[0] == zain, "exact, any case"
    assert preferences.find_skill(ALICE, "zain")[0] == zain, "part of exactly one name"
    assert preferences.find_skill(ALICE, "executive")[0].name == "Executive summary", "built in too"

    found, candidates = preferences.find_skill(ALICE, "auditor")
    assert found is None, "two match, so nothing is guessed"
    assert {s.name for s in candidates} == {"Auditor detail", "Auditor notes"}

    assert preferences.find_skill(ALICE, "nothing like it") == (None, [])


# --- the drafter never sees it ----------------------------------------------


async def test_preferences_are_never_handed_to_the_answering_pipeline(user, batch, drafted, reworded):
    """The promise the whole feature rests on. An instruction inside the grounded
    prompt is indistinguishable from an instruction to ignore the sources."""
    instruction = choose(user.email, verdict_first=True, refer_to="T2", also="Never say N/A.")

    await tools.answer(user, batch.id)

    [call] = drafted["calls"]
    assert set(call) <= {"questions", "language", "run_id"}, call.keys()
    assert all("N/A" not in (q.text + (q.section or "")) for q in call["questions"])
    assert reworded["instructions"] == [instruction] * len(batch.form.questions), (
        "it reaches the rewrite, after drafting, and only there"
    )


async def test_every_answer_somebody_drafts_is_reworded_to_their_preferences(user, batch, drafted, reworded):
    choose(user.email, refer_to="T2")

    outcome = await tools.answer(user, batch.id)

    stored = batches.answers(batch.id)
    assert outcome.styled == len(batch.form.questions)
    for answered in stored.values():
        assert answered.answer.startswith("STYLED: ")
        assert answered.drafted.startswith("Yes. The organisation"), "the draft is kept"
        assert answered.citations, "the citations come through"
    assert reworded["notes"] == ["Reworded to your preferences."] * len(stored)


async def test_nobody_elses_preferences_are_applied(user, batch, drafted, reworded):
    choose(BOB, refer_to="T2")

    outcome = await tools.answer(user, batch.id)

    assert reworded["instructions"] == []
    assert outcome.styled == 0
    assert all(not a.drafted for a in batches.answers(batch.id).values())


async def test_choices_left_as_drafted_mean_no_extra_call(user, batch, drafted, reworded):
    preferences.save(user.email, default_length="full", tone="as_drafted", policy_references="keep")
    await tools.answer(user, batch.id)
    assert reworded["instructions"] == []


async def test_a_rewording_that_fails_costs_the_wording_not_the_answer(user, batch, drafted, monkeypatch):
    choose(user.email, refer_to="T2")
    calls = {"n": 0}

    async def flaky(answered, instruction, language=None, *, note=""):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the model is having a day")
        return answered  # the rewrite's own way of saying it could not reword

    monkeypatch.setattr(tools.rewrite, "rewrite", flaky)

    outcome = await tools.answer(user, batch.id)

    assert outcome.answered == len(batch.form.questions)
    assert outcome.styled == 0
    for answered in batches.answers(batch.id).values():
        assert answered.answer.startswith("Yes. The organisation") and not answered.drafted


async def test_a_forced_language_reaches_the_rewrite(user, drafted, reworded):
    """Left out, an Arabic question's English answer would be reworded back
    into Arabic."""
    choose(user.email, refer_to="T2")
    from src.models import Question

    answers = [AnsweredQuestion(
        question=Question(id="1", text="هل يتم تشفير البيانات؟", language="ar"),
        answer="Yes.", confidence=0.9,
    )]
    await tools.in_house_style(user, answers, language="en")

    assert reworded["languages"] == ["en"]


def test_the_typed_questions_path_applies_preferences_too(drafted, reworded):
    """Every answer somebody drafts, however it was asked for."""
    choose(identity.local_user().email, refer_to="T2")
    client = TestClient(app)

    body = client.post("/api/assessments/answer-questions", json={
        "questions": [{"text": "Do you review access rights?"}],
    }).json()

    assert body["answers"][0]["answer"].startswith("STYLED: ")
    assert body["answers"][0]["drafted"].startswith("Yes. The organisation")


# --- undoing it, and a person's words -----------------------------------------


async def test_the_draft_can_be_put_back(user, batch, drafted, reworded):
    choose(user.email, refer_to="T2")
    await tools.answer(user, batch.id)
    question_id = batch.form.questions[0].id

    tools.restore_draft(user, batch.id, question_id)

    answered = batches.answers(batch.id)[question_id]
    assert answered.answer.startswith("Yes. The organisation")
    assert answered.drafted == ""

    with pytest.raises(tools.ToolError, match="nothing to put back"):
        tools.restore_draft(user, batch.id, question_id)


async def test_a_skill_can_be_undone_with_no_preferences_set(user, batch, drafted, reworded):
    await tools.answer(user, batch.id)
    skill = preferences.add_skill(user.email, "Zain format", "One sentence.")
    await tools.apply_skill(user, batch.id, skill.skill_id)
    question_id = batch.form.questions[0].id
    assert batches.answers(batch.id)[question_id].drafted.startswith("Yes. The organisation")

    tools.restore_draft(user, batch.id, question_id)

    assert batches.answers(batch.id)[question_id].answer.startswith("Yes. The organisation")


async def test_undo_always_means_the_grounded_draft(user, batch, drafted, reworded):
    """Preferences, then a skill, then "shorter": putting it back goes to what
    the pipeline wrote, not to whichever rewording came before the last."""
    choose(user.email, refer_to="T2")
    await tools.answer(user, batch.id)
    await tools.revise(user, batch.id, "Shorter.")
    await tools.revise(user, batch.id, "More formal.")
    question_id = batch.form.questions[0].id

    answered = batches.answers(batch.id)[question_id]
    assert answered.answer.startswith("STYLED: STYLED: STYLED: ")
    assert answered.drafted.startswith("Yes. The organisation")


async def test_a_persons_words_are_never_kept_as_a_draft(user, batch, drafted, reworded):
    """Put back, they would return marked as the model's."""
    await tools.answer(user, batch.id)
    question_id = batch.form.questions[0].id
    tools.set_answer(user, batch.id, question_id, "Yes, quarterly.")

    await tools.revise(user, batch.id, "More formal.", tools.Scope(ids=(question_id,)), include_written=True)

    assert batches.answers(batch.id)[question_id].drafted == ""


async def test_writing_an_answer_by_hand_replaces_the_draft_too(user, batch, drafted, reworded):
    choose(user.email, refer_to="T2")
    await tools.answer(user, batch.id)
    question_id = batch.form.questions[0].id

    tools.set_answer(user, batch.id, question_id, "Yes, quarterly, owned by the CISO.")

    assert batches.answers(batch.id)[question_id].drafted == ""


async def test_rewording_leaves_what_a_person_wrote_alone(user, batch, drafted, reworded):
    """"Make them all more formal" is about the drafts. Rewording a reviewer's
    own sentence under it would put the model's words where theirs were."""
    await tools.answer(user, batch.id)
    mine = batch.form.questions[0].id
    tools.set_answer(user, batch.id, mine, "Yes, quarterly, owned by the CISO.")

    outcome = await tools.revise(user, batch.id, "More formal.")

    assert outcome.protected == 1
    assert outcome.attempted == len(batch.form.questions) - 1
    assert batches.answers(batch.id)[mine].answer == "Yes, quarterly, owned by the CISO."


async def test_asked_for_by_name_a_persons_answer_can_be_reworded(user, batch, drafted, reworded):
    await tools.answer(user, batch.id)
    mine = batch.form.questions[0].id
    tools.set_answer(user, batch.id, mine, "Yes, quarterly, owned by the CISO.")

    await tools.revise(user, batch.id, "More formal.", tools.Scope(ids=(mine,)), include_written=True)

    answered = batches.answers(batch.id)[mine]
    assert answered.answer.startswith("STYLED: ")
    # And the words are the model's now: approving it must not teach the memory.
    assert answered.by_hand is False
    assert answered.confidence_reason != tools.HAND


async def test_a_reworded_answer_has_to_be_approved_again(user, batch, drafted, reworded, memory_index):
    """The approval was for different words."""
    await tools.answer(user, batch.id)
    question_id = batch.form.questions[0].id
    tools.approve_answer(user, batch.id, question_id)

    await tools.revise(user, batch.id, "Shorter.")

    answered = batches.answers(batch.id)[question_id]
    assert answered.confidence_reason != tools.APPROVED
    assert tools.inspect(user, batch.id)["questions"][0]["approved"] is False


async def test_a_rewording_that_failed_is_not_written_back(user, batch, drafted, monkeypatch):
    """Writing an unchanged answer back through the store cleared who had
    edited it, for nothing."""
    await tools.answer(user, batch.id)
    question_id = batch.form.questions[0].id
    tools.approve_answer(user, batch.id, question_id)
    before = batches.edited_by(batch.id).get(question_id)

    async def refuses(answered, instruction, language=None, **kwargs):
        return answered

    monkeypatch.setattr(tools.rewrite, "rewrite", refuses)
    outcome = await tools.revise(user, batch.id, "Shorter.")

    assert outcome.answered == 0 and outcome.failed == outcome.attempted
    assert batches.edited_by(batch.id).get(question_id) == before


async def test_a_reworded_answer_approved_as_it_stands_teaches_the_memory_nothing(
    user, batch, drafted, reworded, memory_index
):
    choose(user.email, refer_to="T2")
    await tools.answer(user, batch.id)

    remembered = tools.approve_answer(user, batch.id, batch.form.questions[0].id)

    assert remembered == ""
    assert answer_memory.count() == 0


# --- the default length -------------------------------------------------------


def test_a_questionnaire_opens_at_the_length_its_opener_prefers(user, tmp_path):
    preferences.save(user.email, default_length="brief")
    opened = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))
    assert opened.detail == "brief"


async def test_answers_to_a_brief_questionnaire_arrive_with_their_brief_form(user, tmp_path, drafted, monkeypatch):
    """They used to get one only at the moment the file was switched to brief,
    so anything answered afterwards was written at full length under a "Brief"
    label."""
    preferences.save(user.email, default_length="brief")
    opened = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))

    async def shorten(answered):
        return "Yes."

    monkeypatch.setattr(tools.rewrite, "shorten", shorten)
    await tools.answer(user, opened.id)

    assert all(a.brief == "Yes." for a in batches.answers(opened.id).values())


# --- skills over a questionnaire ------------------------------------------------


async def test_a_skill_rewords_with_its_own_instruction(user, batch, drafted, reworded):
    await tools.answer(user, batch.id)
    skill = preferences.add_skill(user.email, "Zain format", "One sentence, verdict first.")

    used, outcome = await tools.apply_skill(user, batch.id, skill.skill_id)

    assert used.name == "Zain format"
    assert set(reworded["instructions"]) == {"One sentence, verdict first."}
    assert reworded["notes"][0] == "Reworded with the skill “Zain format”."
    assert outcome.answered == len(batch.form.questions)
    [event] = [e for e in events.for_subject(batches.SUBJECT, batch.id) if e.kind == events.SKILL_APPLIED]
    assert event.payload["skill"] == "Zain format"


async def test_a_built_in_skill_is_applied_the_same_way(user, batch, drafted, reworded):
    await tools.answer(user, batch.id)
    summary = next(s for s in preferences.BUILTIN_SKILLS if s.name == "Executive summary")

    used, outcome = await tools.apply_skill(user, batch.id, summary.skill_id)

    assert used.builtin and outcome.answered == len(batch.form.questions)
    assert set(reworded["instructions"]) == {summary.instruction}


async def test_a_skill_that_is_not_yours_cannot_be_applied(user, batch, drafted, reworded):
    theirs = preferences.add_skill(BOB, "Zain format", "One sentence.")
    await tools.answer(user, batch.id)

    with pytest.raises(tools.ToolError, match="no skill like that"):
        await tools.apply_skill(user, batch.id, theirs.skill_id)
    assert reworded["instructions"] == []


# --- the API --------------------------------------------------------------------


@pytest.fixture
def team():
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)
    identity.add_user(BOB)


def as_person(email: str) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": email, "code": CODE}).status_code == 200
    return client


def test_the_page_exists():
    body = TestClient(app).get("/preferences").text
    assert "<title>Preferences" in body and 'id="builtinSkills"' in body and 'id="asks"' in body


def test_preferences_through_the_api():
    client = TestClient(app)
    first = client.get("/api/preferences").json()
    assert first["preferences"]["tone"] == "as_drafted" and first["instruction"] == ""
    assert first["recommended"]["verdict_first"] is True and first["recommended"]["refer_to"]

    body = client.put("/api/preferences", json={"refer_to": "T2", "default_length": "brief"}).json()

    assert body["preferences"]["refer_to"] == "T2" and body["preferences"]["default_length"] == "brief"
    assert body["instruction"] == preferences.REFER_TO.format(name="T2")
    assert client.put("/api/preferences", json={"tone": "sarcastic"}).status_code == 422
    assert client.put("/api/preferences", json={"refer_to": 'the "company"'}).status_code == 400


def test_composing_shows_the_instruction_without_saving_it():
    client = TestClient(app)
    body = client.post("/api/preferences/compose", json={"verdict_first": True, "tone": "plain"}).json()

    assert body["instruction"] == "\n".join([preferences.VERDICT_FIRST, preferences.PLAIN])
    assert client.get("/api/preferences").json()["instruction"] == "", "composing is not saving"


def test_skills_through_the_api():
    client = TestClient(app)
    listed = client.get("/api/preferences").json()["skills"]
    assert {s["name"] for s in listed if s["builtin"]} == BUILTIN_NAMES

    added = client.post("/api/skills", json={
        "name": "Zain format", "description": "Zain's forms", "instruction": "One sentence.",
    }).json()
    assert added["builtin"] is False
    assert client.post("/api/skills", json={"name": "zain format", "instruction": "Again."}).status_code == 400

    edited = client.patch(f"/api/skills/{added['skill_id']}", json={"instruction": "Two sentences."})
    assert edited.json()["instruction"] == "Two sentences."

    assert client.delete(f"/api/skills/{added['skill_id']}").status_code == 200
    assert client.delete(f"/api/skills/{added['skill_id']}").status_code == 404
    assert client.patch(f"/api/skills/{added['skill_id']}", json={"name": "x"}).status_code == 404


def test_built_in_skills_through_the_api():
    client = TestClient(app)
    builtin = preferences.BUILTIN_SKILLS[0].skill_id

    assert client.patch(f"/api/skills/{builtin}", json={"name": "Mine"}).status_code == 400
    assert client.delete(f"/api/skills/{builtin}").status_code == 400

    copy = client.post(f"/api/skills/{builtin}/copy").json()
    assert copy["name"].endswith("(my copy)") and copy["builtin"] is False
    assert client.post("/api/skills/skill-nothing/copy").status_code == 404


def test_nobody_sees_anybody_elses_skills_or_preferences(team):
    alice, bob = as_person(ALICE), as_person(BOB)
    alice.put("/api/preferences", json={"refer_to": "T2"})
    skill = alice.post("/api/skills", json={"name": "Zain format", "instruction": "One sentence."}).json()

    theirs = bob.get("/api/preferences").json()
    assert theirs["preferences"]["refer_to"] == ""
    assert [s["name"] for s in theirs["skills"] if not s["builtin"]] == []
    assert bob.patch(f"/api/skills/{skill['skill_id']}", json={"name": "Mine now"}).status_code == 404
    assert bob.delete(f"/api/skills/{skill['skill_id']}").status_code == 404
    assert bob.post(f"/api/skills/{skill['skill_id']}/copy").status_code == 404
    assert [s["name"] for s in alice.get("/api/preferences").json()["skills"] if not s["builtin"]] == ["Zain format"]


def test_preferences_need_a_session(team):
    stranger = TestClient(app)
    assert stranger.get("/api/preferences").status_code == 401
    assert stranger.put("/api/preferences", json={"tone": "formal"}).status_code == 401
    assert stranger.post("/api/preferences/compose", json={}).status_code == 401
    assert stranger.post("/api/skills", json={"name": "x", "instruction": "y"}).status_code == 401
    assert stranger.post("/api/preferences/try", json={
        "instruction": "x", "question": "q", "answer": "a",
    }).status_code == 401


def test_trying_an_instruction_stores_nothing(reworded):
    client = TestClient(app)
    body = client.post("/api/preferences/try", json={
        "instruction": preferences.PLAIN, "question": "Is data encrypted?", "answer": "Yes, with AES-256.",
    }).json()

    assert body["before"] == "Yes, with AES-256."
    assert body["after"] == "STYLED: Yes, with AES-256."
    assert body["changed"] is True and body["failed"] is False
    assert reworded["instructions"] == [preferences.PLAIN]
    assert client.get("/api/preferences").json()["instruction"] == "", "trying is not saving"


def test_applying_a_skill_and_putting_a_draft_back_through_the_api(tmp_path, drafted, reworded):
    client = TestClient(app)
    opened = client.post("/api/forms", files={"file": (
        "vendor.xlsx", shapes.simple(tmp_path / "vendor.xlsx").read_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )}).json()
    client.put("/api/preferences", json={"refer_to": "T2"})
    client.post(f"/api/forms/{opened['id']}/answer", json={})
    skill = preferences.BUILTIN_SKILLS[0]

    applied = client.post(f"/api/forms/{opened['id']}/skills/{skill.skill_id}", json={}).json()
    assert applied["skill"]["name"] == skill.name
    assert applied["answered"] == len(opened["questions"])

    first = applied["batch"]["questions"][0]
    assert first["answered"]["drafted"], "the draft survives a skill applied on top"

    restored = client.post(f"/api/forms/{opened['id']}/answers/draft", json={
        "question_id": first["id"],
    }).json()
    assert restored["questions"][0]["answer"].startswith("Yes. The organisation")


# --- the assistant ---------------------------------------------------------------


@pytest.fixture
def kit(user, tmp_path):
    path = shapes.simple(tmp_path / "vendor.xlsx")
    state: dict = {"batch_id": "", "pending_upload": str(path), "steps": [], "refreshed": False}
    tool = {t.__name__: t for t in assistant._tools(user, state)}
    tool["open_questionnaire"]("")
    return tool, state


def test_the_assistant_can_list_and_apply_skills_but_not_make_them(kit):
    tool, _state = kit
    assert {"list_skills", "apply_skill"} <= set(tool)
    assert not any(name in tool for name in ("add_skill", "save_skill", "set_style", "save_preferences"))


def test_the_assistant_is_told_what_each_kind_is_for():
    assert "apply_skill" in assistant.SYSTEM
    assert "never pass it to `reword_answers`" in assistant.SYSTEM
    assert "PREFERENCES are how they want every answer to read" in assistant.SYSTEM
    assert all(name in assistant.SYSTEM for name in BUILTIN_NAMES)


def test_listing_skills_separates_built_in_from_theirs_and_hides_instructions(kit, user):
    tool, _state = kit
    listed = tool["list_skills"]()
    assert "Built in:" in listed and "- Executive summary:" in listed
    assert "have not written any of their own" in listed

    preferences.add_skill(user.email, "Zain format", "SECRET-INSTRUCTION", "Zain's forms")
    listed = tool["list_skills"]()

    assert "Their own:\n- Zain format: Zain's forms" in listed
    assert "SECRET-INSTRUCTION" not in listed


async def test_applying_a_skill_from_the_conversation(kit, user, drafted, reworded):
    tool, state = kit
    await tool["answer_questions"]()
    preferences.add_skill(user.email, "Zain format", "One sentence, verdict first.")

    said = await tool["apply_skill"]("zain")

    assert "Reworded 4 of 4 with the skill 'Zain format'" in said
    assert "One sentence, verdict first." in reworded["instructions"]
    assert state["refreshed"] is True


async def test_an_unknown_or_ambiguous_skill_is_asked_about_not_guessed(kit, user, drafted, reworded):
    tool, _state = kit
    await tool["answer_questions"]()
    preferences.add_skill(user.email, "Auditor notes", "Short.")

    unknown = await tool["apply_skill"]("Zain format")
    ambiguous = await tool["apply_skill"]("auditor")

    assert "no skill called 'Zain format'" in unknown and "'Executive summary'" in unknown
    assert "More than one skill matches" in ambiguous
    assert reworded["instructions"] == []


async def test_answering_in_the_conversation_reports_the_preferences(kit, user, drafted, reworded):
    tool, _state = kit
    choose(user.email, refer_to="T2")

    said = await tool["answer_questions"]()

    assert "reworded to your preferences" in said


async def test_a_question_asked_in_conversation_gets_preferences_or_the_named_skill(kit, user, drafted, reworded):
    tool, _state = kit
    instruction = choose(user.email, refer_to="T2")
    preferences.add_skill(user.email, "Zain format", "One sentence.")

    styled = await tool["answer_directly"]("Do you review access rights?")
    skilled = await tool["answer_directly"]("Do you review access rights?", skill="zain")

    assert "STYLED:" in styled and "reworded to your preferences" in styled
    assert reworded["instructions"] == [instruction, "One sentence."]
    assert "STYLED:" in skilled and "your preferences" not in skilled
