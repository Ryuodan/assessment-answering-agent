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
from src.agents import assistant, assistant_quotes, assistant_turn
from src.models import Evidence, SourceType
from tests import forms_fixtures as shapes
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
    assert assistant_quotes.unfound(reply, [SOURCE]) == []


def test_the_invented_blockquote_is_caught():
    reply = f"The fact sheet says:\n\n> **5.3 Integration with the customer's SIEM**\n> {INVENTED}\n"

    assert assistant_quotes.unfound(reply, [SOURCE]) == [INVENTED], "the heading is genuine; the line under it is not"

    as_it_was = (
        "> **5.3 Integration with the customer's SIEM** (direct integration with the customer's SIEM is supported)"
    )
    assert assistant_quotes.unfound(as_it_was, [SOURCE]) == [as_it_was[2:]], "an invented parenthetical is no citation"


def test_a_quotation_cannot_be_stitched_across_two_sources():
    first, second = "Backups are encrypted at rest", "using keys rotated every year by the vendor"
    reply = f"“{first} {second}”"

    assert assistant_quotes.unfound(reply, [f"{first}.", f"{second}."]) == [f"{first} {second}"]
    assert assistant_quotes.unfound(reply, [f"{first} {second}."]) == []


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
    assert assistant_quotes.unfound(reply, [SOURCE], ["Ole5 facts.docx"]) == []


def test_arabic_quotations_are_checked():
    """Diacritics, alef forms and presentation forms differ between a PDF's text
    and the same words typed; none of them makes a copy something else."""
    source = "يُرسَل تقرير اختبار الاختراق إلى العملاء عند الطلب، ﻻ قبل توقيع اتفاقية عدم الإفصاح."
    copied = "تقول الوثيقة: «يرسل تقرير اختبار الاختراق الى العملاء عند الطلب، لا قبل توقيع اتفاقية»."
    invented = "تقول الوثيقة: «يرسل تقرير اختبار الاختراق إلى أي عميل يطلبه دون أي اتفاقية»."

    assert assistant_quotes.unfound(copied, [source]) == []
    assert assistant_quotes.unfound(invented, [source]) == [
        "يرسل تقرير اختبار الاختراق إلى أي عميل يطلبه دون أي اتفاقية"
    ]


def test_short_quoted_terms_are_not_checked():
    """Titles and terms are put in quotation marks too, and are not claims."""
    reply = 'Under the "Acceptable Use Policy", "no shared accounts" applies; see "Annex B access control rules".'

    assert assistant_quotes.unfound(reply, [SOURCE]) == []


# --- the ways round it a review found ---------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "invented"),
    [
        (
            "> \"5.3 Integration with the customer's SIEM\" (Ole5 supports direct integration with the customer's SIEM)",
            "(Ole5 supports direct integration with the customer's SIEM)",
        ),
        (f"> **“5.3 Integration with the customer's SIEM”** — {INVENTED}", INVENTED),
        (f'> Under "Integration", {INVENTED}', INVENTED),
    ],
    ids=["parenthetical", "after-a-dash", "after-a-quoted-term"],
)
def test_the_rest_of_a_blockquote_line_is_checked_beside_its_quoted_heading(reply, invented):
    """The D1-22 shape with the heading in quotation marks: the heading is genuine,
    and was the only thing checked on its line."""
    assert assistant_quotes.unfound(reply, [SOURCE], ["Ole5 facts.docx"]) == [invented]


@pytest.mark.parametrize(
    "reply",
    [
        '> "Direct integration with a customer\'s SIEM is not supported" (Ole5 facts.docx, §5.3)',
        "> “Direct integration with a customer's SIEM is not supported” — Ole5 facts.docx, section 5.3, page 4",
        "> According to Ole5 facts.docx, section 5.3: “Direct integration with a customer's SIEM is not supported.”",
        "> The fact sheet says: «Direct integration with a customer's SIEM is not supported»",
    ],
    ids=["parenthesis", "dash", "named-before", "said-before"],
)
def test_a_quotation_on_a_blockquote_line_beside_where_it_is_from_is_found(reply):
    assert assistant_quotes.unfound(reply, [SOURCE], ["Ole5 facts.docx"]) == []


NOT_SUPPORTED = "Direct integration with a customer's SIEM is not supported."


