"""The assistant: its tools, its guardrails, and what a turn leaves behind.

The model is stubbed. What is tested here is the machinery a model's choices
land on -- that a sentence turns into the right scope, that an operation it is
not allowed to perform is not merely discouraged but absent, that a turn which
fails part way through still records what it did, and that the conversation it
saves is one it can resume from. Whether a language model picks the right tool
is a different question, measured against the real model by
`scripts/eval_assistant.py`.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src import batches, conversations, events, identity, tools
from src.agents import assistant
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes


@pytest.fixture
def user():
    return identity.local_user()


@pytest.fixture
def answers_yes(monkeypatch):
    """Stand in for the answering pipeline: every question gets a confident yes."""
    seen: dict = {}

    async def fake(questions, language=None, run_id=None, **extra):
        seen["questions"] = questions
        return [
            AnsweredQuestion(
                question=question,
                answer=f"Yes, this is documented and approved. [{question.id}]",
                confidence=0.9,
                needs_review=False,
                citations=["T2 - Information Security Policy.pdf §3.1"],
            )
            for question in questions
        ]

    monkeypatch.setattr(tools.service, "answer_questions", fake)
    return seen


@pytest.fixture
def kit(user, tmp_path):
    """The tools, the state they share, and an opened questionnaire."""
    path = shapes.status_and_comment(tmp_path / "HR Assessment.xlsx")
    state: dict = {"batch_id": "", "pending_upload": str(path), "steps": [], "refreshed": False}
    tool = {t.__name__: t for t in assistant._tools(user, state)}
    return tool, state


# --- the operations it is not allowed to perform ---------------------------
#
# Absent, not discouraged. A prompt that says "do not fill the file" is a
# request; a missing tool is a guarantee, and these three were decided long
# before there was an agent to decide them for.


def test_it_has_no_way_to_write_a_file(kit):
    """`fill` always stopped for confirmation. An agent that could write
    silently would be a worse tool than the one it replaced."""
    tool, _state = kit
    assert "fill" not in tool
    assert {name for name in tool if "fill" in name} == {"propose_fill"}


def test_it_has_no_way_to_change_the_knowledge_base(kit):
    """Indexing and removing policy documents is the corpus every answer is
    grounded in. It belongs behind a panel with a list and a delete button."""
    tool, _state = kit
    assert not [name for name in tool if any(
        word in name for word in ("index", "upload_document", "remove", "delete", "guideline")
    )]


def test_it_has_no_way_to_record_feedback(kit):
    """Feedback belongs on the answer card, where the thing being judged is
    visible."""
    tool, _state = kit
    assert not [name for name in tool if "feedback" in name or "rate" in name]


def test_proposing_a_fill_writes_nothing(kit, answers_yes, tmp_path):
    import asyncio

    tool, state = kit
    tool["open_questionnaire"]("")
    asyncio.run(tool["answer_questions"]())

    said = tool["propose_fill"]()
    assert "have not written anything" in said
    batch = batches.load(state["batch_id"])
    assert not tools._filled_path(batch).exists(), "a file was written by a proposal"


def test_proposing_a_fill_with_nothing_answered_says_so(kit):
    tool, _state = kit
    tool["open_questionnaire"]("")
    assert "would write nothing" in tool["propose_fill"]()


# --- turning a sentence into a scope ---------------------------------------


@pytest.mark.asyncio
async def test_a_section_narrows_what_is_answered(kit, answers_yes):
    tool, state = kit
    tool["open_questionnaire"]("")
    said = await tool["answer_questions"](matching="training")

    assert "Answered 1 of 1" in said
    report = tools.inspect(identity.local_user(), state["batch_id"])
    answered = [q for q in report["questions"] if q.get("answer")]
    assert len(answered) == 1
    assert "training" in answered[0]["text"].lower()


@pytest.mark.asyncio
async def test_finishing_the_rest_does_not_answer_anything_twice(kit, answers_yes):
    """The most expensive mistake available: answering is minutes and money,
    and "finish it" said twice should cost nothing the second time."""
    tool, _state = kit
    tool["open_questionnaire"]("")
    await tool["answer_questions"](matching="training")

    said = await tool["answer_questions"](unanswered_only=True)
    assert "Answered 3 of 3" in said

    again = await tool["answer_questions"](unanswered_only=True)
    assert "Nothing matched" in again


@pytest.mark.asyncio
async def test_a_scope_that_matches_nothing_says_where_to_look(kit, answers_yes):
    """A dead end has to point somewhere, or the agent tries the same guess
    again with a different spelling."""
    tool, _state = kit
    tool["open_questionnaire"]("")
    said = await tool["answer_questions"](part="Quantum Cryptography")
    assert "Nothing matched" in said
    assert "describe_form" in said


@pytest.mark.asyncio
async def test_ids_arrive_as_a_list_however_they_are_punctuated(kit, answers_yes):
    tool, state = kit
    tool["open_questionnaire"]("")
    report = tools.inspect(identity.local_user(), state["batch_id"])
    first, second = report["questions"][0]["id"], report["questions"][1]["id"]

    said = await tool["answer_questions"](ids=f"{first}; {second} ")
    assert "Answered 2 of 2" in said


# --- rewording is not answering --------------------------------------------


@pytest.mark.asyncio
async def test_rewording_a_blank_question_is_refused_rather_than_answered(kit, answers_yes):
    """Rewording a blank question is answering it, and answering costs money
    the person did not ask to spend."""
    tool, _state = kit
    tool["open_questionnaire"]("")
    said = await tool["reword_answers"]("make it shorter")
    assert "nothing to reword" in said
    assert "questions" not in answers_yes, "the answering pipeline should not have run"


@pytest.mark.asyncio
async def test_rewording_runs_over_answers_that_exist(kit, answers_yes, monkeypatch):
    tool, _state = kit
    tool["open_questionnaire"]("")
    await tool["answer_questions"]()

    async def fake_rewrite(answered, instruction, language=None):
        revised = answered.model_copy(deep=True)
        revised.answer = "Shorter."
        return revised

    monkeypatch.setattr(tools.rewrite, "rewrite", fake_rewrite)
    said = await tool["reword_answers"]("keep each to one sentence")
    assert "Reworded 4 of 4" in said


# --- knowing what is in the file -------------------------------------------


def test_describing_a_form_names_its_sheets_and_sections(kit):
    """The sections matter most: "the governance ones" is how people name a
    subset, and an agent that has to guess a sheet name guesses wrongly."""
    tool, _state = kit
    tool["open_questionnaire"]("")
    said = tool["describe_form"]()
    assert "HR Assessment.xlsx" in said
    assert "Human Resources (4)" in said
    assert "Not used: Score (hidden)" in said


def test_describing_a_form_counts_the_blanks_rather_than_implying_them(kit):
    """Asked in Arabic how many were left, the assistant read "1 answered" off
    a four-question file and replied "one remaining". The arithmetic was the
    only thing between it and a right answer, so it should not have had to do
    it."""
    tool, _state = kit
    tool["open_questionnaire"]("")
    assert "0 answered, 4 still blank" in tool["describe_form"]()


def test_every_tool_says_so_when_no_questionnaire_is_open(kit):
    import asyncio

    tool, state = kit
    state["pending_upload"] = ""
    assert "No file has been uploaded" in tool["open_questionnaire"]("")
    assert "No questionnaire is open" in tool["describe_form"]()
    assert "No questionnaire is open" in tool["propose_fill"]()
    assert "No questionnaire is open" in asyncio.run(tool["answer_questions"]())
    assert "No questionnaire is open" in asyncio.run(tool["reword_answers"]("shorter"))
    assert "No questionnaire is open" in tool["write_one_answer"]("q1", "text")
    assert "No questionnaire is open" in tool["set_aside"]("q1")


def test_a_file_that_cannot_be_read_is_a_sentence_not_a_crash(user, tmp_path):
    """These arrive from other companies over a public endpoint."""
    broken = tmp_path / "not-a-workbook.xlsx"
    broken.write_bytes(b"this is not a zip file at all")
    state = {"batch_id": "", "pending_upload": str(broken), "steps": [], "refreshed": False}
    tool = {t.__name__: t for t in assistant._tools(user, state)}

    said = tool["open_questionnaire"]("")
    assert "could not be read" in said
    assert not state["batch_id"]


# --- setting questions aside -----------------------------------------------


def test_setting_aside_keeps_a_question_out_of_the_file(kit):
    tool, state = kit
    tool["open_questionnaire"]("")
    report = tools.inspect(identity.local_user(), state["batch_id"])
    first = report["questions"][0]["id"]

    said = tool["set_aside"](first)
    assert "1 question(s) set aside" in said
    assert tools.inspect(identity.local_user(), state["batch_id"])["questions"][0]["skip"] is True

    tool["set_aside"](first, include=True)
    assert tools.inspect(identity.local_user(), state["batch_id"])["questions"][0]["skip"] is False


def test_setting_aside_nothing_asks_which(kit):
    tool, _state = kit
    tool["open_questionnaire"]("")
    assert "Name the questions" in tool["set_aside"]("  ")


# --- what a turn leaves behind ---------------------------------------------


def _graph(script):
    """A stand-in for the agent: runs `script` against the tools, then replies."""

    class Fake:
        def __init__(self, tool_list):
            self.tools = {t.__name__: t for t in tool_list}

        async def astream(self, payload, config=None, stream_mode=None):
            messages = list(payload["messages"])
            for name, kwargs in script:
                result = self.tools[name](**kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                messages.append(AIMessage("", tool_calls=[
                    {"name": name, "args": kwargs, "id": name}
                ]))
                messages.append(ToolMessage(str(result), tool_call_id=name))
            messages.append(AIMessage("Done."))
            yield {"messages": messages}

    return Fake


@pytest.fixture
def scripted(monkeypatch):
    """Drive the assistant through a fixed sequence of tool calls."""

    def run(script):
        monkeypatch.setattr(assistant, "_agent", lambda tool_list: _graph(script)(tool_list))

    return run


@pytest.mark.asyncio
async def test_a_turn_saves_a_conversation_it_can_resume_from(user, tmp_path, scripted, answers_yes):
    """The stored history is what the agent re-reads, so it has to keep the
    tool calls. A tidy transcript would lose which tool returned what, which is
    exactly what a follow-up instruction depends on."""
    scripted([("open_questionnaire", {"file_name": ""}), ("answer_questions", {})])
    conversation = assistant.start(user, "")
    path = shapes.status_and_comment(tmp_path / "HR.xlsx")

    turn = await assistant.say(user, conversation, "Read this and answer it", upload=path)

    assert turn.reply == "Done."
    assert turn.batch_id and turn.refreshed
    saved = conversations.load(conversation.id, team_id=user.team_id)
    assert saved.batch_id == turn.batch_id
    assert any(isinstance(m, ToolMessage) for m in saved.messages), "tool results were dropped"
    assert any(isinstance(m, HumanMessage) for m in saved.messages)


@pytest.mark.asyncio
async def test_a_conversation_is_titled_from_what_was_first_asked(user, tmp_path, scripted):
    scripted([])
    conversation = assistant.start(user, "")
    await assistant.say(user, conversation, "Answer the governance questions please")
    assert conversations.load(conversation.id).title == "Answer the governance questions please"


@pytest.mark.asyncio
async def test_a_turn_that_fails_still_records_what_it_did(user, tmp_path, monkeypatch, answers_yes):
    """The tools it did call have already changed the batch. A history that
    does not mention them leaves the assistant contradicting the answers on
    screen beside it."""
    class Exploding:
        async def astream(self, payload, config=None, stream_mode=None):
            raise RuntimeError("the provider is down")
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(assistant, "_agent", lambda tool_list: Exploding())
    conversation = assistant.start(user, "")
    turn = await assistant.say(user, conversation, "Answer everything")

    assert turn.stopped_early
    assert "ran out of room" in turn.reply
    saved = conversations.load(conversation.id, team_id=user.team_id)
    assert [m.content for m in saved.messages if isinstance(m, HumanMessage)] == ["Answer everything"]


@pytest.mark.asyncio
async def test_a_turn_is_recorded_against_the_person_who_took_it(user, scripted):
    scripted([])
    conversation = assistant.start(user, "hello")
    await assistant.say(user, conversation, "hello")

    kinds = [e.kind for e in events.for_subject(conversations.SUBJECT, conversation.id)]
    assert events.ASSISTANT_STARTED in kinds
    assert events.ASSISTANT_TURN in kinds


@pytest.mark.asyncio
async def test_the_answer_panel_is_only_re_read_when_something_changed(user, scripted, tmp_path):
    """Re-reading a 183-question batch on every "thanks" is a real cost."""
    scripted([])
    conversation = assistant.start(user, "")
    turn = await assistant.say(user, conversation, "What can you do?")
    assert turn.refreshed is False


def test_the_answers_beside_a_chat_are_the_same_payload_the_other_page_draws(
    user, tmp_path, answers_yes
):
    """Two renderings of an answer card would drift, and the sources and the
    reviewer's reasoning are the part worth looking at."""
    conversation = assistant.start(user, "")
    assert assistant.answers_for(user, conversation) is None, "no file, no cards"

    batch = tools.open_form(user, shapes.status_and_comment(tmp_path / "HR.xlsx"))
    conversation.batch_id = batch.id
    conversations.save(conversation)

    beside = assistant.answers_for(user, conversation)
    assert beside == tools.inspect(user, batch.id)


