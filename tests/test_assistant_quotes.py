"""A quotation in the assistant's reply is checked against what the tools returned (TD-043).

The failure this file exists for: asked what an Ole5 document says about
integrating with a customer's SIEM, the assistant set out the section's genuine
heading as a blockquote and, under it, a line saying the opposite of the
clause. The only text in quotation marks was the genuine title, so blockquote
lines are checked as well as quotation marks. A quotation that no source or
tool result contains is asked about once; one still unfound after that is shown
as a paraphrase, with a note.

The text here is invented and neutral; the shape is the real one.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src import conversations, tools
from src.agents import assistant, assistant_turn
from src.models import Evidence, SourceType
from tests.test_assistant import user  # noqa: F401 - pytest fixture, used by name

SOURCE = (
    "Ole5 forwards its own audit logs – security events only – to the Ole5 security operations centre.\n"
    "5.3 Integration with the customer's SIEM\n"
    "Direct integration with a customer's SIEM is not supported; customers receive a mont hly summary "
    "report instead."
)
"""A fact sheet's chunk, with an en dash and a word a PDF split in two."""

INVENTED = "Ole5 integrates directly with the customer's SIEM over syslog."


# --- what counts as found -----------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "The fact sheet says “DIRECT integration with a customer's SIEM is NOT supported”.",
        'It says: "Direct integration with a customer\'s **SIEM** is not supported".',
        "> Ole5 forwards its own audit logs — security events only — to the Ole5 security operations centre.",
        "> Direct integration with a customer's SIEM is not supported;\n"
        "> customers receive a monthly summary report instead.",
        "“Ole5 forwards its own audit logs … customers receive a monthly summary report instead.”",
        "“Ole5 forwards its own audit logs [...] Direct integration with a customer's SIEM is not supported”",
    ],
    ids=["case", "markdown", "dashes", "line-break-and-split-word", "ellipsis", "bracketed-ellipsis"],
)
def test_a_quotation_found_in_a_source_is_left_alone(reply):
    assert assistant_turn.unfound(reply, [SOURCE]) == []


def test_the_invented_blockquote_is_caught():
    reply = f"The fact sheet says:\n\n> **5.3 Integration with the customer's SIEM**\n> {INVENTED}\n"

    assert assistant_turn.unfound(reply, [SOURCE]) == [INVENTED], "the heading is genuine; the line under it is not"

    as_it_was = (
        "> **5.3 Integration with the customer's SIEM** (direct integration with the customer's SIEM is supported)"
    )
    assert assistant_turn.unfound(as_it_was, [SOURCE]) == [as_it_was[2:]], "an invented parenthetical is no citation"


def test_a_quotation_cannot_be_stitched_across_two_sources():
    first, second = "Backups are encrypted at rest", "using keys rotated every year by the vendor"
    reply = f"“{first} {second}”"

    assert assistant_turn.unfound(reply, [f"{first}.", f"{second}."]) == [f"{first} {second}"]
    assert assistant_turn.unfound(reply, [f"{first} {second}."]) == []


@pytest.mark.parametrize(
    "reply",
    [
        "> Direct integration with a customer's SIEM is not supported. (Ole5 facts.docx, §5.3)",
        "> Direct integration with a customer's SIEM is not supported — Ole5 facts.docx",
        "> **Ole5 facts.docx, §5.3:** Direct integration with a customer's SIEM is not supported.",
        "> Direct integration with a customer's SIEM is not supported (section 5.3, page 4).",
    ],
    ids=["parenthesis", "dash", "label", "clause-and-page"],
)
def test_a_quotation_attributed_to_its_document_is_still_found(reply):
    """Told to quote the sentence and name its document, the model names it on
    the same line. The name is not part of the quotation."""
    assert assistant_turn.unfound(reply, [SOURCE], ["Ole5 facts.docx"]) == []


def test_arabic_quotations_are_checked():
    """Diacritics, alef forms and presentation forms differ between a PDF's text
    and the same words typed; none of them makes a copy something else."""
    source = "يُرسَل تقرير اختبار الاختراق إلى العملاء عند الطلب، ﻻ قبل توقيع اتفاقية عدم الإفصاح."
    copied = "تقول الوثيقة: «يرسل تقرير اختبار الاختراق الى العملاء عند الطلب، لا قبل توقيع اتفاقية»."
    invented = "تقول الوثيقة: «يرسل تقرير اختبار الاختراق إلى أي عميل يطلبه دون أي اتفاقية»."

    assert assistant_turn.unfound(copied, [source]) == []
    assert assistant_turn.unfound(invented, [source]) == ["يرسل تقرير اختبار الاختراق إلى أي عميل يطلبه دون أي اتفاقية"]


