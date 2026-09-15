"""A long conversation, and the questions people ask about the answers in it.

Two failures this file exists for. A conversation past about ten turns lost its
beginning: the model was shown the last sixty messages and that window was saved
back as though it were the whole conversation. And asked "what is the second
question answer?", the assistant could not read an answer back at all, so it
described the fill button instead.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src import batches, conversations, preferences, tools
from src.agents import assistant
from src.api import app
from tests import forms_fixtures as shapes
from tests.test_assistant import _graph, answers_yes, scripted, user  # noqa: F401


def _turn(n: int, *, tools_used: int = 2) -> list:
    messages = [HumanMessage(f"turn {n}")]
    for call in range(tools_used):
        call_id = f"{n}-{call}"
        messages.append(AIMessage("", tool_calls=[{"name": "list_questions", "args": {}, "id": call_id}]))
        messages.append(ToolMessage(f"result {call_id}", tool_call_id=call_id))
    messages.append(AIMessage(f"reply {n}"))
    return messages


# --- what the model is shown ------------------------------------------------------


def test_the_window_starts_at_a_person_and_never_cuts_a_turn():
    history = [message for n in range(40) for message in _turn(n)]

    window = assistant._window(history)

    assert isinstance(window[0], HumanMessage)
    asked = {m.tool_call_id for m in window if isinstance(m, ToolMessage)}
    called = {c["id"] for m in window if isinstance(m, AIMessage) for c in m.tool_calls}
    assert asked == called, "every result has its call, and every call its result"


def test_older_turns_are_shown_as_what_was_asked_and_said():
    history = [message for n in range(10) for message in _turn(n)]

    window = assistant._window(history)

    humans = [m.content for m in window if isinstance(m, HumanMessage)]
    assert humans == [f"turn {n}" for n in range(10)]
    full = assistant.TURNS_IN_FULL
    calls = [m for m in window if isinstance(m, AIMessage) and m.tool_calls]
    assert len(calls) == 2 * full, "only the most recent turns keep their tool calls"
    assert [m.content for m in window if assistant._said(m)][-1] == "reply 9"


def test_only_so_many_turns_are_shown():
    history = [message for n in range(60) for message in _turn(n, tools_used=0)]

    window = assistant._window(history)

    humans = [m.content for m in window if isinstance(m, HumanMessage)]
    assert len(humans) == assistant.TURNS_REMEMBERED
    assert humans[-1] == "turn 59"


def test_a_turn_that_stopped_part_way_does_not_poison_the_next():
    """A tool call with no result is a request the model API refuses, and the
    history is re-sent every turn."""
    broken = [
        HumanMessage("answer everything"),
        AIMessage("", tool_calls=[{"name": "answer_questions", "args": {}, "id": "lost"}]),
    ]
    history = _turn(0) + broken + _turn(2)

    window = assistant._window(history)

    assert not any(isinstance(m, AIMessage) and any(c["id"] == "lost" for c in m.tool_calls) for m in window)
    assert "answer everything" in [m.content for m in window if isinstance(m, HumanMessage)]


# --- what is kept -------------------------------------------------------------------


async def test_a_long_conversation_keeps_its_beginning(user, scripted, answers_yes):
    """Past about ten turns the start of every conversation used to be deleted,
    turn by turn, from the history a person scrolls back through."""
    scripted([("list_skills", {}), ("list_skills", {})])
    conversation = assistant.start(user, "")

    for n in range(30):
        await assistant.say(user, conversation, f"turn {n}")

    saved = conversations.load(conversation.id, team_id=user.team_id)
    humans = [m.content for m in saved.messages if isinstance(m, HumanMessage)]
    assert humans == [f"turn {n}" for n in range(30)]


async def test_the_model_is_shown_a_window_however_long_it_gets(user, monkeypatch, answers_yes):
    shown = []

    class Recording:
        def __init__(self, tool_list):
            pass

        async def astream(self, payload, config=None, stream_mode=None):
            shown.append(list(payload["messages"]))
            yield {"messages": list(payload["messages"]) + [AIMessage("ok")]}

    monkeypatch.setattr(assistant, "_agent", lambda tool_list: Recording(tool_list))
    conversation = assistant.start(user, "")
    for n in range(assistant.TURNS_REMEMBERED + 15):
        await assistant.say(user, conversation, f"turn {n}")

    last = shown[-1]
    assert sum(isinstance(m, HumanMessage) for m in last) == assistant.TURNS_REMEMBERED + 1, (
        "the turns remembered, and the message being sent"
    )
    assert isinstance(last[0], HumanMessage)


async def test_when_it_was_said_and_what_came_with_it_are_kept(user, scripted, answers_yes, tmp_path):
    scripted([("open_questionnaire", {"file_name": ""}), ("answer_questions", {})])
    conversation = assistant.start(user, "")
    path = shapes.status_and_comment(tmp_path / "HR Assessment.xlsx")

    await assistant.say(user, conversation, "Answer everything", upload=path)

    body = TestClient(app).get(f"/api/chat/{conversation.id}").json()
    you, reply = body["messages"]
    assert you["text"] == "Answer everything" and you["file"] == "HR Assessment.xlsx" and you["at"]
    assert reply["at"] and reply["changed"] is True, "so the reply can offer the answers"


def test_a_message_stored_before_files_were_recorded_still_names_its_file():
    old = HumanMessage(f"Read this\n\n{assistant.UPLOAD_NOTE} Vendor.xlsx. Call open_questionnaire to read it.]")
    assert assistant.uploaded_name(old) == "Vendor.xlsx"
    assert assistant.uploaded_name(HumanMessage("no file here")) == ""


# --- reading answers back -------------------------------------------------------------


@pytest.fixture
def answered(user, tmp_path, answers_yes):
    path = shapes.status_and_comment(tmp_path / "HR Assessment.xlsx")
    state: dict = {"batch_id": "", "pending_upload": str(path), "steps": [], "refreshed": False}
    tool = {t.__name__: t for t in assistant._tools(user, state)}
    tool["open_questionnaire"]("")
    return tool, state


async def test_the_second_question_is_the_second_question(answered):
    tool, state = answered
    await tool["answer_questions"]()

    said = tool["read_answers"](position="2")

    second = batches.load(state["batch_id"]).form.questions[1]
    assert f"#2  {second.id}" in said
    assert "answer, to relay word for word: Yes, this is documented and approved." in said
    assert said.count("answer, to relay") == 1


async def test_the_last_one_and_a_range(answered):
    tool, _state = answered
    await tool["answer_questions"]()

    assert "#4 " in tool["read_answers"](position="last")
    assert tool["read_answers"](position="2-3").count("answer, to relay") == 2
    assert "there is no question at '9'" in tool["read_answers"](position="9")


async def test_reading_answers_changes_nothing(answered):
    tool, state = answered
    await tool["answer_questions"]()
    state["refreshed"] = False
    before = {q: a.answer for q, a in batches.answers(state["batch_id"]).items()}

    tool["read_answers"](position="1")
    tool["read_answers"](only="flagged")

    assert state["refreshed"] is False
    assert {q: a.answer for q, a in batches.answers(state["batch_id"]).items()} == before


async def test_a_question_with_no_answer_yet_says_so(answered):
    tool, _state = answered
    said = tool["read_answers"](position="2")
    assert "nothing has been written for it yet" in said


async def test_listing_gives_each_question_its_place(answered):
    tool, _state = answered
    said = tool["list_questions"]()
    assert "#2  Do employees receive regular cybersecurity awareness training?" in said


async def test_undoing_a_rewording_puts_the_drafts_back(answered, monkeypatch):
    tool, state = answered
    await tool["answer_questions"]()

    async def shorter(answered, instruction, language=None, **kwargs):
        revised = answered.model_copy(deep=True)
        revised.answer = "Short."
        return revised

    monkeypatch.setattr(tools.rewrite, "rewrite", shorter)
    await tool["reword_answers"]("one sentence each")

    said = tool["put_back_drafts"]()

    assert said == "Put 4 answer(s) back as they were first drafted."
    assert all(a.answer.startswith("Yes, this is documented") for a in batches.answers(state["batch_id"]).values())
    assert "nothing was put back" in tool["put_back_drafts"]()


async def test_asked_for_another_language_the_rewording_writes_in_it(answered, monkeypatch):
    tool, _state = answered
    await tool["answer_questions"]()
    languages = []

    async def record(answered, instruction, language=None, **kwargs):
        languages.append(language)
        return answered.model_copy(deep=True)

    monkeypatch.setattr(tools.rewrite, "rewrite", record)
    await tool["reword_answers"]("translate to Arabic", language="ar")
    await tool["reword_answers"]("more formal")

    assert languages == ["ar"] * 4 + [None] * 4


def test_the_assistant_is_told_to_read_answers_back_and_that_it_cannot_approve():
    assert "ASKED WHAT AN ANSWER SAYS, READ IT BACK" in assistant.SYSTEM
    assert '`position="2"`' in assistant.SYSTEM
    assert "You cannot approve an answer" in assistant.SYSTEM
    assert "put_back_drafts" in assistant.SYSTEM


def test_preferences_module_still_imports_cleanly():
    assert preferences.BUILTIN_SKILLS


def test_the_reply_language_is_restated_for_the_turn_it_is_about():
    """The rule lost to English tool results: an Arabic question got an English reply."""
    arabic = [HumanMessage("Read this"), AIMessage("Done."), HumanMessage("كم سؤالاً بقي بدون إجابة؟")]
    english = [HumanMessage("اقرأ هذا"), AIMessage("تم."), HumanMessage("How many are left?")]

    assert assistant._language_of_the_turn(arabic) == "ar"
    assert assistant._language_of_the_turn(english) == "en", "the latest message decides"
    assert "quote it exactly as it is written" in assistant.IN_ARABIC


# --- "question 3" means the third question -------------------------------------------


async def test_question_three_is_the_third_question_not_row_three(answered, monkeypatch):
    """Asked to make "the answer to question 3" more formal, the assistant
    reworded the training question: its id is `Human Resources!3`, a spreadsheet
    row, and it is question 2."""
    tool, state = answered
    await tool["answer_questions"]()
    touched = []

    async def record(answered, instruction, language=None, **kwargs):
        touched.append(answered.question.id)
        return answered.model_copy(deep=True)

    monkeypatch.setattr(tools.rewrite, "rewrite", record)
    await tool["reword_answers"]("more formal", position="3")

    third = batches.load(state["batch_id"]).form.questions[2]
    assert touched == [third.id]
    assert third.id != "Human Resources!3"


async def test_a_place_that_is_not_in_the_file_changes_nothing(answered, monkeypatch):
    """An empty id list means "no restriction" to a scope, so a position that
    resolved to nothing used to be one step away from rewording everything."""
    tool, _state = answered
    await tool["answer_questions"]()
    touched = []

    async def record(answered, instruction, language=None, **kwargs):
        touched.append(answered.question.id)
        return answered

    monkeypatch.setattr(tools.rewrite, "rewrite", record)
    said = await tool["reword_answers"]("more formal", position="9")

    assert touched == []
    assert "No answered questions matched" in said


async def test_dictating_and_setting_aside_by_place(answered):
    tool, state = answered
    await tool["answer_questions"]()
    fourth = batches.load(state["batch_id"]).form.questions[3]

    tool["write_one_answer"]("Yes, for every new hire.", position="4")
    tool["set_aside"](position="last")

    assert batches.answers(state["batch_id"])[fourth.id].answer == "Yes, for every new hire."
    assert batches.load(state["batch_id"]).form.questions[3].skip is True
    assert "no single question" in tool["write_one_answer"]("x", position="9")


# --- a reply said twice ---------------------------------------------------------------


@pytest.mark.parametrize(("said", "kept"), [
    ("The background-check question (question 4) has been restored to the questionnaire."
     "The background-check question (question 4) is now back in the questionnaire.",
     "The background-check question (question 4) is now back in the questionnaire."),
    ("The background-check question has been set aside and will not be written to the file."
     "The background-check question has been set aside and will be excluded from the final submission.",
     "The background-check question has been set aside and will be excluded from the final submission."),
    ("تم تنحية سؤال الفحص الأمني ولن يكتب في الملف.تم تنحية سؤال الفحص الأمني ولن يُكتب في الملف النهائي.",
     "تم تنحية سؤال الفحص الأمني ولن يُكتب في الملف النهائي."),
])
def test_a_reply_the_model_wrote_twice_is_kept_once(said, kept):
    assert assistant.without_repetition(said) == kept


@pytest.mark.parametrize("said", [
    "Answered 4 of 4.See the answers beside this.",
    "Yes. T2 encrypts data.Our backups are also encrypted with AES-256 and keys rotate yearly.",
    "Answered the first two questions.",
    "The answer to question 2 is: data is stored in Saudi Arabia.The answer rests on the "
    "Data Privacy Policy, section 4.",
])
def test_two_different_sentences_are_left_alone(said):
    assert assistant.without_repetition(said) == said



def test_a_previous_reply_appended_to_this_one_is_taken_off():
    earlier = ["No answers are currently flagged. All answers will be included in the file."]
    said = ("The background-check question has been set aside and will not be written to the file."
            "No answers are currently flagged. All answers will be included in the file.")

    assert assistant.tidy_reply(said, earlier) == (
        "The background-check question has been set aside and will not be written to the file."
    )
    assert assistant.tidy_reply(earlier[0], earlier) == earlier[0], "saying the same thing again is allowed"


def test_the_models_own_citation_markers_are_taken_out():
    said = "Passwords must be at least 8 characters. 【search_policies result #2】 That is the minimum."
    assert assistant.tidy_reply(said) == "Passwords must be at least 8 characters. That is the minimum."


async def test_no_flagged_answers_is_said_as_facts_not_as_an_approval(answered):
    """Told only that nothing matched, the assistant announced that every answer
    had been approved. Nobody had approved anything."""
    tool, _state = answered
    await tool["answer_questions"]()

    said = tool["read_answers"](only="flagged")

    assert "None of the 4 answers is flagged" in said
    assert "0 of them have been approved by a person" in said
    assert "None of the 4 answers has been approved" in tool["read_answers"](only="approved")


async def test_what_is_stored_is_what_was_shown(user, monkeypatch, answers_yes):
    earlier = "Answered the first two questions, and none needs review."

    class Echoing:
        def __init__(self, tool_list):
            pass

        async def astream(self, payload, config=None, stream_mode=None):
            yield {"messages": list(payload["messages"]) + [AIMessage("Set aside question 4." + earlier)]}

    conversation = assistant.start(user, "")
    conversation.messages = [HumanMessage("Answer two"), AIMessage(earlier)]
    monkeypatch.setattr(assistant, "_agent", lambda tool_list: Echoing(tool_list))

    turn = await assistant.say(user, conversation, "Leave out question 4")

    assert turn.reply == "Set aside question 4."
    saved = conversations.load(conversation.id, team_id=user.team_id)
    assert [m.content for m in saved.messages if assistant._said(m)][-1] == "Set aside question 4."



async def test_a_call_to_a_tool_that_does_not_exist_is_carried_on_from_not_fatal(
    user, monkeypatch, answers_yes
):
    """Groq refuses the whole request when the model calls a tool it was never
    offered -- `repo_browser.open_file`, from its own training. That ended turns
    that had already done their work."""
    sent = []

    class Flaky:
        def __init__(self, tool_list):
            pass

        async def astream(self, payload, config=None, stream_mode=None):
            messages = list(payload["messages"])
            sent.append(messages)
            if len(sent) == 1:
                yield {"messages": messages + [
                    AIMessage("", tool_calls=[{"name": "list_skills", "args": {}, "id": "a"}]),
                    ToolMessage("Built in: ...", tool_call_id="a"),
                ]}
                raise RuntimeError(INVENTED)
            if len(sent) == 2:
                yield {"messages": messages}
                raise RuntimeError(INVENTED)
            yield {"messages": messages + [AIMessage("Here are your skills.")]}

    monkeypatch.setattr(assistant, "_agent", lambda tool_list: Flaky(tool_list))
    conversation = assistant.start(user, "")

    turn = await assistant.say(user, conversation, "What skills do I have?")

    assert turn.reply == "Here are your skills." and not turn.stopped_early
    assert [len(messages) for messages in sent] == [1, 4, 4], (
        "carried on with the finished tool call, not started over, and one note, not one per try"
    )
    note = sent[1][-1]
    assert isinstance(note, HumanMessage) and "repo_browser.open_file" in note.content, (
        "the same request again gets the same refused call at temperature 0"
    )
    saved = conversations.load(conversation.id, team_id=user.team_id)
    assert sum(isinstance(m, ToolMessage) for m in saved.messages) == 1
    assert [m.content for m in saved.messages if isinstance(m, HumanMessage)] == [
        "What skills do I have?"
    ], "the note is sent, never stored"


INVENTED = ("Error code: 400 - {'error': {'message': \"Tool call validation failed: attempted to "
            "call tool 'repo_browser.open_file' which was not in request.tools\", "
            "'code': 'tool_use_failed'}}")


async def test_a_model_that_keeps_inventing_tools_stops_after_two_tries(user, monkeypatch, answers_yes):
    tries = []

    class Stubborn:
        def __init__(self, tool_list):
            pass

        async def astream(self, payload, config=None, stream_mode=None):
            tries.append(1)
            raise RuntimeError(INVENTED)
            yield  # pragma: no cover

    monkeypatch.setattr(assistant, "_agent", lambda tool_list: Stubborn(tool_list))
    turn = await assistant.say(user, assistant.start(user, ""), "hello")

    assert turn.stopped_early and len(tries) == 1 + assistant.CARRY_ON


def test_the_note_does_not_change_the_language_of_the_reply():
    note = assistant._correction(RuntimeError(INVENTED))
    messages = [HumanMessage("ما هي إجابة السؤال الثاني؟"), note]

    assert assistant._language_of_the_turn(messages) == "ar"


async def test_any_other_failure_still_stops_the_turn(user, monkeypatch, answers_yes):
    class Broken:
        def __init__(self, tool_list):
            pass

        async def astream(self, payload, config=None, stream_mode=None):
            raise RuntimeError("the network is down")
            yield  # pragma: no cover

    monkeypatch.setattr(assistant, "_agent", lambda tool_list: Broken(tool_list))
    turn = await assistant.say(user, assistant.start(user, ""), "hello")
    assert turn.stopped_early
