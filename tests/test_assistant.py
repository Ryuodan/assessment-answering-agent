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
    assert "0 answered here, 4 still blank" in tool["describe_form"]()


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


@pytest.mark.asyncio
async def test_a_set_aside_answer_is_not_said_to_be_going_into_the_file(kit, answers_yes):
    """The answers panel draws what `inspect` says. It said "will be written" of
    an answer set aside, so the card beside the assistant never changed."""
    tool, state = kit
    user = identity.local_user()
    tool["open_questionnaire"]("")
    await tool["answer_questions"]()
    before = tools.inspect(user, state["batch_id"])
    first = before["questions"][0]
    going_in = sum(1 for q in before["questions"] if q["will_be_written"])
    assert first["will_be_written"], "the premise: it was going in"

    tool["set_aside"](position="1")
    after = tools.inspect(user, state["batch_id"])

    assert after["questions"][0]["will_be_written"] is False
    assert after["questions"][0]["held_back_because"] == "", "set aside is not held back"
    assert after["counts"]["set_aside"] == 1
    assert after["counts"]["held_back"] == before["counts"]["held_back"]
    assert sum(1 for q in after["questions"] if q["will_be_written"]) == going_in - 1


@pytest.mark.asyncio
async def test_a_set_aside_answer_is_not_flagged_and_the_fill_report_counts_it_out(kit, answers_yes):
    tool, state = kit
    user = identity.local_user()
    tool["open_questionnaire"]("")
    await tool["answer_questions"]()
    going_in = sum(1 for q in tools.inspect(user, state["batch_id"])["questions"] if q["will_be_written"])

    tool["set_aside"](position="1")

    assert "set aside" in tool["read_answers"](position="1")
    assert "#1 " not in tool["read_answers"](only="flagged")
    said = tool["propose_fill"]()
    assert f"{going_in - 1} answer(s) would be written" in said
    assert "the 1 set-aside question(s) are not written" in said


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
async def test_the_note_about_the_upload_is_not_something_anybody_said(
    user, tmp_path, scripted, answers_yes
):
    """The agent is told a file arrived, in the message it re-reads. That note
    is plumbing, and it was going into the conversation's name -- so a history
    read as a list of "[A file has been uploaded to this conversation: HR…"
    rather than a list of what was asked."""
    scripted([("open_questionnaire", {"file_name": ""})])
    conversation = assistant.start(user, "")
    path = shapes.status_and_comment(tmp_path / "HR.xlsx")

    await assistant.say(user, conversation, "Read this file.", upload=path)

    saved = conversations.load(conversation.id, team_id=user.team_id)
    assert saved.title == "Read this file."
    # And it is still in the history, because that is what the agent re-reads.
    asked = [m for m in saved.messages if isinstance(m, HumanMessage)]
    assert assistant.UPLOAD_NOTE in str(asked[0].content)
    assert assistant.spoken(str(asked[0].content)) == "Read this file."


@pytest.mark.asyncio
async def test_a_turn_says_what_it_is_doing_while_it_does_it(user, tmp_path, scripted, answers_yes):
    """A person watching a turn has the label and nothing else. "Working" for
    ninety seconds is indistinguishable from a page that has frozen, so every
    tool announces itself as it starts."""
    from src import progress

    seen = []
    real = progress.note

    def watched(run_id, stage):
        seen.append((run_id, stage))
        real(run_id, stage)

    scripted([("open_questionnaire", {"file_name": ""}), ("search_policies", {"query": "mfa"})])
    conversation = assistant.start(user, "")
    path = shapes.status_and_comment(tmp_path / "HR.xlsx")

    original, progress.note = progress.note, watched
    try:
        await assistant.say(user, conversation, "Read this", upload=path, run_id="watched")
    finally:
        progress.note = original

    assert [stage for run, stage in seen if run == "watched"] == [
        "Reading the file…", "Searching the policies…",
    ]


@pytest.mark.asyncio
async def test_a_turn_is_watchable_from_the_moment_it_starts(user, scripted):
    """Registered before the first model call. The turn that uploads a file is
    the slowest one and has no batch to be named after, which is why the run id
    comes from the caller."""
    from src import progress

    scripted([])
    conversation = assistant.start(user, "")
    await assistant.say(user, conversation, "hello", run_id="early")
    assert progress.snapshot("early") is not None