def test_short_quoted_terms_are_not_checked():
    """Titles and terms are put in quotation marks too, and are not claims."""
    reply = 'Under the "Acceptable Use Policy", "no shared accounts" applies; see "Annex B access control rules".'

    assert assistant_turn.unfound(reply, [SOURCE]) == []


# --- asking again, then marking ------------------------------------------------------

GENUINE = (
    "The fact sheet says:\n\n"
    "> Direct integration with a customer's SIEM is not supported; customers receive a monthly summary "
    "report instead.\n\n(Ole5 facts.docx, section 5.3)"
)
DRAFTED = f"The fact sheet says:\n\n> **5.3 Integration with the customer's SIEM**\n> {INVENTED}"


@pytest.fixture
def searched(monkeypatch):
    async def search(query, mode="hybrid", limit=8, *, team_id=None, product_id=""):
        found = Evidence(source_type=SourceType.GUIDELINE, source_name="Ole5 facts.docx", snippet=SOURCE)
        return {"results": [found.model_dump()]}

    monkeypatch.setattr(tools, "search", search)


def _passes(monkeypatch, *replies: str) -> list[list]:
    """An agent that searches on its first pass, and replies with the next of `replies` on each.

    Returns what every pass was sent.
    """
    sent: list[list] = []

    class Agent:
        def __init__(self, tool_list):
            self.tools = {t.__name__: t for t in tool_list}

        async def astream(self, payload, config=None, stream_mode=None):
            messages = list(payload["messages"])
            sent.append(list(messages))
            if len(sent) == 1:
                result = await self.tools["search_policies"](query="customer SIEM integration")
                call = {"name": "search_policies", "args": {"query": "customer SIEM integration"}, "id": "s1"}
                messages += [AIMessage("", tool_calls=[call]), ToolMessage(result, tool_call_id="s1")]
            yield {"messages": messages + [AIMessage(replies[len(sent) - 1])]}

    monkeypatch.setattr(assistant, "_agent", lambda tool_list, **named: Agent(tool_list))
    return sent


@pytest.mark.asyncio
async def test_a_reply_quoting_what_the_source_says_is_sent_as_it_is(user, monkeypatch, searched):
    sent = _passes(monkeypatch, GENUINE)

    turn = await assistant.say(user, assistant.start(user, ""), "Does Ole5 integrate with our SIEM?")

    assert len(sent) == 1
    assert turn.reply == GENUINE


@pytest.mark.asyncio
async def test_a_reply_quoting_what_no_source_says_is_asked_again_once(user, monkeypatch, searched):
    sent = _passes(monkeypatch, DRAFTED, GENUINE)
    conversation = assistant.start(user, "")

    turn = await assistant.say(user, conversation, "Does Ole5 integrate with our SIEM?")

    assert len(sent) == 2
    note = sent[1][-1]
    assert isinstance(note, HumanMessage) and assistant_turn.is_correction(note)
    assert f"«{INVENTED}»" in note.content and "Quote only words copied exactly" in note.content
    assert not any(DRAFTED in str(message.content) for message in sent[1]), "the draft is dropped, not shown back"
    assert any(isinstance(message, ToolMessage) for message in sent[1]), "the search it made is kept"
    assert turn.reply == GENUINE

    saved = conversations.load(conversation.id, team_id=user.team_id)
    stored = "\n".join(str(message.content) for message in saved.messages)
    assert INVENTED not in stored and "Not from the person" not in stored, "neither the draft nor the note is kept"
    assert [m.content for m in saved.messages if assistant._said(m)] == [GENUINE]


@pytest.mark.asyncio
async def test_a_quote_still_unfound_is_shown_as_a_paraphrase(user, monkeypatch, searched):
    sent = _passes(monkeypatch, DRAFTED, DRAFTED)

    turn = await assistant.say(user, assistant.start(user, ""), "Does Ole5 integrate with our SIEM?")

    assert len(sent) == 2, "asked again once, not until it agrees"
    lines = turn.reply.splitlines()
    assert INVENTED in lines, "no longer set out as a quotation"
    assert "> **5.3 Integration with the customer's SIEM**" in lines, "the quotation that was found stays one"
    assert turn.reply.endswith("so treat it as a paraphrase. The clauses themselves are listed under this reply.")


@pytest.mark.asyncio
async def test_the_note_is_in_the_language_of_the_turn(user, monkeypatch, searched):
    drafted = "تقول الوثيقة: «يتكامل نظام Ole5 مباشرة مع نظام إدارة الأحداث لدى العميل»."
    _passes(monkeypatch, drafted, drafted)

    turn = await assistant.say(user, assistant.start(user, ""), "هل يتكامل Ole5 مع نظام إدارة الأحداث لدينا؟")

    assert "«" not in turn.reply and "يتكامل نظام Ole5 مباشرة" in turn.reply
    assert "ملاحظة:" in turn.reply and "المقاطع نفسها مدرجة تحت هذه الرسالة." in turn.reply