@pytest.mark.parametrize(
    "reply",
    [
        f"> As stated in Ole5 facts.docx, section 5.3: “{NOT_SUPPORTED}”",
        f"> The Ole5 facts.docx document states in section 5.3: “{NOT_SUPPORTED}”",
        f'> "{NOT_SUPPORTED}" This is stated in Ole5 facts.docx, section 5.3.',
        f'> "{NOT_SUPPORTED}" (from the Ole5 facts document, section 5.3)',
        f"> As the Ole5 fact sheet states in section 5.3: “{NOT_SUPPORTED}”",
        f'> "{NOT_SUPPORTED}" (found in Ole5 facts.docx, section 5.3, last paragraph)',
        f"> وفقاً لما ورد في مستند Ole5 facts.docx، القسم 5.3: «{NOT_SUPPORTED}»",
        f"> كما جاء في مستند Ole5 facts.docx، في القسم 5.3: «{NOT_SUPPORTED}»",
        f"> ينص مستند Ole5 facts.docx في القسم 5.3 على أن: «{NOT_SUPPORTED}»",
        f"> «{NOT_SUPPORTED}» (من مستند Ole5 facts.docx، القسم 5.3)",
        f"> «{NOT_SUPPORTED}» (موجود في القسم 5.3 من مستند Ole5 facts.docx)",
    ],
    ids=[
        "as-stated-in",
        "the-document-states",
        "stated-after",
        "from-the-document",
        "a-shortened-name",
        "found-in",
        "ar-according-to",
        "ar-as-it-came",
        "ar-the-document-says",
        "ar-from-the-document",
        "ar-found-in",
    ],
)
def test_a_quotation_said_to_be_from_its_document_in_a_sentence_is_found(reply):
    """A review found each of these, correct quotations all, asked about again and then
    marked a paraphrase: an attribution of three words or more was read as a claim."""
    assert assistant_quotes.unfound(reply, [SOURCE], ["Ole5 facts.docx"]) == []


@pytest.mark.parametrize(
    ("reply", "invented"),
    [
        (
            f"> As stated in Ole5 facts.docx, Ole5 supports syslog forwarding: “{NOT_SUPPORTED}”",
            "As stated in Ole5 facts.docx, Ole5 supports syslog forwarding",
        ),
        (
            f"> “{NOT_SUPPORTED}” (Ole5 facts.docx, section 5.3: now supported)",
            "(Ole5 facts.docx, section 5.3: now supported)",
        ),
        (
            f"> وفقاً لمستند Ole5 facts.docx فإن التكامل المباشر مدعوم: «{NOT_SUPPORTED}»",
            "وفقاً لمستند Ole5 facts.docx فإن التكامل المباشر مدعوم",
        ),
        (
            f"> “{NOT_SUPPORTED}” This is not stated in Ole5 facts.docx, section 5.3.",
            "This is not stated in Ole5 facts.docx, section 5.3.",
        ),
    ],
    ids=["a-claim-in-the-attribution", "a-short-claim-after-the-name", "ar-a-claim-in-the-attribution", "a-negation"],
)
def test_a_claim_in_an_attribution_is_still_caught(reply, invented):
    assert assistant_quotes.unfound(reply, [SOURCE], ["Ole5 facts.docx"]) == [invented]


@pytest.mark.parametrize(
    "reply",
    [
        f'> Ole5 facts.docx, section 5.3, states the following: "{NOT_SUPPORTED}"',
        f"> Ole5 facts.docx puts it as follows in section 5.3: “{NOT_SUPPORTED}”",
        f"> The relevant clause in Ole5 facts.docx (section 5.3) reads: “{NOT_SUPPORTED}”",
        f"> Ole5 facts.docx explicitly states in section 5.3: “{NOT_SUPPORTED}”",
        f"> Here is the exact wording from Ole5 facts.docx, section 5.3: “{NOT_SUPPORTED}”",
        f"> The answer is in Ole5 facts.docx, section 5.3, which says: “{NOT_SUPPORTED}”",
        f"> As set out in Ole5 facts.docx, section 5.3: “{NOT_SUPPORTED}”",
        f"> جاء في البند 5.3 من مستند Ole5 facts.docx ما يلي: «{NOT_SUPPORTED}»",
        f"> جاء في القسم 5.3 من مستند Ole5 facts.docx ما نصه: «{NOT_SUPPORTED}»",
        f"> تنص الفقرة 5.3 من مستند Ole5 facts.docx بوضوح على: «{NOT_SUPPORTED}»",
    ],
    ids=[
        "the-following",
        "puts-it-as-follows",
        "relevant-clause-reads",
        "explicitly-states",
        "exact-wording",
        "the-answer-is-in",
        "set-out-in",
        "ar-what-follows",
        "ar-its-wording",
        "ar-clearly",
    ],  # fmt: skip
)
def test_an_ordinary_attribution_cites(reply):
    """A second review found each of these, correct quotations all, still asked about
    again: one ordinary word outside the list made the attribution a claim."""
    assert assistant_quotes.unfound(reply, [SOURCE], ["Ole5 facts.docx"]) == []


