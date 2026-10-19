"""Whether what an assistant reply sets out as a quotation is in what it could quote from (plan 027, TD-043).

Beside `src/agents/assistant_turn.py`. A reply had quoted a real heading over a
sentence saying the opposite of its clause. So every quotation is looked for,
word for word, in what the person said, the tool results and the clauses found
anywhere in the conversation. One that is in none of them is asked about once,
then shown as a paraphrase with a note. What counts as found, each rule a way
round it that was tried:

* The words outside quotation marks on a blockquote line are a quotation too:
  a quoted heading beside them vouches for nothing.
* An ellipsis may leave words out, never a negation of the words it keeps:
  "is … supported" is not a copy of "is not supported".
* A document's name beside a quotation is no part of it, but a claim beside
  the name is: "(Ole5 facts says syslog is available)" cites nothing.
* Only what a document said counts. A search's own words repeat the model's
  query, and a drafted answer's reasoning is the drafter's.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import cached_property
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.agents.assistant_turn import CORRECTION, UI_KEY, is_correction
from src.logs import get_logger

logger = get_logger(__name__)

QUOTE_MIN_WORDS = 6
"""Shorter quoted spans are titles and terms, not claims about what a document says."""

RATIONALE = "reasoning when it was drafted:"
"""How a tool result introduces the reasoning an answer was drafted with: the drafter's words, not a document's."""

SEARCH_TOOL = "search_policies"
"""Its clauses are among the sources; the rest of what it returns is the model's own query said back."""

_QUOTED = re.compile(
    r'"([^"\n]+)"'  # straight
    r"|\u201c([^\u201c\u201d\n]+)\u201d"  # curly
    r"|\u00ab([^\u00ab\u00bb\n]+)\u00bb"  # guillemets, as Arabic is written
    r"|\u201e([^\u201c\u201d\u201e\n]+)[\u201c\u201d]"  # low-high
)
_QUOTE_LINE = re.compile(r"^[ \t]{0,3}>[ \t]?(.*)$")
_BESIDE = " \t*_,;:\u2014\u2013-"
"""What is trimmed from the words beside a quotation on a blockquote line."""
_ELLIPSIS = re.compile(r"\[\s*(?:\u2026|\.\.\.)\s*\]|\u2026|\.\.\.")
_DIACRITICS = re.compile("[\u064b-\u065f\u0670\u0640]")  # harakat, superscript alef, tatweel
_LETTERS = str.maketrans({**dict.fromkeys("أإآٱ", "ا"), "ى": "ي", **{chr(0x0660 + d): str(d) for d in range(10)}})
_KEPT = re.compile(r"[^\W_]+")
_TRAILING = re.compile(
    r"^(?P<said>.*\S)\s*(?:\((?P<paren>[^()]+)\)|\s[\u2014\u2013-]\s+(?P<dash>[^\u2014\u2013]+?))\W*$"
)
_LABEL = re.compile(r"^(?P<label>[^:]{1,120}):[*_]*\s+(?P<said>.+)$")
_PLACES = frozenset(
    "section sections clause clauses page pages p pp para paragraph source ref annex appendix table "
    "pdf docx doc xlsx xls csv txt md pptx البند القسم صفحة الصفحة المادة الفقرة المصدر".split()
)
"""Words that say where something is: a clause, a page, a file's kind."""
_NEGATIONS = frozenset(
    "not no never none nor neither cannot cant without except unless isnt arent wasnt werent dont doesnt "
    "didnt wont wouldnt shouldnt couldnt mustnt hasnt havent hadnt neednt "
    "لا لم لن ليس ليست غير دون بدون الا عدم ولا ولم ولن وليس سوى".split()
)
_CLAUSE_ENDS = (".", "!", "?", ";", "\u061f", "\u061b")


def quoted_spans(reply: str) -> list[str]:
    """What a reply sets out as a quotation: text in quotation marks, and every blockquote line.

    On a blockquote line with quotation marks in it, the words outside them are
    checked too, each run on its own. A run that only names where the words are
    from is told apart later, when the documents are known.
    """
    spans: list[str] = []
    for line in (reply or "").splitlines():
        spans += [
            next(group for group in found.groups() if group is not None).strip() for found in _QUOTED.finditer(line)
        ]
        blockquote = _QUOTE_LINE.match(line)
        if blockquote:
            beside = _QUOTED.sub("\n", blockquote[1]).split("\n")
            spans += [beside[0].strip()] if len(beside) == 1 else [run.strip(_BESIDE) for run in beside]
    return list(dict.fromkeys(span for span in spans if len(span.split()) >= QUOTE_MIN_WORDS))


