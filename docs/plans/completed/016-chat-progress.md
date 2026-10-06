# Plan 016: The chat page's answered count

**Status:** completed

## Goal

The user reported on 2026-10-06 that the chat page's indicator of how many
questions have been answered "is not working properly". Find what it shows
and why, fix the cause, and add a test that would have caught it.

## Acceptance criteria

- [x] The fault is reproduced on the real page, with what the working bubble showed, before anything is changed.
- [x] After answering, a rewording, house-style or shortening pass is labelled as that pass, never "Answered 0 of N".
- [x] A chat turn's shortening pass reports under the turn's own ID, so the bubble follows it.
- [x] The tests fail on the old code and pass on the new: a unit test per counted stage, one for shortening under the turn's ID, and a browser test of the chat page.
- [x] `uv run poe check` passes.

## Plan

1. Trace the bubble's polling, `src/progress.py`, and every caller that reports progress.
2. Reproduce in the browser: a scripted assistant turn with slow fake answers and preferences set, and record every text of the working bubble.
3. Fix the cause, rerun the reproduction, and keep it as a test.

## Progress log

- 2026-10-06: Traced. The chat page polls `/api/assessments/progress/<id>` every 1.2 s, under an ID it makes for each turn. The answering pipeline counts under that ID correctly. But `progress.set_total()` set every run's stage to "answering". The passes that follow answering each call `start(stage=...)` and then `set_total()`: rewording (`tools.revise`, the revise route), house style (`tools.in_house_style`) and shortening (`tools.make_brief`). So their counts were labelled "Answered". Shortening also reported under the batch's ID, which a chat turn does not watch.
- 2026-10-06: Reproduced in Chromium with a scripted turn: 4 questions answered 0.6 s apart, and the person's preferences set. The bubble showed "Thinking…", "Answered 0 of 4", "Answered 2 of 4", then "Answered 0 of 4" and "Answered 2 of 4" again. The second count is the preferences being applied, shown as a fresh answering run. With no preferences set the bubble was correct, so the fault appears for anyone who has set preferences.
- 2026-10-06: Fixed:
  - `set_total` keeps a stage that names what it counts (`progress.COUNTED`: answering, rewriting, styling, shortening). Only "extracting" or the assistant's free-text stages become "answering".
  - `tools.make_brief` takes a `run_id`. `tools.answer` and `tools.revise` pass the turn's ID to it; the workbench's routes still report under the batch, as before.

  The reproduction now shows "Answered 0 of 4", "Answered 2 of 4", "Applied your preferences to 0 of 4", "Applied your preferences to 2 of 4". The workbench uses the same stage names, so its bar is fixed by the same change.
- 2026-10-06: Tests:
  - `tests/test_turn_progress.py` (6 tests): 4 of them fail on the old code (one per counted pass, and shortening under the turn's ID); the other 2 pin what did not change.
  - `tests/browser/test_chat.py`: on the old code it fails with the bubble's own words ("Answered 2 of 4", then "Answered 0 of 4"); on the new code it passes in 8 s.

  The temporary reproduction scripts were deleted.
- 2026-10-06: `uv run poe check` passes (1,809 tests, 6 browser tests). Plan complete.

## Decision log

- 2026-10-06: Fixed without asking first, although it changes behaviour: the user reported the fault and asked for it to work. Only the labels and the ID a pass reports under changed, and the counts themselves are untouched. (Claude)