@pytest.mark.parametrize(
    ("reply", "invented"),
    [
        (f"> “{NOT_SUPPORTED}” (Ole5 facts.docx, section 5.3: it is set to 90 in the policy)",
         "(Ole5 facts.docx, section 5.3: it is set to 90 in the policy)"),
        (f"> “{NOT_SUPPORTED}” (Ole5 facts.docx, section 4: it is set to 90)",
         "(Ole5 facts.docx, section 4: it is set to 90)"),
        (f"> «{NOT_SUPPORTED}» (لمّا يرد في مستند Ole5 facts.docx)", "(لمّا يرد في مستند Ole5 facts.docx)"),
    ],
    ids=["a-value-set", "a-value-set-short", "ar-not-yet-said"],
)  # fmt: skip
def test_a_value_or_a_negation_beside_a_quotation_is_no_citation(reply, invented):
    """ "set" and "put" count only in "set out" and "puts it"; "لما" only before "ورد" or
    "جاء", since "لمّا يرد" means "not yet said"."""
    assert assistant_quotes.unfound(reply, [SOURCE], ["Ole5 facts.docx"]) == [invented]


def test_more_than_is_not_a_quotation():
    """A list item starting with ">99.9%" is a comparison the model wrote, not a quotation."""
    reply = "Ole5 commits to:\n- >99.9% availability for the hosted service each month\n- 24/7 support"

    assert assistant_quotes.unfound(reply, ["Ole5 availability is 99.9%."], ["Ole5 facts.docx"]) == []


@pytest.mark.parametrize(
    "lead",
    [
        "As outlined in Ole5 facts.docx, section 5.3:",
        "As detailed in Ole5 facts.docx, section 5.3:",
        "As defined in Ole5 facts.docx, section 5.3:",
        "As documented in Ole5 facts.docx, section 5.3:",
        "Excerpt from Ole5 facts.docx, section 5.3:",
        "Ole5 facts.docx, section 5.3, indicates the following:",
        "In the words of Ole5 facts.docx, section 5.3:",
        "حسب ما ورد في مستند Ole5 facts.docx، القسم 5.3:",
        "بحسب ما جاء في مستند Ole5 facts.docx، القسم 5.3:",
        "وفق ما ورد في القسم 5.3 من مستند Ole5 facts.docx:",
        "كما هو موضح في القسم 5.3 من مستند Ole5 facts.docx:",
        "كما هو منصوص عليه في القسم 5.3 من مستند Ole5 facts.docx:",
        "وفيما يلي نص القسم 5.3 من مستند Ole5 facts.docx:",
        "استناداً إلى القسم 5.3 من مستند Ole5 facts.docx:",
        "نقلاً عن مستند Ole5 facts.docx، القسم 5.3:",
        "يشير مستند Ole5 facts.docx في القسم 5.3 إلى ما يلي:",
    ],
)
def test_more_ordinary_attributions_cite(lead):
    """A third review's list of attributions that still cost a second pass and a false note."""
    assert assistant_quotes.unfound(f"> {lead} “{NOT_SUPPORTED}”", [SOURCE], ["Ole5 facts.docx"]) == []


RETAINED = "7.2 Log retention\nAudit logs are retained for 90 days and then deleted automatically by the platform."
KEPT = "Audit logs are retained for 90 days and then deleted automatically by the platform."
POLICIES = ["Ole5 facts.docx", "Data Retention Policy.docx", "Encryption Standard.pdf"]