def _words(text: str) -> list[str]:
    """Its words as letters and digits, with case, diacritics, letter forms and markdown set aside."""
    text = _DIACRITICS.sub("", unicodedata.normalize("NFKC", text or "").casefold()).translate(_LETTERS)
    return _KEPT.findall(text)


def _plain(text: str) -> str:
    """Letters and digits only, run together.

    Dropping the spaces absorbs what a faithful copy can still differ by: line
    breaks, `**`, a dash of another kind, a word a PDF split in two.
    """
    return "".join(_words(text))


class _Source:
    """One text a quotation may come from: its letters run together, and its words when an ellipsis needs them."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.plain = _plain(text)

    @cached_property
    def words(self) -> list[tuple[int, str, bool]]:
        """Each word's place in `plain`, its letters, and whether a clause ends with it."""
        found: list[tuple[int, str, bool]] = []
        at = 0
        for line in self.text.splitlines():
            line_words = line.split()
            for index, word in enumerate(line_words):
                letters = _plain(word)
                if letters:
                    ends = index == len(line_words) - 1 or word.rstrip("\"'*_)]\u201d\u2019\u00bb").endswith(
                        _CLAUSE_ENDS
                    )
                    found.append((at, letters, ends))
                    at += len(letters)
        return found

    def left_out_a_negation(self, start: int, stop: int) -> bool:
        """Whether the words between `start` and `stop` hold a negation of a clause the quotation keeps.

        A negation in a clause left out whole -- one ended before it and one
        after it -- negates nothing quoted.
        """
        before = [word for word in self.words if word[0] < start]
        gap = [word for word in self.words if start <= word[0] < stop]
        closed = bool(before) and before[-1][2]
        for index, (_at, letters, ends) in enumerate(gap):
            if letters in _NEGATIONS and not (closed and any(word[2] for word in gap[index:])):
                return True
            closed = closed or ends
        return False

    def holds(self, pieces: list[str]) -> bool:
        """Whether every piece is here, in order, with no negation left out between two of them."""
        start = self.plain.find(pieces[0])
        while start >= 0:
            end = start + len(pieces[0])
            for piece in pieces[1:]:
                at = self.plain.find(piece, end)
                if at < 0:
                    return False
                if at > end and self.left_out_a_negation(end, at):
                    break
                end = at + len(piece)
            else:
                return True
            start = self.plain.find(pieces[0], start + 1)
        return False


def _verbatim(text: str, corpus: list[_Source]) -> bool:
    """Whether one source holds every piece of `text` between its ellipses, in order."""
    pieces = [piece for piece in map(_plain, _ELLIPSIS.split(text)) if piece]
    return bool(pieces) and any(source.holds(pieces) for source in corpus)


def _cites(text: str, documents: list[list[str]]) -> bool:
    """Whether `text` only says where a quotation is from: a document's name, a clause or a page, and a word or two.

    "(Ole5 facts.docx, section 5.3)" and "according to Ole5 facts" cite;
    "(Ole5 facts says syslog is available on request)" makes a claim.
    """
    words = _words(text)
    named = False
    for name in documents:
        for at in range(len(words) - len(name), -1, -1):
            if words[at : at + len(name)] == name:
                words[at : at + len(name)], named = [], True
    rest = [word for word in words if word not in _PLACES and not word.isdigit()]
    return (named or len(rest) < len(words)) and len(rest) <= 2


def _found(span: str, corpus: list[_Source], documents: list[list[str]]) -> bool:
    if _verbatim(span, corpus) or _cites(span, documents):
        return True
    trailing, label = _TRAILING.match(span), _LABEL.match(span)
    if trailing and _cites(trailing["paren"] or trailing["dash"] or "", documents):
        return _verbatim(trailing["said"], corpus)
    return bool(label and _cites(label["label"], documents) and _verbatim(label["said"], corpus))


