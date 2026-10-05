"""A reasoning model's thinking must never be mistaken for the answer.

Some models write their working into the message rather than beside it, and
Groq returns it that way unless it is told otherwise: `reasoning_format`
defaults to **raw**, which means `<think>...</think>` in front of the answer.
The deployment was pointed at such a model, and the Brief button answered with
"<think>The user wants me to rewrite the answer to be more concise...".

Drafting was never affected -- it comes back through a tool call, where the
thinking cannot reach -- so what these tests hold are the paths that use the
model's plain text: rewording, the assistant's replies, and everything
downstream of a reworded answer, which is the customer's own file.
"""

from __future__ import annotations

import pytest

from src import llm, rewrite
from src.agents import assistant
from src.config import settings
from src.formatting import to_cell_text, without_reasoning
from src.forms import status
from src.models import AnsweredQuestion, Question

THINKING = (
    "<think>\nThe user wants me to rewrite the answer to be more concise, following these "
    "rules:\n\n1. Open with the verdict (yes, no, partly, not applicable)\n2. One sentence "
    "saying what we do. This is not applicable to physical media, but the policy is clear.\n"
    "</think>\n\nYes. Backups are encrypted with AES-256."
)
SAID = "Yes. Backups are encrypted with AES-256."


# --- reading the message ---------------------------------------------------------------


def test_the_thinking_comes_out_and_the_answer_stays():
    assert without_reasoning(THINKING) == SAID


@pytest.mark.parametrize("text", [
    "<THINK>working</THINK>Yes.",
    "< think >working</ think >Yes.",
    "<thinking>working</thinking>\nYes.",
    "<reasoning>working</reasoning>Yes.",
    "<think>first</think><think>second</think>Yes.",
])
def test_the_shapes_a_provider_returns_it_in(text):
    assert without_reasoning(text) == "Yes."


def test_an_answer_with_no_thinking_is_untouched():
    assert without_reasoning(SAID) == SAID
    assert without_reasoning("") == ""


def test_a_reply_cut_off_mid_thought_has_no_answer_in_it():
    """Reaching the token limit inside the thinking leaves an opening tag and
    no answer. Returning what is left would write the working into the file."""
    assert without_reasoning("<think>\nThe user wants me to rewrite") == ""
    assert without_reasoning("Yes.\n<think>and now I reconsider") == "Yes."


# --- rewording -------------------------------------------------------------------------


class Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class Model:
    def __init__(self, content: str) -> None:
        self.content = content

    async def ainvoke(self, messages):
        return Reply(self.content)


def _answered() -> AnsweredQuestion:
    return AnsweredQuestion(
        question=Question(id="q1", text="Do you encrypt backups?", language="en"),
        answer="Yes. Backups are encrypted at rest with AES-256 and restores are tested quarterly.",
        confidence=0.9, needs_review=False,
    )


@pytest.fixture
def thinking_model(monkeypatch):
    def use(content: str):
        monkeypatch.setattr(rewrite, "chat_llm", lambda **_: Model(content))
    return use


@pytest.mark.asyncio
async def test_a_reworded_answer_is_what_the_model_said_not_what_it_thought(thinking_model):
    thinking_model(THINKING)
    revised = await rewrite.rewrite(_answered(), "Make it shorter.")
    assert revised.answer == SAID


@pytest.mark.asyncio
async def test_the_brief_form_is_too(thinking_model):
    thinking_model(THINKING)
    assert await rewrite.shorten(_answered()) == SAID


@pytest.mark.asyncio
async def test_thinking_with_no_answer_after_it_costs_the_wording_not_the_answer(thinking_model):
    """The rule the rewrite path already had, reached by a new route: a
    rewording that produces nothing leaves the answer as it was."""
    original = _answered()
    thinking_model("<think>The user wants me to rewrite the answer, so I should")

    revised = await rewrite.rewrite(original, "Make it shorter.")

    assert revised is original
    assert revised.answer.startswith("Yes. Backups are encrypted at rest")


# --- what a reworded answer reaches ------------------------------------------------------


def test_thinking_never_reaches_a_cell():
    """`fill` writes `to_cell_text`, and a cell goes to the customer."""
    assert to_cell_text(THINKING) == SAID


def test_the_verdict_is_read_from_the_answer_not_the_thinking():
    """The dropdown beside the answer is set from the verdict it opens with.
    With the thinking in front, the opening verdict is hidden and the fallback
    scan reads the reasoning's words instead: this answer says yes, and the
    customer's file said Not Applicable."""
    options = ["Yes", "No", "Partially", "Not Applicable"]

    assert status.stance_of(THINKING) is status.Stance.YES
    assert status.choose(THINKING, options).value == "Yes"


def test_the_assistants_reply_is_what_it_said(monkeypatch):
    from langchain_core.messages import AIMessage

    state = {"messages": [AIMessage(THINKING)]}
    assert assistant._reply_from(state) == SAID


# --- asking the provider not to send it in the first place -------------------------------


def test_the_provider_is_asked_to_keep_the_thinking_separate(monkeypatch):
    """The real fix. Stripping is the second lock, for a gateway that ignores
    this or a model that emits the tags anyway."""
    made = {}

    class Recorder:
        def __init__(self, **kwargs):
            made.update(kwargs)

    monkeypatch.setattr(llm, "ChatGroq", Recorder)
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "groq_reasoning_format", "parsed")
    llm.chat_llm.cache_clear()

    llm.chat_llm(temperature=0.0)

    assert made["reasoning_format"] == "parsed"
    llm.chat_llm.cache_clear()


