"""What one assistant turn may do, and what its reply may claim (plan 027, TD-043).

Beside `src/agents/assistant.py`, which re-exports `tidy_reply`, `without_repetition`,
`CORRECTION` and `UI_KEY` from here. Each rule is a turn that went wrong:

* A turn searches at most three times, and reads each clause whole. Shown 400
  characters of each, the model never saw the sentence that answered it, and
  searched nineteen times in quoted phrases until the turn ran out of steps.
* Its sources are listed once: those searches listed 114 clauses, 14 distinct.
* A turn that stopped says what it did, not "What I did finish is in the
  answers beside this" after a turn that changed nothing.
* A quotation no source contains is asked about once, then shown as a
  paraphrase with a note. A reply had quoted a real heading over a sentence
  saying the opposite of its clause.
* A knowledge-base document is not opened as a questionnaire, and the model is
  told why, rather than to have the person attach it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src import service
from src.identity import User
from src.logs import get_logger

logger = get_logger(__name__)

SEARCHES_PER_TURN = 3
"""Searches one turn may make. One usually settles a question; the third is the last."""

CLAUSE_CHARS = 1500
"""How much of each clause a search shows the model: all of one, at the chunk size of 1,200."""

QUOTE_MIN_WORDS = 6
"""Shorter quoted spans are titles and terms, not claims about what a document says."""

FOR_THIS_PRODUCT = "FOR THIS PRODUCT"
"""The mark on a product's own clauses, as the drafter's sources carry it (TD-040)."""

CORRECTION = "correction"
"""Marks a note to the model about its last step. It is sent, never stored or shown."""

UI_KEY = "ui"
"""Where a turn's steps and sources ride on its reply message.

`additional_kwargs` is serialised with the message, so what the interface draws
under a reply is stored with the reply rather than beside it, and the two
cannot drift apart.
"""


def is_correction(message: BaseMessage) -> bool:
    return bool((getattr(message, "additional_kwargs", None) or {}).get(CORRECTION))


# --- searching ------------------------------------------------------------------------


def _normalised(query: str) -> str:
    return " ".join(re.sub(r"[\"'\u201c\u201d\u2018\u2019\u00ab\u00bb\u201e]", " ", query or "").casefold().split())


def search_refused(state: dict[str, Any], query: str) -> str:
    """Why this search is not run, or "" when it may be, counting it.

    Before anything is awaited, so searches asked for at once cannot all pass the limit together.
    """
    searched: list[str] = state.setdefault("searches", [])
    if _normalised(query) in {_normalised(earlier) for earlier in searched}:
        return "Already searched for that this turn; its clauses are above. Reply from them."
    if len(searched) >= SEARCHES_PER_TURN:
        made = "; ".join(repr(earlier) for earlier in searched)
        return (
            f"Not searched: this turn has already searched {len(searched)} times ({made}), which is the "
            "limit. Do not search again. Reply now from the clauses those searches returned: quote the "
            "sentence that answers the question word for word and name its document. If none says it, "
            "say plainly that the documents found do not state it, and name the closest clause."
        )
    searched.append(query)
    return ""


def clauses(hits: list[dict[str, Any]]) -> str:
    """Search hits as the model reads them: each clause whole, the product's own marked."""
    shown = []
    for hit in hits:
        where = str(hit.get("locator") or hit.get("source_name") or "")
        text = str(hit.get("snippet") or "").strip()
        if len(text) > CLAUSE_CHARS:
            text = text[:CLAUSE_CHARS].rsplit(" ", 1)[0] + " ..."
        shown.append(f"[{where}, {FOR_THIS_PRODUCT}] {text}" if hit.get("product_id") else f"[{where}] {text}")
    return "\n\n".join(shown)


def source_key(item: dict[str, Any]) -> tuple[str, ...]:
    """One clause, whichever search found it: its knowledge base, kind, document, chunk and entry.

    Not the locator, which three chunks of a fact sheet with no clause numbers share.
    """
    fields = ("product_id", "source_type", "source_name", "chunk", "entry_id")
    return tuple(str(getattr(item.get(name), "value", item.get(name, ""))) for name in fields)