def unfound(reply: str, texts: Iterable[str], documents: Iterable[str] = ()) -> list[str]:
    """The quotations in a reply that none of `texts` contains, word for word.

    Each text is compared on its own, so a quotation cannot be stitched across two.
    `documents` may be named beside a quotation, before or after it, without being part of it.
    """
    spans = quoted_spans(reply)
    if not spans:  # most replies quote nothing
        return []
    corpus = [_Source(text) for text in texts if text]
    names = [_words(str(document).rsplit(".", 1)[0]) for document in documents]
    named = [list(name) for name in dict.fromkeys(tuple(name) for name in names if len("".join(name)) >= 4)]
    return [span for span in spans if not _found(span, corpus, named)]


def _documents_said(text: str) -> str:
    """A tool result without the drafter's reasoning, which is no document's words."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(RATIONALE))


def unquoted(reply: str, messages: Iterable[BaseMessage], sources: list[dict[str, Any]]) -> list[str]:
    """`unfound`, against everything the conversation could quote from.

    What the person said, every tool result and every clause found, in this turn
    and in every earlier one stored, however long ago. Never the assistant's own
    replies, nor a note to the model, which repeats the words; nor what a search
    says beside its clauses, which repeats the model's own query.
    """
    if not quoted_spans(reply):  # most replies quote nothing, and a conversation can be long
        return []
    messages = list(messages)
    shown = [m.additional_kwargs.get(UI_KEY) or {} for m in messages if isinstance(m, AIMessage)]
    found = list(sources) + [source for ui in shown for source in ui.get("sources", [])]
    called = {call.get("id"): call["name"] for m in messages if isinstance(m, AIMessage) for call in m.tool_calls}
    asked = [str(m.content) for m in messages if isinstance(m, HumanMessage) and not is_correction(m)]
    results = [
        m for m in messages if isinstance(m, ToolMessage) and (m.name or called.get(m.tool_call_id)) != SEARCH_TOOL
    ]
    texts = asked + [_documents_said(str(m.content)) for m in results] + [str(s.get("snippet") or "") for s in found]
    return unfound(reply, texts, [str(s.get(field) or "") for s in found for field in ("source_name", "doc_id")])


def without_reply(final: dict[str, Any]) -> dict[str, Any]:
    """The turn so far with its closing reply taken off, to be asked again without it."""
    messages = list((final or {}).get("messages", []))
    while messages and isinstance(messages[-1], AIMessage) and not messages[-1].tool_calls:
        messages.pop()
    return {**(final or {}), "messages": messages}


def quote_correction(spans: list[str]) -> HumanMessage:
    """The note that asks for the reply again, naming the words no source contains."""
    logger.info("assistant.quote_asked_again", spans=len(spans))
    named = "; ".join(f"\u00ab{span[:300]}\u00bb" for span in spans)
    return HumanMessage(
        "[Not from the person: your reply set out these words as a quotation, but they are in no source "
        f"or tool result: {named}. Write the reply again. Quote only words copied exactly from a tool "
        "result, and name the document. If no clause says it, say so plainly.]",
        additional_kwargs={CORRECTION: True},
    )


_NOT_QUOTED = {
    "en": (
        "Note: a passage above was set out as a quotation, but those words are not in any document found, "
        "so treat it as a paraphrase.",
        " The clauses themselves are listed under this reply.",
    ),
    "ar": (
        "ملاحظة: عُرض مقطع أعلاه على أنه اقتباس، لكن كلماته غير موجودة في أي مستند عُثر عليه، "
        "فاعتبره صياغة بتصرف لا اقتباساً حرفياً.",
        " المقاطع نفسها مدرجة تحت هذه الرسالة.",
    ),
}
_MARKS = (('"', '"'), ("\u201c", "\u201d"), ("\u00ab", "\u00bb"), ("\u201e", "\u201c"), ("\u201e", "\u201d"))


def as_paraphrase(reply: str, spans: list[str], language: str, *, listed: bool) -> str:
    """The reply with those spans no longer set out as quotations, and a note saying why.

    A blockquote line holding one is a blockquote no longer, whatever else it holds.
    """
    text = reply
    for span in spans:
        for opening, closing in _MARKS:
            text = re.sub(rf"{re.escape(opening)}\s*{re.escape(span)}\s*{re.escape(closing)}", lambda _: span, text)
        text = re.sub(rf"^[ \t]{{0,3}}>[ \t]?(?=.*{re.escape(span)})", "", text, flags=re.MULTILINE)
    logger.info("assistant.quote_unverified", spans=len(spans))
    note, where = _NOT_QUOTED["ar" if language == "ar" else "en"]
    return f"{text}\n\n{note}{where if listed else ''}"