def test_a_conversation_from_another_team_is_not_visible(user, tmp_path):
    """Everything else in this system is scoped to a team; a conversation names
    a customer's file and half its answers."""
    conversation = assistant.start(user, "hello")
    assert conversations.load(conversation.id, team_id="another-team") is None


# --- seeing the questions --------------------------------------------------
#
# Added because the eval found two failures that were both this: without a way
# to list questions the assistant cannot get an id, so `set_aside` was
# unusable, and it could not check a scope before spending money on it.


def test_listing_questions_gives_their_ids_and_state(kit):
    tool, _state = kit
    tool["open_questionnaire"]("")
    said = tool["list_questions"]()

    assert "4 question(s) matched all questions" in said
    assert "Human Resources!2" in said
    assert "[blank   ]" in said


@pytest.mark.asyncio
async def test_listing_shows_which_are_already_answered(kit, answers_yes):
    tool, _state = kit
    tool["open_questionnaire"]("")
    await tool["answer_questions"](matching="training")

    said = tool["list_questions"]()
    assert said.count("[answered]") == 1
    assert said.count("[blank   ]") == 3


def test_a_scope_matching_nothing_explains_that_it_is_not_a_query(kit):
    """The failure it was written for: the assistant passed
    `matching="training OR awareness"` as one literal string, matched nothing,
    and reported that the file had no training questions."""
    tool, _state = kit
    tool["open_questionnaire"]("")
    said = tool["list_questions"](matching="training OR awareness")

    assert "Nothing matched" in said
    assert "literal substring" in said
    assert "not a query" in said


def test_listing_is_bounded(kit, tmp_path, user):
    """A questionnaire runs to 183 questions and this goes into a prompt."""
    cells = {"A1": "#", "B1": "Question", "C1": "Answer"}
    for row in range(2, 120):
        cells[f"A{row}"] = f"{row - 1}.0"
        cells[f"B{row}"] = f"Is control number {row - 1} implemented and documented?"
    path = shapes.build(tmp_path / "long.xlsx", [shapes.SheetSpec("Controls", cells)])
    state = {"batch_id": "", "pending_upload": str(path), "steps": [], "refreshed": False}
    tool = {t.__name__: t for t in assistant._tools(user, state)}
    tool["open_questionnaire"]("")

    said = tool["list_questions"](limit=10)
    assert "and 108 more" in said
    assert len(said.splitlines()) == 12


def test_setting_aside_uses_an_id_that_listing_actually_returns(kit):
    """The two tools have to agree about what an id is, or the second is
    unusable however well the first is described."""
    tool, _state = kit
    tool["open_questionnaire"]("")
    listed = tool["list_questions"]()
    first = listed.splitlines()[1].strip().split("  ")[0]

    assert "1 question(s) set aside" in tool["set_aside"](first)