@pytest.mark.parametrize(
    ("reply", "invented"),
    [
        (f"> The answer is 365, as stated in Ole5 facts.docx, section 7.2: “{KEPT}”",
         "The answer is 365, as stated in Ole5 facts.docx, section 7.2"),
        (f"> “{KEPT}” (Ole5 facts.docx, section 7.2: the answer is 365)", "(Ole5 facts.docx, section 7.2: the answer is 365)"),
        (f"> “{KEPT}” (Data Retention Policy.docx, section 7.2: it is 365 in the policy)",
         "(Data Retention Policy.docx, section 7.2: it is 365 in the policy)"),
        (f"> “{KEPT}” (Ole5 data retention is 365, per the Data Retention Policy)",
         "(Ole5 data retention is 365, per the Data Retention Policy)"),
        (f"> «{KEPT}» (هو 365 كما ورد في مستند Ole5 facts.docx)", "(هو 365 كما ورد في مستند Ole5 facts.docx)"),
        (f"> “{KEPT}” (Ole5 facts.docx, section 7.2, puts it at 365)", "(Ole5 facts.docx, section 7.2, puts it at 365)"),
        (f"> “{KEPT}” (Ole5 facts.docx sets out 365 in section 7.2)", "(Ole5 facts.docx sets out 365 in section 7.2)"),
        (f"> Ole5 follows the Encryption Standard, as stated in Ole5 facts.docx, section 7.2: “{KEPT}”",
         "Ole5 follows the Encryption Standard, as stated in Ole5 facts.docx, section 7.2"),
    ],
    ids=["the-answer-is", "the-answer-is-after", "it-is-in-the-policy", "a-value-between-names", "ar-a-value",
         "puts-it-at", "sets-out-a-value", "follows-a-standard"],
)  # fmt: skip
def test_a_value_or_a_compliance_claim_beside_a_quotation_is_caught(reply, invented):
    """A number counts as a place only right after a place word or a document's name;
    "answer", "follows" and "puts it" only in phrases that say where something is said."""
    assert assistant_quotes.unfound(reply, [RETAINED], POLICIES) == [invented]


@pytest.mark.parametrize("line", [f">5.3 {INVENTED}", f">> {INVENTED}"], ids=["clause-number-after-the-mark", "nested"])
def test_a_blockquote_starting_with_a_number_or_nested_is_still_checked(line):
    """ "More than" is read only after a list item's marker; at the start of a line `>` is a quotation."""
    assert assistant_quotes.unfound(line, [SOURCE]) != []


def test_no_note_is_added_for_words_the_reply_does_not_hold():
    """In plan 028's rehearsal a reply quoting three clauses word for word got the note,
    while its quotation marks and blockquotes stayed: the words flagged were not in it.
    A note that points at no quotation is only wrong, so none is added."""
    reply = "> “Direct integration with a customer's SIEM is not supported.” – *Ole5 facts.docx*"

    assert assistant_quotes.as_paraphrase(reply, [INVENTED], "en", listed=True) == reply
    assert assistant_quotes.as_paraphrase(f"> {INVENTED}", [INVENTED], "en", listed=True) != f"> {INVENTED}"


@pytest.mark.parametrize(
    "reply",
    [
        f"    > {INVENTED}",
        f"- > {INVENTED}",
        f"* > {INVENTED}",
        f"1. > {INVENTED}",
        f"2) > {INVENTED}",
        f"\t> {INVENTED}",
    ],
    ids=["indented", "dash-item", "star-item", "numbered-item", "numbered-paren-item", "tab"],
)
def test_a_blockquote_indented_or_in_a_list_is_checked(reply):
    """The chat page shows each line trimmed, so these all read as "> ..." there,
    and none of them was checked."""
    assert assistant_quotes.unfound(reply, [SOURCE]) == [INVENTED]


@pytest.mark.parametrize(
    ("reply", "shown"),
    [
        (f"- > {INVENTED}", f"- {INVENTED}"),
        (f"    > {INVENTED}", f"    {INVENTED}"),
        (f"1. > {INVENTED}", f"1. {INVENTED}"),
    ],
    ids=["dash-item", "indented", "numbered-item"],
)
def test_a_blockquote_in_a_list_shown_as_a_paraphrase_stays_a_list_item(reply, shown):
    said = assistant_quotes.as_paraphrase(reply, [INVENTED], "en", listed=False)

    assert said.splitlines()[0] == shown


@pytest.mark.parametrize(
    "reply",
    [
        "“Direct integration with a customer's SIEM is … supported”",
        "“Direct integration with a customer's SIEM is … supported; customers receive a monthly summary report instead”",
    ],
    ids=["ending-on-it", "going-on-after-it"],
)
def test_an_ellipsis_cannot_leave_out_a_negation(reply):
    assert assistant_quotes.unfound(reply, [SOURCE]) == [reply[1:-1]]