def add_sources(state: dict[str, Any], items: Iterable[dict[str, Any]]) -> None:
    """Put clauses under the reply, each once however often it was found."""
    sources: list[dict[str, Any]] = state.setdefault("sources", [])
    seen = {source_key(source) for source in sources}
    for item in items:
        if source_key(item) not in seen:
            seen.add(source_key(item))
            sources.append(item)


# --- a knowledge-base document is not a questionnaire ---------------------------------


def nothing_attached(user: User, state: dict[str, Any], file_name: str) -> str:
    """What `open_questionnaire` says when no file came with the message.

    Told to "ask the person to attach the questionnaire" when it had tried to open a knowledge-base document,
    the model asked them to attach a document the knowledge base already held.
    """
    name = (file_name or "").strip()
    if name and _a_knowledge_base_document(user, state, name):
        return (
            f"Nothing was opened. {name!r} is a document in the knowledge base, not a questionnaire attached "
            "to this message, and open_questionnaire cannot read it. To tell the person what it says, quote "
            "the sentences search_policies returned from it, word for word, and name it. If they do not "
            "cover the question, say so. Do not ask them to attach it."
        )
    return (
        "Nothing was opened: no file is attached to this message. open_questionnaire reads only a "
        "questionnaire the person attaches. It cannot open a knowledge-base document or a file named in "
        "conversation. If they asked what a document says, answer from search_policies. If they meant to "
        "send a questionnaire, ask them to attach it."
    )


def _a_knowledge_base_document(user: User, state: dict[str, Any], name: str) -> bool:
    wanted = name.casefold()
    if any(str(source.get("source_name") or "").casefold() == wanted for source in state.get("sources") or []):
        return True
    try:  # the shared knowledge base, and the chat's product's
        listed = [service.knowledge_stats(user.team_id, product_id=p) for p in {"", state.get("product_id") or ""}]
    except Exception as failed:  # noqa: BLE001 - unknown, so the plain refusal; never a failed turn
        logger.warning("assistant.knowledge_unreadable", error=str(failed) or repr(failed))
        return False
    return any(str(source.get("name") or "").casefold() == wanted for stats in listed for source in stats["sources"])


# --- a turn that stopped part way -----------------------------------------------------

_STOPPED = {
    "en": {
        "changed": "I ran out of room part way through that. What I did finish is in the answers beside this.",
        "searched": "I ran out of room part way through that, and nothing was answered or changed. "
        "I searched the documents {times} without settling it. The clauses found are listed under this "
        "reply, from {documents}. Asking about one point at a time usually works better.",
        "found_nothing": "I ran out of room part way through that, and nothing was answered or changed. "
        "I searched the documents {times} and found nothing that matched. "
        "Asking about one point at a time usually works better.",
        "nothing": "I ran out of room part way through that, and nothing was changed. "
        "Could you try again, one step at a time?",
    },
    "ar": {
        "changed": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك. ما أنجزته موجود في الإجابات بجانب هذه الرسالة.",
        "searched": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك، ولم تتم الإجابة عن شيء ولم يتغير شيء. "
        "بحثت في المستندات {times} دون أن أصل إلى جواب حاسم. المقاطع التي وجدتها مدرجة تحت هذه الرسالة، "
        "من {documents}. السؤال عن نقطة واحدة في كل مرة يعطي عادةً نتيجة أفضل.",
        "found_nothing": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك، ولم تتم الإجابة عن شيء ولم يتغير شيء. "
        "بحثت في المستندات {times} ولم أجد شيئاً مطابقاً. السؤال عن نقطة واحدة في كل مرة يعطي عادةً نتيجة أفضل.",
        "nothing": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك، ولم يتغير شيء. هل يمكنك المحاولة مرة أخرى، خطوة بخطوة؟",
    },
}
_TIMES = {"en": ("once", "twice", "{n} times"), "ar": ("مرة واحدة", "مرتين", "{n} مرات")}
_AND = {"en": (", ", " and "), "ar": ("، ", " و")}