@pytest.mark.asyncio
async def test_a_turn_without_a_run_id_still_works(user, scripted):
    """Nothing is watching. That is a missing progress bar, never a failure."""
    scripted([])
    conversation = assistant.start(user, "")
    turn = await assistant.say(user, conversation, "hello")
    assert turn.reply == "Done."


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
    assert "[blank    ]" in said


@pytest.mark.asyncio
async def test_listing_shows_which_are_already_answered(kit, answers_yes):
    tool, _state = kit
    tool["open_questionnaire"]("")
    await tool["answer_questions"](matching="training")

    said = tool["list_questions"]()
    assert said.count("[answered]") == 1
    assert said.count("[blank    ]") == 3


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


# --- a file that arrives already filled in ---------------------------------
#
# Last year's submission, or a colleague's draft. Handed one and asked what was
# in it, the assistant said it had no answers -- the count only ever looked at
# what this system had written, and the file's own answers live on the targets
# as the text already in the cell.


@pytest.fixture
def filled(user, tmp_path):
    path = shapes.already_answered(tmp_path / "Last year.xlsx")
    state: dict = {"batch_id": "", "pending_upload": str(path), "steps": [], "refreshed": False}
    tool = {t.__name__: t for t in assistant._tools(user, state)}
    tool["open_questionnaire"]("")
    return tool, state


def test_answers_the_file_arrived_with_are_counted(filled):
    tool, _state = filled
    said = tool["describe_form"]()
    assert "2 question(s) arrived with an answer already written" in said
    assert "0 answered here" in said, "they are the file's answers, not ours"


def test_still_blank_does_not_count_what_the_file_answered_or_what_was_set_aside(filled):
    """Blank was the question count minus our answers, so the file's own answers
    and the rows set aside were all "still blank" -- and on this file the
    assistant was told 4 were left beside a line saying 2 came answered."""
    tool, state = filled
    assert "0 answered here, 2 still blank" in tool["describe_form"]()

    blank = [q["id"] for q in tools.inspect(identity.local_user(), state["batch_id"])["questions"]
             if not q["existing"]]
    tool["set_aside"](blank[0])
    assert "0 answered here, 1 still blank" in tool["describe_form"]()


def test_a_question_answered_only_by_a_status_still_counts(filled, user, state=None):
    """"Partially Compliant" with no comment beside it is an answer."""
    tool, batch_state = filled
    report = tools.inspect(user, batch_state["batch_id"])
    assert report["counts"]["already_in_file"] == 2
    assert report["questions"][1]["existing"] == "Partially Compliant"


def test_listing_marks_which_ones_came_with_an_answer(filled):
    tool, _state = filled
    said = tool["list_questions"]()
    assert said.count("[in file  ]") == 2
    assert said.count("[blank    ]") == 2


def test_reading_what_the_file_said_quotes_it(filled):
    tool, _state = filled
    said = tool["read_existing"](matching="human resources")
    assert "the file says: Yes. The HR process is documented" in said


def test_reading_a_question_that_arrived_blank_says_so(filled):
    tool, _state = filled
    assert "None of those arrived with an answer" in tool["read_existing"](matching="background")


@pytest.mark.asyncio
async def test_finishing_the_rest_skips_what_the_file_already_answered(filled, answers_yes):
    """The point of counting them: "finish it" should cost two answers, not
    four, and must not overwrite words somebody already reviewed."""
    tool, batch_state = filled
    said = await tool["answer_questions"](unanswered_only=True)
    assert "Answered 2 of 2" in said

    report = tools.inspect(identity.local_user(), batch_state["batch_id"])
    assert report["questions"][0]["answer"] == "", "an answer already in the file was overwritten"
    assert report["questions"][0]["existing"].startswith("Yes. The HR process")


@pytest.mark.asyncio
async def test_answering_the_whole_file_leaves_its_own_answers_alone(filled, answers_yes):
    """Not a scope the model chose well -- the broadest one there is. The two
    the file arrived with survive it, and the reply says they were left."""
    tool, batch_state = filled
    said = await tool["answer_questions"]()

    assert "2 question(s) in that scope already had an answer" in said
    assert "Answered 2 of 2" in said

    report = tools.inspect(identity.local_user(), batch_state["batch_id"])
    assert report["questions"][0]["answer"] == ""
    assert report["questions"][0]["existing"].startswith("Yes. The HR process")


