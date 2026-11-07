"""The small slice of Markdown the drafter actually writes.

Answers come back with emphasis and lists — 153 bold spans, 139 bullets and 78
numbered items across one 42-question run — because that is how a model writes
when asked to enumerate several requirements. Left as raw text those asterisks
are noise in an assessment response; stripped out, the list structure goes with
them, and on a question with nine obligations the structure is most of the
answer's value.

So the markup is parsed rather than removed, once, here, and each surface
renders the result its own way: ReportLab flowables for the PDF, DOM nodes for
the web interface. Deliberately not a Markdown library — the input is one
model's output, four constructs wide, and a parser for the whole language would
be a dependency and a security surface bought for nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# **bold** and __bold__. Non-greedy, and it will not span a blank line, so an
# unclosed asterisk cannot swallow the rest of the answer.
_BOLD = re.compile(r"(?<!\w)(\*\*|__)(?=\S)(.+?)(?<=\S)\1(?!\w)", re.DOTALL)

# Source indices the drafter sometimes drops into its prose — "…(see §3.1.5)【3】"
# — referring to the [n] numbering of the prompt's sources block. That numbering
# is internal: the reader never sees the block, so the marker points at nothing.
# The clause citation beside it is the real reference and survives.
#
# The optional `†source` tail is the shape this model reaches for unprompted:
# 【1†source】【2†source】, four of them in a row, went into an answer measured on
# the held-out set. Without it the brackets were stripped and the word "source"
# was left standing in the sentence.
_SOURCE_MARKER = re.compile(r"[【〔]\s*\d{1,2}\s*(?:†[^】〕]*)?[】〕]")
# The prompt's own numbering, which it forbids in the answer and models write
# anyway: measured 2026-10-05 in 115 of 2,121 stored answers (5.4%) and 255 of
# 2,716 evaluated ones, against 0 of 698 answers people wrote (TD-024). `[3]`,
# `[1, 2]`, `[2-4]`; not `[1](url)`, and not after a word that makes it a real
# reference -- "annex [1]", "section [2]" -- which is what `_REAL_REFERENCE` keeps.
_BRACKET_MARKER = re.compile(r"\[\s*\d{1,2}(?:\s*[,–\-]\s*\d{1,2})*\s*\](?!\()")
_REAL_REFERENCE = re.compile(
    r"(?i)\b(?:annex|appendix|section|clause|article|item|figure|table|footnote|note|schedule|exhibit|"
    r"attachment|paragraph|chapter|step)\s*$"
)

# A reasoning model's thinking, which some providers return inside the message
# rather than beside it. Groq's `reasoning_format` defaults to "raw", which
# means exactly this -- so pointing the deployment at a reasoning model put
# "<think>The user wants me to rewrite the answer..." where the answer goes.
_REASONING = re.compile(r"<\s*(think|thinking|reasoning)\s*>.*?<\s*/\s*\1\s*>", re.DOTALL | re.IGNORECASE)
_REASONING_OPENS = re.compile(r"<\s*(?:think|thinking|reasoning)\s*>", re.IGNORECASE)
_BULLET = re.compile(r"^\s*[-*•]\s+(?P<text>.+)$")
_NUMBERED = re.compile(r"^\s*(?P<marker>\d{1,3})[.)]\s+(?P<text>.+)$")
_HEADING = re.compile(r"^\s*#{1,6}\s+(?P<text>.+?)\s*#*$")


@dataclass(frozen=True)
class Block:
    """One rendered line of an answer."""

    kind: str  # "paragraph" | "bullet" | "number" | "heading"
    text: str
    marker: str = ""

    @property
    def spans(self) -> list[tuple[str, bool]]:
        """The line split into (text, is_bold) runs, in order."""
        return _split_bold(self.text)


def _split_bold(text: str) -> list[tuple[str, bool]]:
    spans: list[tuple[str, bool]] = []
    position = 0
    for match in _BOLD.finditer(text):
        if match.start() > position:
            spans.append((text[position : match.start()], False))
        spans.append((match.group(2), True))
        position = match.end()
    if position < len(text):
        spans.append((text[position:], False))
    return [span for span in spans if span[0]] or [("", False)]


# Brackets holding nothing once the numbers are out, or only what joined them:
# commas, "and", "see". A bracket with any other word in it stays.
_LEFT_EMPTY = re.compile(r"[ \t]*[(（][\s,،;:]*(?:(?:and|or|see(?:\s+also)?|و)[\s,،;:]*)*[)）]", re.IGNORECASE)


def _unless_a_real_reference(match: re.Match[str]) -> str:
    """'' for a leaked source number; the text itself for "annex [1]" and the like."""
    before = match.string[max(0, match.start() - 30) : match.start()]
    return match.group(0) if _REAL_REFERENCE.search(before) else ""


def strip_source_markers(text: str) -> str:
    """Remove internal source indices the drafter leaked into the prose."""
    original = text or ""
    cleaned = _SOURCE_MARKER.sub("", original)
    cleaned = _BRACKET_MARKER.sub(_unless_a_real_reference, cleaned)
    if cleaned != original:
        # "tested quarterly ([3])" left "tested quarterly ()", and "([4], [5])" left
        # "(,)", in a customer's file (TD-073). Only after a number was taken out.
        cleaned = _LEFT_EMPTY.sub("", cleaned)
    # The marker usually trails a closing bracket or a space; tidy what is left
    # so the sentence does not end " ." or carry a double space.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r"[ \t]+([.,;:)])", lambda match: match.group(1), cleaned)


def parse(text: str) -> list[Block]:
    """Split an answer into rendered lines, keeping list structure."""
    blocks: list[Block] = []
    for raw in strip_source_markers(text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        heading = _HEADING.match(line)
        if heading:
            blocks.append(Block("heading", heading.group("text")))
            continue

        numbered = _NUMBERED.match(line)
        if numbered:
            blocks.append(Block("number", numbered.group("text"), numbered.group("marker")))
            continue

        bullet = _BULLET.match(line)
        if bullet:
            blocks.append(Block("bullet", bullet.group("text")))
            continue

        blocks.append(Block("paragraph", line.strip()))
    return blocks


def without_reasoning(text: str) -> str:
    """The answer, with any thinking the model left in it taken out.

    Reasoning models write their working into the message when the provider is
    asked for it "raw", and Groq asks for raw unless told otherwise. What comes
    back then is `<think>...</think>` followed by the answer -- or, when the
    reply was cut short, an opening tag and nothing after it, in which case
    there is no answer in the message at all and "" is the honest result: the
    caller keeps what it already had rather than writing thinking into a file.

    The right fix is to ask the provider for the reasoning separately, which
    `llm.chat_llm` now does. This is the second lock: a provider that ignores
    the setting, a gateway that drops it, or a model that emits the tags anyway
    would otherwise put the model's working in front of a customer.
    """
    cleaned = _REASONING.sub("", text or "")
    opened = _REASONING_OPENS.search(cleaned)
    if opened:  # an unterminated block: everything after it is thinking
        cleaned = cleaned[: opened.start()]
    return cleaned.strip()


def to_cell_text(text: str) -> str:
    """The answer as it should read inside a questionnaire's own cell.

    A spreadsheet cell and a Word table cell show text, not Markdown, and the
    drafter writes Markdown: the Fabrikam questionnaire went back to its customer
    with "**Identifiers** –" in a cell, asterisks and all. Emphasis goes, bullets
    become a real bullet character, a heading becomes its words -- and unlike
    `to_plain_text` a blank line between paragraphs stays, because in a cell
    holding four paragraphs it is most of what makes them readable.
    """
    lines: list[str] = []
    for raw in strip_source_markers(without_reasoning(text)).splitlines():
        line = raw.rstrip()
        if not line.strip():
            if lines and lines[-1] != "":
                lines.append("")
            continue
        heading = _HEADING.match(line)
        bullet = _BULLET.match(line)
        numbered = _NUMBERED.match(line)
        if heading:
            body, prefix = heading.group("text"), ""
        elif numbered:
            body, prefix = numbered.group("text"), numbered.group("marker") + ". "
        elif bullet:
            body, prefix = bullet.group("text"), "• "
        else:
            body, prefix = line.strip(), ""
        lines.append(prefix + "".join(span for span, _ in _split_bold(body)))
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def to_plain_text(text: str) -> str:
    """The answer with its markup resolved, for CSV and other flat outputs.

    Emphasis disappears, list structure survives as a real bullet character —
    a spreadsheet cell has no way to show bold, but it can show a list.
    """
    lines = []
    for block in parse(text):
        body = "".join(span for span, _ in block.spans)
        if block.kind == "bullet":
            lines.append(f"• {body}")
        elif block.kind == "number":
            lines.append(f"{block.marker}. {body}")
        else:
            lines.append(body)
    return "\n".join(lines)


def same_wording(asked: str, question: str) -> bool:
    """Whether two questions are the same words, case, punctuation, spacing and digits' script aside (plan 034).

    Deliberately exact. Questions that read alike and are not the same -- an
    incident-response drill and a business-continuity drill -- are the failure the
    drafting prompt warns about, and a looser match would put one's answer first
    for the other.
    """
    return asks_on_its_own(question) and wording_key(asked) == wording_key(question)


_FOLLOW_UP = re.compile(
    r"^(?:if (?:yes|no|so|not|applicable|available)|please (?:provide|describe|explain|specify|attach|list|share|"
    r"give|state|detail)|provide|describe|explain|specify|attach|details?|comments?|evidence|remarks?|other|"
    r"إذا|اذا|في حال|يرجى|الرجاء|يُرجى|يرجي)\b",
    re.IGNORECASE,
)


def asks_on_its_own(question: str) -> bool:
    """Whether a question's words say what it asks, without its section or the row above (plan 034's review).

    "If yes, please provide details" asks about encryption under Encryption and
    about access under Access control: the same words, two questions. Such a
    follow-up, or anything of fewer than four words, is never matched by its
    words alone -- neither to an earlier answer nor to a kept search plan.
    """
    words = wording_key(question)
    return len(words.split()) >= 4 and not _FOLLOW_UP.match(words)


def wording_key(text: str) -> str:
    """A question's words with case, punctuation, spacing and the digits' script folded away (plan 034)."""
    from src.chunking import fold_digits

    folded = re.sub(r"[ً-ْـ]", "", fold_digits(text).casefold())  # harakat and tatweel
    return " ".join(re.findall(r"\w+", folded))