def stopped_reply(state: dict[str, Any], language: str) -> str:
    """What a turn that ran out of steps says, from what this turn actually did.

    The documents are named rather than their best clause quoted: the highest
    score in the turn this was written for belonged to an unrelated clause.
    """
    language = "ar" if language == "ar" else "en"
    said = _STOPPED[language]
    if state.get("refreshed"):
        return said["changed"]
    searches = len(state.get("searches") or [])
    if not searches:
        return said["nothing"]
    once, twice, more = _TIMES[language]
    times = once if searches == 1 else twice if searches == 2 else more.format(n=searches)
    sources = sorted(state.get("sources") or [], key=lambda source: not source.get("product_id"))  # its own first
    names = list(dict.fromkeys(str(source["source_name"]) for source in sources if source.get("source_name")))[:4]
    if not names:
        return said["found_nothing"].format(times=times)
    comma, conjunction = _AND[language]
    documents = comma.join(names[:-1]) + conjunction + names[-1] if len(names) > 1 else names[0]
    return said["searched"].format(times=times, documents=documents)


# --- the reply as a person should read it ---------------------------------------------

_JOINED = re.compile(r"(?<=[.!?\u061f])(?=[A-Z\u0600-\u06FF*\"'])")
_WORD = re.compile(r"[\w\u0600-\u06FF]+")


def without_repetition(text: str) -> str:
    """A reply once, when the model wrote it twice back to back.

    Seen on the real model three times in twenty turns of one conversation:
    "The background-check question has been set aside and will not be written
    to the file.The background-check question has been set aside and will be
    excluded from the final submission." -- one message, two phrasings of the
    same sentence, joined with no space, which is what two of the model's output
    channels concatenated look like. Only a join like that is considered, and
    only when the two halves are mostly the same words, so two different
    sentences that happen to lack a space are left alone. The later half is kept.

    Four in ten words shared is the bar: "…has been restored to the
    questionnaire.The background-check question (question 4) is now back in the
    questionnaire." shares 43%, and two unrelated sentences share almost none.
    """
    text = (text or "").strip()
    for match in _JOINED.finditer(text):
        head, tail = text[: match.start()].strip(), text[match.start() :].strip()
        first, second = set(_WORD.findall(head.casefold())), set(_WORD.findall(tail.casefold()))
        if len(first) < 4 or len(second) < 4:
            continue
        if len(first & second) / len(first | second) >= 0.4:
            return tail
    return text


_CITATION_MARK = re.compile(r"\s*\u3010[^\u3011]{0,120}\u3011")


def tidy_reply(text: str, earlier: list[str] | tuple[str, ...] = ()) -> str:
    """The reply as a person should read it.

    Three things the model adds that nobody should see, each found reading a
    long conversation turn by turn:

    * a copy of a previous reply appended to this one -- "The background-check
      question has been set aside…" followed, with no space, by the last turn's
      "No answers are currently flagged…";
    * the same reply written twice in two phrasings (see `without_repetition`);
    * a citation marker in the model's own format, "【search_policies result #2】",
      which points at nothing a person can open.
    """
    text = _CITATION_MARK.sub("", text or "").strip()
    for before in earlier:
        before = (before or "").strip()
        if len(before) >= 20 and before in text and text != before:
            text = text.replace(before, "", 1).strip()
    return without_repetition(text)


# --- quotations -----------------------------------------------------------------------

_QUOTED = re.compile(
    r'"([^"\n]+)"'  # straight
    r"|\u201c([^\u201c\u201d\n]+)\u201d"  # curly
    r"|\u00ab([^\u00ab\u00bb\n]+)\u00bb"  # guillemets, as Arabic is written
    r"|\u201e([^\u201c\u201d\u201e\n]+)[\u201c\u201d]"  # low-high
)
_QUOTE_LINE = re.compile(r"^[ \t]{0,3}>[ \t]?(.*)$")
_ELLIPSIS = re.compile(r"\[\s*(?:\u2026|\.\.\.)\s*\]|\u2026|\.\.\.")
_DIACRITICS = re.compile("[\u064b-\u065f\u0670\u0640]")  # harakat, superscript alef, tatweel
_LETTERS = str.maketrans({**dict.fromkeys("أإآٱ", "ا"), "ى": "ي", **{chr(0x0660 + d): str(d) for d in range(10)}})
_KEPT = re.compile(r"[^\W_]+")
_TRAILING = re.compile(
    r"^(?P<said>.*\S)\s*(?:\((?P<paren>[^()]+)\)|\s[\u2014\u2013-]\s+(?P<dash>[^\u2014\u2013]+?))\W*$"
)
_LABEL = re.compile(r"^(?P<label>[^:]{1,120}):[*_]*\s+(?P<said>.+)$")
_LOCATION = re.compile(r"^(?:(?:section|clause|pages?|p|source|ref|البند|القسم|صفحة)\b|[\u00a7\d.,:\u2013\s-])+$", re.I)


