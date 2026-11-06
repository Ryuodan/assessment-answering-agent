"""What an assistant turn that stopped part way says (plan 027, TD-043).

Beside `src/agents/assistant_turn.py`, which decides when a turn has asked for
too much. Said from what the turn actually did, each rule a stopped reply that
was wrong:

* "What I did finish is in the answers beside this" after a turn that changed
  nothing: answers are said to be finished only when a tool wrote some, and
  opening a file is said as that.
* "I searched the documents 3 times" after three direct answers, and "nothing
  was answered" after one was drafted: searches and direct answers are counted
  apart.
* A turn that stopped after drafting direct answers lost them, slow and paid
  for, because nothing else shows them: they are relayed, word for word.
* The documents are named rather than their best clause quoted: the highest
  score in the turn this was written for belonged to an unrelated clause.
* "I ran out of room" after the connection to the model service dropped: what
  stopped the turn is said as it was (`cause`), and "one step at a time" is
  advised only when the turn really ran out of steps (the user's test of plan 029).
"""

from __future__ import annotations

from typing import Any

from src.logs import get_logger
from src.models import AnsweredQuestion

logger = get_logger(__name__)

_STOPPED = {
    "en": {
        "changed": "{lead}. What I did finish is in the answers beside this.",
        "opened": "{lead}. I opened {file}, but nothing in it was answered or changed yet.",
        "stopped": "{lead}.",
        "untouched": "{lead}, and nothing was answered or changed.",
        "searched": "I searched the documents {times} without settling it. The clauses found are listed under "
        "this reply, from {documents}.",
        "found_nothing": "I searched the documents {times} and found nothing that matched.",
        "partly_failed": "I searched the documents {times} and found nothing that matched; the search itself "
        "failed {failures}.",
        "failed": "I tried to search the documents {times}, but the search failed.",
        "advice": "Asking about one point at a time usually works better.",
        "nothing": "{lead}, and nothing was changed. {retry}",
        "drafted": "Before it stopped, I drafted {answers}:",
        "flagged": "Flagged for review: {reason}",
    },
    "ar": {
        "changed": "{lead}. ما أنجزته موجود في الإجابات بجانب هذه الرسالة.",
        "opened": "{lead}. فتحت {file}، لكن لم تتم الإجابة عن شيء فيه ولم يتغير فيه شيء بعد.",
        "stopped": "{lead}.",
        "untouched": "{lead}، ولم تتم الإجابة عن شيء ولم يتغير شيء.",
        "searched": "بحثت في المستندات {times} دون أن أصل إلى جواب حاسم. المقاطع التي وجدتها مدرجة تحت هذه "
        "الرسالة، من {documents}.",
        "found_nothing": "بحثت في المستندات {times} ولم أجد شيئاً مطابقاً.",
        "partly_failed": "بحثت في المستندات {times} ولم أجد شيئاً مطابقاً، وتعذّر البحث نفسه {failures}.",
        "failed": "حاولت البحث في المستندات {times}، لكن البحث تعذّر.",
        "advice": "السؤال عن نقطة واحدة في كل مرة يعطي عادةً نتيجة أفضل.",
        "nothing": "{lead}، ولم يتغير شيء. {retry}",
        "drafted": "قبل أن أتوقف، صغت {answers}:",
        "flagged": "بحاجة إلى مراجعة: {reason}",
    },
}
_LEAD = {
    "en": {
        "room": "I ran out of room part way through that",
        "connection": "I lost the connection to the answering service part way through that",
        "busy": "The answering service was too busy to finish that",
        "error": "Something went wrong part way through that",
    },
    "ar": {
        "room": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك",
        "connection": "انقطع الاتصال بخدمة الإجابة قبل أن أُكمل ذلك",
        "busy": "كانت خدمة الإجابة مشغولة فلم أتمكن من إكمال ذلك",
        "error": "حدث خطأ قبل أن أُكمل ذلك",
    },
}
"""How a stopped reply opens, by what stopped the turn (`cause`)."""
_RETRY = {
    "en": {
        "room": "Could you try again, one step at a time?",
        "connection": "Please check the connection and try again.",
        "busy": "Please try again in a minute.",
        "error": "Please try again.",
    },
    "ar": {
        "room": "هل يمكنك المحاولة مرة أخرى، خطوة بخطوة؟",
        "connection": "يرجى التحقق من الاتصال والمحاولة مرة أخرى.",
        "busy": "يرجى المحاولة مرة أخرى بعد دقيقة.",
        "error": "يرجى المحاولة مرة أخرى.",
    },
}
_CONNECTION = frozenset(
    {"APIConnectionError", "APITimeoutError", "ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout",
     "PoolTimeout", "ReadError", "WriteError", "RemoteProtocolError", "ConnectionError", "TimeoutError"}
)  # fmt: skip
"""Error class names, from the model provider's client and httpx, that mean the service could not be reached."""
_TIMES = {"en": ("once", "twice", "{n} times"), "ar": ("مرة واحدة", "مرتين", "{n} مرات")}
_ANSWERS: dict[str, tuple[str, ...]] = {
    "en": ("an answer to one question", "answers to two questions", "answers to {n} questions"),
    "ar": ("إجابة عن سؤال واحد", "إجابتين عن سؤالين", "إجابات عن {n} أسئلة", "إجابات عن {n} سؤالاً"),
}
_AND = {"en": (", ", " and "), "ar": ("، ", " و")}