@pytest.mark.asyncio
async def test_a_scope_of_only_answered_questions_is_not_reported_as_a_dead_end(
    filled, answers_yes
):
    """"Nothing matched, call describe_form" would send it round the houses
    looking for a sheet name that was never the problem."""
    tool, batch_state = filled
    report = tools.inspect(identity.local_user(), batch_state["batch_id"])
    already = report["questions"][0]["id"]

    said = await tool["answer_questions"](ids=already)
    assert "already had an answer" in said and "Nothing matched" not in said


@pytest.mark.asyncio
async def test_replacing_an_answer_takes_the_flag(filled, answers_yes):
    tool, batch_state = filled
    report = tools.inspect(identity.local_user(), batch_state["batch_id"])
    already = report["questions"][0]["id"]

    said = await tool["answer_questions"](ids=already, replace_existing=True)
    assert "Answered 1 of 1" in said

    after = tools.inspect(identity.local_user(), batch_state["batch_id"])
    assert after["questions"][0]["answer"].startswith("Yes, this is documented")


def test_replacing_is_said_out_loud_in_the_steps(filled):
    """The steps are what the interface shows the person. Overwriting an answer
    the security team wrote is not something to do without leaving a mark."""
    import asyncio
    tool, batch_state = filled
    report = tools.inspect(identity.local_user(), batch_state["batch_id"])
    asyncio.run(tool["answer_questions"](ids=report["questions"][0]["id"], replace_existing=True))
    assert any("replacing what is there" in step for step in batch_state["steps"])


# --- answering a question with no file at all -------------------------------


@pytest.fixture
def answers_with_evidence(monkeypatch):
    """The pipeline, standing in, with a clause behind each answer."""
    from src.models import Evidence, SourceType

    async def fake(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=question,
                answer=f"Yes, backups are encrypted. [{question.text[:12]}]",
                confidence=0.9, needs_review=False,
                evidence=[Evidence(
                    source_type=SourceType.GUIDELINE,
                    source_name="T2 - Information Security Policy.pdf",
                    snippet="Backups shall be encrypted at rest using AES-256.",
                    doc_id="T2-ISP", clause="9.4.1",
                )],
            )
            for question in questions
        ]

    monkeypatch.setattr(tools.service, "answer_questions", fake)


@pytest.mark.asyncio
async def test_a_question_can_be_answered_with_no_questionnaire_open(
    kit, answers_with_evidence
):
    """Somebody asks in passing. Making them upload a spreadsheet to find out
    what the policies commit the organisation to would be absurd."""
    tool, state = kit
    said = await tool["answer_directly"]("Do we encrypt our backups?")

    assert "Yes, backups are encrypted" in said
    assert "relay word for word" in said, "a drafted answer is not a note to summarise"
    assert not state["batch_id"], "it answered without opening anything"


@pytest.mark.asyncio
async def test_answering_directly_puts_its_clauses_under_the_reply(
    kit, answers_with_evidence
):
    tool, state = kit
    await tool["answer_directly"]("Do we encrypt our backups?")
    [source] = state["sources"]
    assert "T2-ISP" in source["locator"] and "9.4.1" in source["locator"]
    assert "AES-256" in source["snippet"]


@pytest.mark.asyncio
async def test_answering_directly_takes_a_few_questions_at_once(kit, answers_with_evidence):
    tool, _state = kit
    said = await tool["answer_directly"]("Do we encrypt backups?\nDo we log access?")
    assert said.count("relay word for word") == 2


@pytest.mark.asyncio
async def test_a_list_too_long_to_ask_this_way_is_refused(kit, answers_with_evidence):
    """This path stores nothing -- no cells, no cards, nothing to come back to.
    A list that long is a questionnaire and belongs in a file."""
    tool, _state = kit
    said = await tool["answer_directly"]("\n".join(f"Question {n}?" for n in range(9)))
    assert "at most 5" in said


