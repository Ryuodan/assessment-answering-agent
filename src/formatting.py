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


def strip_source_markers(text: str) -> str:
    """Remove internal source indices the drafter leaked into the prose."""
    cleaned = _SOURCE_MARKER.sub("", text or "")
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
