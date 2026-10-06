# Plan 007: Validated boundaries

**Status:** active

## Goal

Data that enters the system from outside becomes a typed, validated model at the
point it enters, so that a malformed value fails where it arrives, with a message
naming it, instead of travelling inward and failing somewhere unrelated. The
survey found most boundaries already parsed into pydantic models (request bodies,
stored records, model output). Four gaps remain: settings that take one of a
fixed set of words are free strings; the organisation profile file is read into
a dataclass without type checks; Docling's responses are used as raw dicts; and
nothing stops new code from decoding raw JSON. This plan closes them, records an
inventory of every boundary, and finishes milestone M3.

## Acceptance criteria

- [ ] `DETECTION_STRATEGY`, `GROQ_REASONING_FORMAT`, `LOG_LEVEL` and `DOCLING_IMAGE_EXPORT_MODE` are `Literal` types; an invalid value fails at startup naming the setting; `LOG_LEVEL` still accepts lower case; the strategy vocabulary matches `forms.reading.STRATEGIES` (tested).
- [ ] The organisation profile is a pydantic model read with `model_validate_json`; a malformed file still falls back to the built-in profile, logged as an event; nothing else about the profile changes (tests).
- [ ] Docling's task and result responses are parsed into models; a response of the wrong shape is a `DoclingError`, so the local fallback still applies (tests).
- [ ] ARCH-JSON fails on `json.loads` in `src/` outside the named exemptions, each with its reason; tests with failing examples.
- [ ] `docs/design/boundaries.md` lists every boundary, what it is parsed into, and where a gap remains; ARCHITECTURE.md links it.
- [ ] `uv run poe check` passes; the roadmap marks M3 done.

## Plan

1. This plan.
2. Settings vocabularies.
3. The organisation profile; the Docling responses (their modules' logging converted as they are touched).
4. ARCH-JSON.
5. The inventory; docs; `check`; close; roadmap.

## Progress log

- 2026-10-06: Plan written. Survey: request bodies are pydantic models; stored questionnaires, answers and runs are read back with `model_validate_json`; model output goes through `structured_llm` schemas; JSON is decoded raw in five places (`conversations`, `docling_client`, `llm` twice, `organisation`, `store`). The deployment's `.env` uses valid values for the four vocabulary settings (`placeholder`, `INFO`, `guarded`; reasoning format unset), checked by reading only those keys.
- 2026-10-06: Step 2. The four settings are `Literal` types; `LOG_LEVEL` upper-cased before the check (`info` worked before). Each refuses a bad value naming itself; mypy unchanged.
- 2026-10-06: Step 3. `Organisation` is a pydantic model (`extra="ignore"`), read with `model_validate_json`; the broad `except Exception` became `(OSError, ValidationError)` with a warning event. Docling: `_Task`, `_Result` and a generic `_parse` (a first version narrowed types with `assert isinstance`, replaced by a type variable because asserts vanish under `-O`). Running the old `docling_client.py` against the new test showed the gap was real: a reply whose `document` is a string raised `AttributeError`, which the fallback does not catch. Both modules' logging became events as they were touched (two more modules off the ARCH-LOG list: 21 remain). 16 boundary tests; the snapshots are unchanged.
- 2026-10-06: Step 4. ARCH-JSON first flagged `src/llm.py` twice (a provider's failed tool call, decoded and then validated against the schema); it became the third named exemption, with that reason. 2 rule tests.
- 2026-10-06: Step 5. `docs/design/boundaries.md` (11 boundaries, gaps named), D-015, GP-23, ARCHITECTURE.md and CLAUDE.md links.

## Decision log

- 2026-10-06: HTTP query and form parameters that are checked by hand (`mode` on search, `authority` on upload, the upload suffix) keep their hand checks: replacing them with `Literal` types would change their error responses from their own codes to `validation_failed`, which the error snapshots pin. They are typed at the boundary already; the inventory records them. My choice.