def quoted_spans(reply: str) -> list[str]:
    """What a reply sets out as a quotation: text in quotation marks, and every blockquote line.

    A blockquote line with quotation marks inside it is checked by those alone,
    so the document it is attributed to is not taken for part of the quotation.
    """
    spans: list[str] = []
    for line in (reply or "").splitlines():
        inner = [next(group for group in found.groups() if group is not None) for found in _QUOTED.finditer(line)]
        blockquote = _QUOTE_LINE.match(line)
        spans += [span.strip() for span in (inner or ([blockquote[1]] if blockquote else []))]
    return list(dict.fromkeys(span for span in spans if len(span.split()) >= QUOTE_MIN_WORDS))


def _plain(text: str) -> str:
    """Letters and digits only, with case, diacritics, letter forms, spacing and markdown set aside.

    Dropping the spaces absorbs what a faithful copy can still differ by: line
    breaks, `**`, a dash of another kind, a word a PDF split in two.
    """
    text = _DIACRITICS.sub("", unicodedata.normalize("NFKC", text or "").casefold()).translate(_LETTERS)
    return "".join(_KEPT.findall(text))


def _verbatim(text: str, corpus: str) -> bool:
    """Every stretch of three or more words, between ellipses, is in the corpus."""
    return all(_plain(piece) in corpus for piece in _ELLIPSIS.split(text) if len(piece.split()) >= 3)


def _cites(text: str, documents: list[str]) -> bool:
    """Whether `text` only says where a quotation is from: a document's name, or a clause or page."""
    plain = _plain(text)
    return bool(_LOCATION.match(text.strip("*_ ").strip())) or any(name in plain for name in documents)


def _found(span: str, corpus: str, documents: list[str]) -> bool:
    if _verbatim(span, corpus):
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
    corpus = "\n".join(_plain(text) for text in texts) if spans else ""  # most replies quote nothing
    names = [name for name in (_plain(str(document).rsplit(".", 1)[0]) for document in documents) if len(name) >= 4]
    return [span for span in spans if not _found(span, corpus, names)]


def unquoted(reply: str, final: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    """`unfound`, against what this turn could quote from: what the person said, every
    tool result and every clause found, this turn's and those under earlier replies.
    Never the assistant's own replies, nor a note to the model, which repeats the words.
    """
    messages = list((final or {}).get("messages", []))
    shown = [m.additional_kwargs.get(UI_KEY) or {} for m in messages if isinstance(m, AIMessage)]
    found = list(sources) + [source for ui in shown for source in ui.get("sources", [])]
    said = [m for m in messages if isinstance(m, (HumanMessage, ToolMessage)) and not is_correction(m)]
    texts = [str(m.content) for m in said] + [str(source.get("snippet") or "") for source in found]
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
    """The reply with those spans no longer set out as quotations, and a note saying why."""
    text = reply
    for span in spans:
        for opening, closing in _MARKS:
            text = re.sub(rf"{re.escape(opening)}\s*{re.escape(span)}\s*{re.escape(closing)}", lambda _: span, text)
        text = re.sub(rf"^[ \t]{{0,3}}>[ \t]?\s*{re.escape(span)}[ \t]*$", lambda _: span, text, flags=re.MULTILINE)
    logger.info("assistant.quote_unverified", spans=len(spans))
    note, where = _NOT_QUOTED["ar" if language == "ar" else "en"]
    return f"{text}\n\n{note}{where if listed else ''}"