def test_a_negation_left_out_is_one_of_the_clauses_quoted_however_it_is_split():
    source = "Backups are encrypted every night. Keys are not rotated by the vendor."

    assert assistant_quotes.unfound("“Backups are encrypted every night … rotated by the vendor”", [source]) != []
    assert assistant_quotes.unfound("“Backups are encrypted every night … Keys are not rotated”", [source]) == []


def test_the_pieces_of_an_ellipsis_are_in_one_text_in_order():
    first, second = "Backups are encrypted at rest", "keys are rotated every year by the vendor"

    assert assistant_quotes.unfound(f"“{first} … {second}”", [f"{first}.", f"{second}."]) == [f"{first} … {second}"]
    assert assistant_quotes.unfound(f"“{second} … {first}”", [f"{first}; and {second}."]) == [f"{second} … {first}"]
    assert assistant_quotes.unfound(f"“{first} … {second}”", [f"{first}; and {second}."]) == []


@pytest.mark.parametrize(
    ("said", "documents"),
    [
        ("(security teams may enable it on request for any customer)", ["Security.pdf"]),
        ("(Ole5 facts says syslog forwarding is available on request)", ["Ole5 facts.docx"]),
        ("- Ole5 facts, but syslog is offered instead", ["Ole5 facts.docx"]),
    ],
    ids=["a-generic-name", "a-claim-after-the-name", "a-claim-after-a-dash"],
)
def test_a_claim_beside_a_document_name_is_no_citation(said, documents):
    span = f"Direct integration with a customer's SIEM is not supported {said}"

    assert assistant_quotes.unfound(f"> {span}", [SOURCE], documents) == [span]


def test_a_label_holding_a_claim_is_no_citation():
    span = "Ole5 facts.docx confirms Ole5 supports direct SIEM integration: Direct integration with a customer's SIEM"

    assert assistant_quotes.unfound(f"> {span}", [SOURCE], ["Ole5 facts.docx"]) == [span]


def test_what_a_search_says_back_is_not_a_source():
    """The model's own query, said back by the tool, would pass for a document's words.
    Stored conversations still hold searches that said their query back."""
    query = "Ole5 integrates directly with the customer's SIEM over syslog"
    call = AIMessage("", tool_calls=[{"name": "search_policies", "args": {"query": query}, "id": "s1"}])
    said_back = ToolMessage(f"Nothing in the indexed policies matched {query!r}.", tool_call_id="s1")

    assert assistant_quotes.unquoted(f"> {query}", [HumanMessage("Does it?"), call, said_back], []) == [query]


def test_the_reasoning_an_answer_was_drafted_with_is_not_a_source():
    reasoning = "The policy implies that backups are encrypted with keys the vendor holds."
    read_back = ToolMessage(
        "#1  q1 -- Are backups encrypted?\n"
        "      it says: Backups shall be encrypted at rest using AES-256 everywhere.\n"
        f"    {assistant_quotes.RATIONALE} {reasoning}",
        tool_call_id="r1",
        name="read_answers",
    )

    assert assistant_quotes.unquoted(f'The card says "{reasoning}"', [read_back], []) == [reasoning]
    assert (
        assistant_quotes.unquoted(
            'It cites "Backups shall be encrypted at rest using AES-256 everywhere."', [read_back], []
        )
        == []
    )


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


SEARCH = (("search_policies", {"query": "customer SIEM integration"}),)


def _passes(monkeypatch, *replies, script=SEARCH, fails: str = "") -> list[list]:
    """An agent that makes `script`'s calls on its first pass, and replies with the next of `replies` on each.

    A reply may be a message, to carry what it cost. `fails` is how a second
    pass fails: "" not at all, "at-once" before its first chunk, "part-way" after
    it. Returns what every pass was sent.
    """
    sent: list[list] = []

    class Agent:
        def __init__(self, tool_list):
            self.tools = {t.__name__: t for t in tool_list}

        async def astream(self, payload, config=None, stream_mode=None):
            messages = list(payload["messages"])
            sent.append(list(messages))
            if len(sent) == 1:
                for index, (name, args) in enumerate(script):
                    result = self.tools[name](**args)
                    result = await result if hasattr(result, "__await__") else result
                    call = {"name": name, "args": args, "id": f"c{index}"}
                    messages += [
                        AIMessage("", tool_calls=[call]),
                        ToolMessage(result, tool_call_id=f"c{index}", name=name),
                    ]
            elif fails:
                if fails == "part-way":
                    yield {"messages": messages}
                raise RuntimeError("the provider is down")
            reply = replies[len(sent) - 1]
            yield {"messages": messages + [reply if isinstance(reply, AIMessage) else AIMessage(reply)]}

    monkeypatch.setattr(assistant, "_agent", lambda tool_list, **named: Agent(tool_list))
    return sent


