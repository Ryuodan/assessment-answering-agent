"""The searches a query plan holds, read out of the planner's plain text.

Moved unchanged from `src.graph.nodes` (plan 034, to make room), which imports it
under its old name, `_parse_queries`.
"""

from __future__ import annotations

import re


def parse_queries(content: object) -> list[str]:
    """Pull search queries out of a plain-text plan, one per line.

    Tolerant of the shapes a model reaches for unprompted: numbered lists,
    bullets, quotes, and a reasoning model's `<think>` preamble.
    """
    if isinstance(content, list):  # some providers return content blocks
        content = " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)

    text = re.sub(r"<think>.*?</think>", " ", str(content), flags=re.DOTALL | re.IGNORECASE)

    queries = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"“”')
        # A plan is a list of short search strings; anything long is commentary.
        if 3 <= len(line) <= 160 and not line.endswith(":"):
            queries.append(line)
    return queries