def cause(failed: BaseException) -> str:
    """What stopped a turn: "room" (it ran out of steps), "connection", "busy" (rate limited) or "error".

    Read from the error and every error it was raised from, by class name, so
    that neither the model provider's client nor httpx is imported here.
    """
    chain: list[BaseException] = []
    error: BaseException | None = failed
    while error is not None and error not in chain:
        chain.append(error)
        error = error.__cause__ or error.__context__
    names = {type(error).__name__ for error in chain}
    if "GraphRecursionError" in names or any("Recursion limit" in str(error) for error in chain):
        found = "room"
    elif "RateLimitError" in names or any(getattr(error, "status_code", None) == 429 for error in chain):
        found = "busy"
    elif names & _CONNECTION or any(isinstance(error, (ConnectionError, TimeoutError)) for error in chain):
        found = "connection"
    else:
        found = "error"
    logger.warning("assistant.stopped", cause=found, error=type(failed).__name__, detail=str(failed)[:300])
    return found


def keep(state: dict[str, Any], result: AnsweredQuestion) -> None:
    """Keep a direct answer as it was handed to the model, for a turn that stops before relaying it."""
    flagged = (result.confidence_reason or "low confidence") if result.needs_review else ""
    state.setdefault("drafted", []).append(
        {"question": result.question.text, "answer": result.answer, "flagged": flagged}
    )


def _counted(n: int, forms: tuple[str, ...]) -> str:
    """`n` of something: one, two, a few, and -- where a fourth form is given, as Arabic needs -- eleven or more."""
    one, two, few, *many = forms
    return one if n == 1 else two if n == 2 else (many[0] if many and n > 10 else few).format(n=n)


def _relayed(drafted: list[dict[str, str]], said: dict[str, str], language: str) -> str:
    """The direct answers drafted, word for word, after what the reply says; "" when there are none."""
    if not drafted:
        return ""
    lines = [said["drafted"].format(answers=_counted(len(drafted), _ANSWERS[language]))]
    for answer in drafted:
        flagged = f"\n{said['flagged'].format(reason=answer['flagged'])}" if answer["flagged"] else ""
        lines.append(f"**{answer['question']}**\n{answer['answer']}{flagged}")
    return "\n\n" + "\n\n".join(lines)


def stopped_reply(state: dict[str, Any], language: str) -> str:
    """What a turn that ran out of steps says, from what this turn actually did."""
    language = "ar" if language == "ar" else "en"
    said = _STOPPED[language]
    stopped_by = state.get("stopped_by") or "room"  # a turn that asked for refused searches ran out of steps
    lead, retry = _LEAD[language][stopped_by], _RETRY[language][stopped_by]
    drafted = _relayed(state.get("drafted") or [], said, language)
    if state.get("changed"):
        return said["changed"].format(lead=lead) + drafted
    opened = state.get("opened") or ""
    head = (said["opened"].format(lead=lead, file=opened) if opened
            else said["stopped" if drafted else "untouched"].format(lead=lead))  # fmt: skip
    searches = [entry for entry in state.get("searches") or [] if entry["kind"] == "search"]
    if not searches and not drafted:
        return f"{head} {retry}" if opened else said["nothing"].format(lead=lead, retry=retry)
    body = _searched(state, searches, said, language) if searches else ""
    advice = said["advice"] if stopped_by == "room" else retry
    return " ".join(part for part in (head, body, advice) if part) + drafted


def _searched(state: dict[str, Any], searches: list[dict[str, str]], said: dict[str, str], language: str) -> str:
    """What the searches found. One that failed is not said to have found nothing."""
    times = _counted(len(searches), _TIMES[language])
    failed = sum(entry["outcome"] == "failed" for entry in searches)
    sources = sorted(state.get("sources") or [], key=lambda source: not source.get("product_id"))  # its own first
    names = list(dict.fromkeys(str(source["source_name"]) for source in sources if source.get("source_name")))[:4]
    if names and any(entry["outcome"] == "found" for entry in searches):
        comma, conjunction = _AND[language]
        documents = comma.join(names[:-1]) + conjunction + names[-1] if len(names) > 1 else names[0]
        return said["searched"].format(times=times, documents=documents)
    if failed == len(searches):
        return said["failed"].format(times=times)
    failures = _counted(failed, _TIMES[language])
    return said["partly_failed" if failed else "found_nothing"].format(times=times, failures=failures)
