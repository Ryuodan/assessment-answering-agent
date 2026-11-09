# Plan 042: The card's colours say what they mean

**Status:** completed 2026-11-09

## Goal

The user's notes on plan 041's card: "The cards are good looking now, but I have a few notes. The answer text is not distinguished from other text. And the sources doesn't signal that it either came from knowledge-base or answer-memory. Also the confidence level should be more obvious and color coded. And I would color the "Why this is flagged" or "Why the confidence is low". I mean we should use colors more to signal different meanings, but to not over do it and end up make it look like a game."

## Acceptance criteria

- [x] The answer sits on a ground of its own. A note in its place (left blank, no answer) does not.
- [x] Sources are grouped by where they came from, each row led by "Knowledge base" or "Answer memory" in its colour, and the opened source says the same.
- [x] The confidence is a coloured label: red at or under the server's threshold, green in the top half above it, amber between.
- [x] A check that held the answer caps it at amber, so it is never green beside "Needs review". A person's decision leaves it uncoloured. With no threshold known, it is uncoloured.
- [x] "Why this is flagged" is amber. "Why the confidence is low" is red when the score is what held it, amber when a check did. The reasoning stays plain.
- [x] The chat's filter tabs are drawn as the Workbench's: "the filter buttons in the assistant answers panel are kind of odd" (the user). The shared rule leaned on the Workbench's own `button` rule, which the chat page does not have.
- [x] Each colour means one thing, and the words say it too. English and Arabic, light and dark. `uv run poe check` passes.

## Plan

1. `cards.js` and `cards.css`: the five meanings, the answer's ground, the rows of sources, the label, the two blocks.
2. `tests/browser/test_card_colours.py`, the docs, the gate.

## How to test it yourself

Open a review and choose the All tab. The answer is on a grey ground. The percentage at the top right is green, amber or red. Under the answer, sources are in rows named Knowledge base (blue) and Answer memory (plum). Open "Why this answer" on a held card: the two reasons are coloured, the reasoning is not.

## Progress log

- 2026-11-09: done as above. Text and labels were checked against their grounds: 4.6:1 or better in both themes.

## Decision log

- 2026-11-09: the meanings: green fine, amber a person should look, red low or failed, blue the knowledge base, plum the answer memory. Plum, not the green the sources had before plan 041, because green now means fine. (Mine.)
- 2026-11-09: the line between amber and green is halfway from the server's threshold to 100% (80% at the default 60%). It moves with the threshold, so the card holds no number of its own. (Mine; the user can overrule it.)
- 2026-11-09: a held answer's score is capped at amber: green beside "Needs review" is what plan 030 removed. (Mine.)
- 2026-11-09: a row for each place, rather than a word on each chip: said once per row, and the chips stay short. (Mine.)
- 2026-11-09: the answer's ground is neutral, so it does not compete with what the colours say. (Mine.)
