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
"""

from __future__ import annotations

from typing import Any

from src.models import AnsweredQuestion

_STOPPED = {
    "en": {
        "changed": "I ran out of room part way through that. What I did finish is in the answers beside this.",
        "opened": "I ran out of room part way through that. I opened {file}, but nothing in it was answered "
        "or changed yet.",
        "stopped": "I ran out of room part way through that.",
        "untouched": "I ran out of room part way through that, and nothing was answered or changed.",
        "searched": "I searched the documents {times} without settling it. The clauses found are listed under "
        "this reply, from {documents}.",
        "found_nothing": "I searched the documents {times} and found nothing that matched.",
        "partly_failed": "I searched the documents {times} and found nothing that matched; the search itself "
        "failed {failures}.",
        "failed": "I tried to search the documents {times}, but the search failed.",
        "advice": "Asking about one point at a time usually works better.",
        "retry": "Could you try again, one step at a time?",
        "nothing": "I ran out of room part way through that, and nothing was changed. "
        "Could you try again, one step at a time?",
        "drafted": "Before it stopped, I drafted {answers}:",
        "flagged": "Flagged for review: {reason}",
    },
    "ar": {
        "changed": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك. ما أنجزته موجود في الإجابات بجانب هذه الرسالة.",
        "opened": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك. فتحت {file}، لكن لم تتم الإجابة عن شيء فيه "
        "ولم يتغير فيه شيء بعد.",
        "stopped": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك.",
        "untouched": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك، ولم تتم الإجابة عن شيء ولم يتغير شيء.",
        "searched": "بحثت في المستندات {times} دون أن أصل إلى جواب حاسم. المقاطع التي وجدتها مدرجة تحت هذه "
        "الرسالة، من {documents}.",
        "found_nothing": "بحثت في المستندات {times} ولم أجد شيئاً مطابقاً.",
        "partly_failed": "بحثت في المستندات {times} ولم أجد شيئاً مطابقاً، وتعذّر البحث نفسه {failures}.",
        "failed": "حاولت البحث في المستندات {times}، لكن البحث تعذّر.",
        "advice": "السؤال عن نقطة واحدة في كل مرة يعطي عادةً نتيجة أفضل.",
        "retry": "هل يمكنك المحاولة مرة أخرى، خطوة بخطوة؟",
        "nothing": "نفدت المساحة المتاحة لي قبل أن أُكمل ذلك، ولم يتغير شيء. هل يمكنك المحاولة مرة أخرى، خطوة بخطوة؟",
        "drafted": "قبل أن أتوقف، صغت {answers}:",
        "flagged": "بحاجة إلى مراجعة: {reason}",
    },
}
_TIMES = {"en": ("once", "twice", "{n} times"), "ar": ("مرة واحدة", "مرتين", "{n} مرات")}
_ANSWERS: dict[str, tuple[str, ...]] = {
    "en": ("an answer to one question", "answers to two questions", "answers to {n} questions"),
    "ar": ("إجابة عن سؤال واحد", "إجابتين عن سؤالين", "إجابات عن {n} أسئلة", "إجابات عن {n} سؤالاً"),
}
_AND = {"en": (", ", " and "), "ar": ("، ", " و")}


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
    drafted = _relayed(state.get("drafted") or [], said, language)
    if state.get("changed"):
        return said["changed"] + drafted
    opened = state.get("opened") or ""
    head = said["opened"].format(file=opened) if opened else said["stopped" if drafted else "untouched"]
    searches = [entry for entry in state.get("searches") or [] if entry["kind"] == "search"]
    if not searches and not drafted:
        return f"{head} {said['retry']}" if opened else said["nothing"]
    body = _searched(state, searches, said, language) if searches else ""
    return " ".join(part for part in (head, body, said["advice"]) if part) + drafted


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