def test_a_gateway_that_rejects_the_parameter_can_be_told_not_to_send_it(monkeypatch):
    made = {}

    class Recorder:
        def __init__(self, **kwargs):
            made.update(kwargs)

    monkeypatch.setattr(llm, "ChatGroq", Recorder)
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "groq_reasoning_format", "")
    llm.chat_llm.cache_clear()

    llm.chat_llm(temperature=0.0)

    assert "reasoning_format" not in made
    llm.chat_llm.cache_clear()


# --- repairing what was stored while it was broken ---------------------------------------


def test_the_repair_script_cleans_a_stored_answer_and_leaves_the_rest(tmp_path):
    """Answers reworded while the setting was unset are still in the database;
    `scripts/strip_thinking.py` takes the thinking back out of them."""
    import sqlite3

    from scripts.strip_thinking import clean
    from src import batches, store
    from src.forms.model import DetectedForm
    from src.identity import User

    user = User(email="a@example.com", team_id=settings.default_team)
    batch = batches.create(user, tmp_path / "vendor.xlsx", DetectedForm(source_name="v.xlsx", format="xlsx"))
    thinking = _answered()
    thinking.question.id = "q1"
    thinking.answer = THINKING
    thinking.brief = THINKING
    clean_one = _answered()
    clean_one.question.id = "q2"
    batches.save_answers(batch.id, [thinking, clean_one])

    connection = sqlite3.connect(settings.db_path)
    try:
        found, empty = clean(connection, apply=True)
    finally:
        connection.close()
    store.reset_connection()

    stored = batches.answers(batch.id)
    assert (found, empty) == (2, 0)
    assert stored["q1"].answer == SAID and stored["q1"].brief == SAID
    assert stored["q2"].answer == clean_one.answer, "an answer with no thinking is untouched"


def test_the_repair_script_leaves_an_answer_that_is_only_thinking(tmp_path):
    """There is nothing underneath it to keep, and a silently blanked answer is
    worse than an obviously wrong one."""
    import sqlite3

    from scripts.strip_thinking import clean
    from src import batches, store
    from src.forms.model import DetectedForm
    from src.identity import User

    user = User(email="a@example.com", team_id=settings.default_team)
    batch = batches.create(user, tmp_path / "vendor.xlsx", DetectedForm(source_name="v.xlsx", format="xlsx"))
    only_thinking = _answered()
    only_thinking.question.id = "q1"
    only_thinking.answer = "<think>The user wants me to rewrite the answer, so I should"
    batches.save_answers(batch.id, [only_thinking])

    connection = sqlite3.connect(settings.db_path)
    try:
        found, empty = clean(connection, apply=True)
    finally:
        connection.close()
    store.reset_connection()

    assert (found, empty) == (1, 1)
    assert batches.answers(batch.id)["q1"].answer.startswith("<think>")


# --- a tool call written in the model's own dialect ---------------------------------------
#
# The second thing a reasoning model broke, and the worse one: Qwen-trained
# models write a tool call as XML, where every value is text. A boolean field
# then reads "True", the provider refuses the whole call, and the question comes
# back unanswered. Measured against qwen3.6 on Groq: every review call failed,
# under every reasoning format, so nothing could be answered at all.

XML_CALL = (
    "<tool_call>\n<function=AnswerReview>\n<parameter=grounded>\nTrue\n</parameter>\n"
    "<parameter=confidence>\n0.92\n</parameter>\n<parameter=verdict_reason>\n"
    "Every claim maps to a source.\n</parameter>\n</function>\n</tool_call>"
)


class Refused(Exception):
    """Groq's `tool_use_failed`, as the client raises it."""

    def __init__(self, failed_generation: str) -> None:
        super().__init__("tool call validation failed")
        self.body = {"error": {"code": "tool_use_failed", "failed_generation": failed_generation}}


@pytest.fixture
def groq_refusal(monkeypatch):
    monkeypatch.setattr(llm, "GroqBadRequestError", Refused)


def test_a_tool_call_written_as_xml_is_recovered(groq_refusal):
    from src.models import AnswerReview

    recovered = llm._recover_from_tool_use_failed(Refused(XML_CALL), AnswerReview)

    assert recovered is not None
    assert recovered.grounded is True, "the string 'True' is the boolean it was meant to be"
    assert recovered.confidence == 0.92
    assert "maps to a source" in recovered.verdict_reason


def test_the_json_shape_still_recovers(groq_refusal):
    """The dialect this existed for first: valid arguments under a wrong name."""
    import json

    from src.models import AnswerReview

    payload = json.dumps({"name": "not_the_tool", "arguments": {
        "grounded": True, "confidence": 0.5, "verdict_reason": "Supported.",
    }})

    recovered = llm._recover_from_tool_use_failed(Refused(payload), AnswerReview)

    assert recovered is not None and recovered.confidence == 0.5


def test_a_list_argument_survives_the_dialect(groq_refusal):
    from src.models import DraftedAnswer

    call = (
        "<function=DraftedAnswer>\n<parameter=answer>\nYes.\n</parameter>\n"
        "<parameter=used_source_ids>\n[1, 3]\n</parameter>\n"
        "<parameter=confidence>\n0.8\n</parameter>\n</function>"
    )

    recovered = llm._recover_from_tool_use_failed(Refused(call), DraftedAnswer)

    assert recovered is not None and recovered.used_source_ids == [1, 3]


def test_nonsense_is_not_recovered_into_an_answer(groq_refusal):
    """Recovery must not invent a result: an unusable payload has to re-raise."""
    from src.models import AnswerReview

    assert llm._recover_from_tool_use_failed(Refused("I could not decide."), AnswerReview) is None
    assert llm._recover_from_tool_use_failed(
        Refused("<parameter=grounded>\nmaybe\n</parameter>"), AnswerReview,
    ) is None
