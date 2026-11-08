# Plan 040: The language and Dark mode move to Preferences

**Status:** completed 2026-11-08

## Goal

The user's request: "I think "Dark mode" option and "Language" option shouldn't be a button with the other tabs. Lets put them in a setting page or something".

Every page's top bar held the links to the other pages, then two buttons that are not places to go: the language switch and Dark mode. Both now live on the Preferences page, in one panel at the top. The top bar is only where you can go, and who you are.

## Acceptance criteria

- [x] No page's top bar has the language switch or the theme button.
- [x] Preferences has "Language of the pages" and "Appearance" together, at the top. Light mode and Dark mode are a choice like the page's other choices.
- [x] The appearance is applied on every page and kept on the device, as before. With nothing chosen, it follows the system. It is not one of the answer preferences: choosing it does not ask to save.
- [x] The language is kept with the person, as before, and reaches every page.
- [x] The prompt before losing unsaved typing stays on Preferences, the only page that switches now. It is gone from the others, with its Arabic.
- [x] The Preferences link's hint says the language and look are there, in English and Arabic.
- [x] Browser tests: `tests/browser/test_language_switch.py`. `uv run poe check` passes.

## Plan

1. Take the buttons out of the six pages and `i18n.js`. The pages keep applying the theme.
2. Add the appearance choice beside the language in Preferences.
3. Tests, docs, the gate.

## How to test it yourself

Reload any page. The top bar has no "Dark mode" and no "العربية". Open Preferences: the first panel has "Language of the pages" and "Appearance". Choose Dark mode, and open another page: it stays dark. Choose العربية: the page reloads in Arabic, and so does every other page.

## Progress log

- 2026-11-08: done as above. The theme code in each page stays where it was, without its button; it is still written six times, as it was. `Appearance` (المظهر) is a new term, added to the glossary for review. The tests of the prompt on the assistant's page and the Workbench went with it, as did the tests of the switch itself; tests of choosing in Preferences, on every page, replace those.

## Decision log

- 2026-11-08: both move out of the top bar. (The user.)
- 2026-11-08: "a setting page or something" is the Preferences page, which already had the language. A new Settings page would add a link to the bar this plan is thinning, for two choices. (Mine; the user can overrule it.)
- 2026-11-08: Dark mode is two choices, Light mode and Dark mode, using the glossary's terms, rather than a button that names the other one. It matches the page's other choices. (Mine.)
