"""A question answered in the chat, shown as its answer card (plan 030).

Beside `src/agents/assistant.py`, whose `answer_directly` drafts it through the
pipeline a questionnaire's rows go through, and whose `read_answers` reads an
answer's sources back with `sources_of`. Each rule is a turn that went wrong:

* The model was handed the drafted answer and wrote the reply in its own words:
  six of twelve stored direct answers were paraphrased, and in one Arabic test
  it contradicted a correct draft, reading the 700-character excerpts of its
  clauses. Each answer now rides on the reply as the card the Workbench draws,
  word for word, with its status, its confidence and the clauses it cites. The
  model is told so, and its own words lead into the card rather than restate it.
* The sources under the reply were the first six chunks the answer carried,
  not the clauses it cited.
"""

from __future__ import annotations

from typing import Any

from src.agents import assistant_quotes, assistant_stopped, assistant_turn
from src.models import AnsweredQuestion, Evidence

SOURCE_CHARS = 700
"""How much of each cited clause is read back when somebody asks what an answer
was based on. Enough to quote the sentence that matters; a whole chunk for every
source of five answers would crowd out the conversation."""

ON_SCREEN = "answer, on the person's screen as a card exactly as drafted (do not restate it):"
"""How the tool result introduces a drafted answer: what it says, and that the person already sees it."""

LEAD_IN = (
    "Each answer above is shown to the person under your reply as an answer card: word for word, with its "
    "status, its confidence and the clauses it cites. Your reply is one short sentence that leads into the "
    "card. Do not restate, translate, summarise or reword an answer, and do not list its sources: the card "
    "shows them. If one is flagged for review or could not be answered, say so and why."
)
"""Said in the result, where the model decides what to reply, and not only in the prompt."""


def cited(result: AnsweredQuestion) -> list[Evidence]:
    """The clauses an answer cites: those of its evidence that one of its citations names, in order."""
    named = set(result.citations)
    return [item for item in result.evidence if item.locator in named]


def card(result: AnsweredQuestion) -> dict[str, Any]:
    """An answer as the page's card draws it: all it says, with only the clauses it cites."""
    return {**result.model_dump(mode="json"), "evidence": [item.model_dump(mode="json") for item in cited(result)]}


def handed_back(state: dict[str, Any], drafted: list[AnsweredQuestion]) -> str:
    """What `answer_directly` tells the model. Each answer's card and cited clauses are kept for the reply."""
    lines: list[str] = []
    for result in drafted:
        state.setdefault("direct_answers", []).append(card(result))
        lines.append(result.question.text)
        if result.error:
            lines.append(f"    could not be answered: {result.error}")
            continue
        lines.append(f"    {ON_SCREEN} {result.answer}")
        assistant_stopped.keep(state, result)  # relayed by a turn that stops before the model can
        if result.drafted:
            lines.append("    (reworded to your preferences)")
        if result.needs_review:
            lines.append(f"    flagged for review: {assistant_stopped.held_because(result)}")
        # What it cites, in the reply's own history, so "where did that come
        # from" a few messages later is answered from this and not from a new
        # search that finds something similar.
        lines.extend(sources_of(result.model_dump(), detailed=True))
        assistant_turn.add_sources(state, (item.model_dump() for item in cited(result)))
    return "\n".join([*lines, LEAD_IN])


def sources_of(answered: dict[str, Any], *, detailed: bool) -> list[str]:
    """What one answer was written from, exactly as its card shows it.

    The citations are the answer's own list and the text beside each is the
    chunk the drafter was given, so "which sources did you use" is answered
    from the record rather than re-searched. Searching again returned a
    similar list, not the same one -- and a person comparing the reply with
    the card saw sources the answer never cited.
    """
    # Only when asked. A plain read-back is the answer and its state: with a
    # list of sources after it, an answer asked for in Arabic came back
    # translated rather than quoted more often -- two runs in three against
    # one in three without.
    if not detailed:
        return []
    citations = [c for c in (answered.get("citations") or []) if c]

    unused = list(answered.get("evidence") or [])  # each citation takes the next of its name, as the card does
    lines = [] if citations else ["    sources cited: none"]
    for citation in citations:
        item = next((e for e in unused if (e.get("locator") or e.get("source_name") or "") == citation), None)
        if item is not None:  # two remembered answers can share a name; each is listed (plan 027)
            unused.remove(item)
        else:
            lines.append(f"    cited: {citation} -- named in the answer; the text of it was not kept")
            continue
        kind = (
            "a previous answer of ours"
            if item.get("source_type") == "prior_answer"
            else "a law or external requirement, not our own policy"
            if item.get("authority") == "external"
            else "our own policy"
        )
        said = " ".join(str(item.get("snippet") or "").split())
        if len(said) > SOURCE_CHARS:
            said = said[:SOURCE_CHARS].rsplit(" ", 1)[0] + " ..."
        lines.append(f"    cited: {citation} ({kind})")
        lines.append(f"      it says: {said}")
    if (answered.get("rationale") or "").strip():  # on one line, which a quotation may not come from
        lines.append(f"    {assistant_quotes.RATIONALE} {' '.join(answered['rationale'].split())[:800]}")
    return lines
