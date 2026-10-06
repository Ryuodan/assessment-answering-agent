# Plan 006: Tests never touch real configuration or data

**Status:** active

## Goal

The suite runs on settings built from their declared defaults only, whatever
is in the developer's `.env` or shell, and every file a test reads or writes is
under a temporary directory. Today `src.config.settings` is built from `.env`
when it is imported (TD-011), so most settings in a test are whatever the
developer has configured, and the organisation profile is read from
`data/organisation.json` by a path no fixture redirects (TD-023). Afterwards
both are closed, and two guards keep them closed: a fixture that fails any test
in which a path setting still points into the project, and a check that stops
modules building paths under the project root themselves.

## Acceptance criteria

- [ ] `src/config.py` reads the env file named by `ASSESSMENT_ANSWER_ENV_FILE` (default: the project's `.env`; empty: none); `tests/conftest.py` sets it empty and removes any shell variable named like a setting before anything imports `src.config`.
- [ ] The organisation profile's location is a setting (`ORGANISATION_PATH`), used by `src/organisation.py`, redirected by `isolated_storage` like the other paths.
- [ ] Every test fails if, after `isolated_storage`, any `Path` setting still points inside the project; tested by showing the guard catches an unredirected path.
- [ ] ARCH-PATH fails when a module in `src/` other than `src/config.py` uses `PROJECT_ROOT`; tests with failing examples.
- [ ] The suite passes; TD-011 and TD-023 resolved; GP-13 names its enforcement; `uv run poe check` passes.

## Plan

1. This plan.
2. The env-file switch and the conftest set-up; the suite on pure defaults.
3. `organisation_path`; `src/organisation.py` (and its one log call converted, as it is touched).
4. The path guard in `isolated_storage`; ARCH-PATH.
5. Docs; `check`; close.

## Progress log

- 2026-10-06: Plan written; the user asked to finish M3 and then the other milestones. Survey: `PROJECT_ROOT` is used outside `src/config.py` only by `src/organisation.py`; no shell variable on this machine names a setting today.

## Decision log

- 2026-10-06: The switch is an environment variable read by `src/config.py` (the one module that reads the environment), naming the env file rather than only turning it off, so it is also useful for running against another configuration. It is not a field of Settings, so it is not in `.env.example`. My choice.