@pytest.mark.asyncio
async def test_a_reply_quoting_what_the_source_says_is_sent_as_it_is(user, monkeypatch, searched):
    sent = _passes(monkeypatch, GENUINE)

    turn = await assistant.say(user, assistant.start(user, ""), "Does Ole5 integrate with our SIEM?")

    assert len(sent) == 1
    assert turn.reply == GENUINE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        f"The fact sheet is clear:\n\n> As stated in Ole5 facts.docx, section 5.3: “{NOT_SUPPORTED}”",
        f"الوثيقة واضحة:\n\n> وفقاً لما ورد في مستند Ole5 facts.docx، القسم 5.3: «{NOT_SUPPORTED}»",
    ],
    ids=["en", "ar"],
)
async def test_a_quotation_with_its_attribution_is_sent_in_one_pass(user, monkeypatch, searched, reply):
    """It took a second pass, told the model its own attribution was "in no source",
    and then ended the correct reply with a note calling it a paraphrase."""
    sent = _passes(monkeypatch, reply, reply)

    turn = await assistant.say(user, assistant.start(user, ""), "Does Ole5 integrate with our SIEM?")

    assert len(sent) == 1
    assert turn.reply == reply


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


@pytest.mark.asyncio
async def test_a_clause_found_turns_ago_can_still_be_quoted(user, monkeypatch):
    """The model is shown the last few turns whole and older ones as words only,
    so their clauses were not looked in: a correct re-quotation was asked about
    again, and could be taken back."""
    found = Evidence(source_type=SourceType.GUIDELINE, source_name="Ole5 facts.docx", snippet=SOURCE).model_dump()
    conversation = assistant.start(user, "")
    conversation.messages = [
        HumanMessage("Does Ole5 integrate with our SIEM?"),
        AIMessage("It does not.", additional_kwargs={assistant.UI_KEY: {"steps": [], "sources": [found]}}),
    ]
    for n in range(assistant.TURNS_IN_FULL):
        conversation.messages += [HumanMessage(f"Something else, {n}"), AIMessage(f"Said {n}.")]
    reply = 'As found earlier, the fact sheet says "Direct integration with a customer\'s SIEM is not supported".'
    sent = _passes(monkeypatch, reply, reply, script=())

    turn = await assistant.say(user, conversation, "Remind me what it said?")

    assert len(sent) == 1, "found in one pass"
    assert turn.reply == reply


@pytest.mark.asyncio
async def test_a_reply_may_quote_the_answer_it_just_wrote(user, monkeypatch, tmp_path):
    """Composed by the model rather than copied from the message, the words written
    were in no tool result, so the confirmation quoting them was marked a paraphrase."""
    written = "Yes. All customer data is encrypted at rest with AES-256."
    reply = f'Done. Question 1 now reads: "{written}"'
    script = (("open_questionnaire", {"file_name": ""}), ("write_one_answer", {"text": written, "position": "1"}))
    sent = _passes(monkeypatch, reply, reply, script=script)
    path = shapes.status_and_comment(tmp_path / "HR.xlsx")

    turn = await assistant.say(
        user, assistant.start(user, ""), "Set the first answer to say we encrypt at rest", upload=path
    )

    assert len(sent) == 1
    assert turn.reply == reply


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", ["at-once", "part-way"])
async def test_a_second_pass_that_fails_leaves_the_first_reply_marked(user, monkeypatch, searched, fails):
    """It gave the dropped draft unmarked, or threw a whole reply away for "nothing
    was answered or changed", and the draft's tokens were never counted."""
    draft = AIMessage(DRAFTED, usage_metadata={"input_tokens": 700, "output_tokens": 50, "total_tokens": 750})
    sent = _passes(monkeypatch, draft, fails=fails)

    turn = await assistant.say(user, assistant.start(user, ""), "Does Ole5 integrate with our SIEM?")

    assert len(sent) == 2
    assert not turn.stopped_early
    assert INVENTED in turn.reply.splitlines(), "the first reply, its unfound quotation no longer one"
    assert turn.reply.endswith("so treat it as a paraphrase. The clauses themselves are listed under this reply.")
    assert (turn.input_tokens, turn.output_tokens) == (700, 50), "the dropped draft was paid for, once"