@pytest.mark.asyncio
async def test_answering_directly_leaves_the_open_questionnaire_alone(
    kit, answers_with_evidence
):
    tool, state = kit
    tool["open_questionnaire"]("")
    await tool["answer_directly"]("Do we encrypt our backups?")

    report = tools.inspect(identity.local_user(), state["batch_id"])
    assert report["counts"]["answered"] == 0, "a question asked aloud is not a row in the file"


def test_what_a_turn_did_is_stored_with_its_reply(user, scripted, tmp_path):
    """The steps and the clauses it quoted used to be sent with the reply and
    then lost: reopening the conversation redrew the words and none of the
    evidence under them. A claim about what the policies say is worth what the
    clause behind it is worth, and that has to survive a reload."""
    scripted([("describe_form", {})])
    conversation = assistant.start(user, "")

    import asyncio
    asyncio.run(assistant.say(user, conversation, "What is in the file?"))

    saved = conversations.load(conversation.id, team_id=user.team_id)
    reply = [m for m in saved.messages
             if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)][-1]
    assert reply.additional_kwargs[assistant.UI_KEY]["steps"] == ["describe_form"]


@pytest.mark.asyncio
async def test_the_transcript_hands_back_what_each_turn_did(user, scripted, tmp_path):
    from fastapi.testclient import TestClient

    from src.api import app

    scripted([("describe_form", {})])
    conversation = assistant.start(user, "")
    await assistant.say(user, conversation, "What is in the file?")

    with TestClient(app) as client:
        body = client.get(f"/api/chat/{conversation.id}").json()

    assistant_turns = [m for m in body["messages"] if m["role"] == "assistant"]
    assert assistant_turns and assistant_turns[-1]["steps"] == ["describe_form"]
    assert "sources" in assistant_turns[-1]


# --- leaving an answer blank on purpose ------------------------------------
#
# A question can be wrong for this organisation, or answered better by silence.
# Deleting the answer got you back to "not answered yet", which is the state a
# person is trying to leave.


@pytest.mark.asyncio
async def test_a_blanked_answer_is_not_the_same_as_an_unanswered_one(kit, answers_yes, user):
    tool, state = kit
    tool["open_questionnaire"]("")
    await tool["answer_questions"]()
    first = tools.inspect(user, state["batch_id"])["questions"][0]["id"]

    tools.blank_answer(user, state["batch_id"], first)
    question = tools.inspect(user, state["batch_id"])["questions"][0]

    assert question["blanked"] is True
    assert question["answer"] == ""


@pytest.mark.asyncio
async def test_a_blanked_answer_clears_the_cell_rather_than_skipping_it(kit, answers_yes, user):
    """The file may already hold last year's answer. Skipping the question
    would leave those words in place, which is the opposite of what was asked."""
    from src.forms.xlsx_package import Workbook

    tool, state = kit
    tool["open_questionnaire"]("")
    await tool["answer_questions"]()
    first = tools.inspect(user, state["batch_id"])["questions"][0]["id"]
    tools.blank_answer(user, state["batch_id"], first)

    filled = tools.fill(user, state["batch_id"])
    with Workbook(filled.path) as workbook:
        sheet = workbook["Human Resources"]
        assert sheet.value(2, "D") == "", "the blanked answer left something behind"
        assert sheet.value(3, "D").startswith("Yes,"), "the others were not written"


@pytest.mark.asyncio
async def test_a_blanked_answer_is_not_counted_as_work_outstanding(kit, answers_yes, user):
    """It is a decision, so `unanswered_only` must not offer it again."""
    tool, state = kit
    tool["open_questionnaire"]("")
    await tool["answer_questions"](matching="training")
    first = tools.inspect(user, state["batch_id"])["questions"][0]["id"]
    tools.blank_answer(user, state["batch_id"], first)

    said = await tool["answer_questions"](unanswered_only=True)
    assert "Answered 2 of 2" in said, "a question left blank on purpose was answered again"


def test_blanking_a_question_that_does_not_exist_is_refused(kit, user):
    tool, state = kit
    tool["open_questionnaire"]("")
    with pytest.raises(tools.ToolError):
        tools.blank_answer(user, state["batch_id"], "Nowhere!99")


