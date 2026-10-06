# Security

What this system holds, where, who can reach it, and the rules for working in
this repository. The design reasoning behind sign-in and isolation is in the
README sections [Signing in, and what gets remembered](README.md#signing-in-and-what-gets-remembered)
and [Facing a network](README.md#facing-a-network).

## What is sensitive

| Data | Where | Why it matters |
|---|---|---|
| Customer questionnaires and their filled copies | `data/` (per team, per person), gitignored | arrive from other companies, often under NDA |
| Internal policies and the text indexed from them | `data/`, `chroma_db/` (Chroma stores each chunk's raw text), gitignored | the organisation's internal controls |
| The team's past answers | the answer memory (SQLite and Chroma); `eval/answer_memory.json` and `eval/house_set.json`, committed only sealed in `eval/sealed/` (plaintext gitignored) | real answers given to named customers |
| Accounts, sessions, the event log | SQLite at `DB_PATH` (`data/app.db`), gitignored | who did what; session tokens (stored as SHA-256) |
| Secrets | `.env`, gitignored: `GROQ_API_KEY`, `LANGSMITH_API_KEY`, `EMBEDDING_API_KEY`, `ADMIN_PASSWORD`, `EVAL_DATA_KEY` | access to paid services, to the system, and to the sealed eval data |
| Traces, when switched on | LangSmith (EU or US) or a local Phoenix store | each trace is a copy of the prompt: policy text and the questionnaire |

## Known exposure

- **Eval data in git history (TD-013).** `eval/house_set.json` and
  `eval/answer_memory.json` were committed in plaintext until plan 002 sealed
  them (2026-10-05); by the user's decision history is not rewritten, so every
  commit before the sealing still holds the plaintext. **Before this repository
  is pushed to any remote, purge those two paths from history** (for example
  `git filter-repo --path eval/house_set.json --path eval/answer_memory.json
  --invert-paths`); the sealed copies in `eval/sealed/` are unaffected.
- **Data residency.** LangSmith has no Saudi region; `LANGSMITH_TRACING` is off
  by default and switching it on sends policy text and questionnaires abroad.
  That is a decision for whoever owns the documents.

## Sealed eval data

`eval/sealed/*.enc` is AES-256-GCM, keyed by `EVAL_DATA_KEY` in `.env`
(`eval/vault.py`, D-011). `uv run poe eval-unlock` writes the plaintexts to
`eval/`, where `.gitignore` keeps them out of commits and ARCH-SEALED fails if
one is tracked, not ignored, or changed without being re-sealed.

- **The key is the data.** Lose it and the sealed files cannot be read. Keep a
  copy outside this machine (a password manager), and hand it to a colleague
  only over a channel you would trust with the questionnaires themselves.
- A new key is made once with `uv run python -m eval.vault keygen`, which
  writes it into `.env` and prints nothing. To rotate: unlock with the old key,
  empty the `EVAL_DATA_KEY=` line, run keygen, then `uv run poe eval-seal --force`.

## Logs

Every log line goes through one handler (`src/logs.py`) that replaces the
values of `GROQ_API_KEY`, `LANGSMITH_API_KEY`, `EMBEDDING_API_KEY`,
`ADMIN_PASSWORD` and `EVAL_DATA_KEY`, and anything shaped like an API key, with
`[redacted]`. The per-request line records the route template, never the raw
path or query string. A team access code generated on upgrade is shown on the
console and the Access panel and never logged (TD-029). One exception is kept by
decision: uvicorn's own access log, which bypasses this handler, records raw
paths and queries (TD-031).

## Access model, in one paragraph

Sign-in needs an address on the allow-list and the team's access code (an
administrator uses a password instead). Codes and passwords are hashed with
scrypt; sessions are database rows, revocable at once. Sign-in is throttled per
address, and a refused sign-in costs the same time whether or not the address
exists. Teams cannot see each other's knowledge base, memory or documents
(404, not 403); inside a team, questionnaires, runs and conversations belong to
the person who made them. With no users added the API runs open, as
`local@localhost`; adding the first user closes it.

## Security-sensitive code, and the tests that hold it

| Concern | Code | Tests |
|---|---|---|
| sign-in, sessions, roles | `src/identity.py`, `src/credentials.py`, `api.current_user`, `api.current_admin` | `tests/test_api_identity.py`, `tests/test_identity.py`, `tests/test_credentials.py` |
| path traversal through document routes and uploads | `service.resolve_document`, `service.save_upload` | `tests/test_hostile_input.py` |
| hostile spreadsheets and Word files (zip bombs, huge sheets) | `src/forms/xlsx_package.py`, `src/forms/docx.py` | `tests/test_forms_hostile.py` |
| server text shown as markup (XSS) | `src/static/*.html`, `service.docx_preview_html` | `tests/test_document_library.py` (Word preview); the page-side rule has no test (TD-021) |
| team isolation | `knowledge`, `answer_memory`, `service.list_documents` | `tests/test_team_isolation.py` |
| per-person privacy | `conversations.load`, `batches.load` (via `tools._require`), `runs.load` | `tests/test_private_work.py` |

## Rules for anyone working here, agents included

1. Never commit `.env`, `data/`, `chroma_db/`, `eval/results/` or any customer
   file. `.gitignore` covers them; do not override it.
2. Never print or log a secret, and never read `.env` values into a
   conversation or a commit message. That includes `EVAL_DATA_KEY`.
3. Tests use temporary directories only (`tests/conftest.py` redirects every
   storage path). A test must never need the real database, index or `.env`.
4. Do not run a script that writes to the real Chroma index (TD-012) unless the
   user asked for that run.
5. Do not add a git remote before TD-013 is resolved.
6. `uv run poe arch` scans tracked files for key-shaped strings (ARCH-SECRET);
   a hit is a stop-and-ask, not something to allow-list quietly.
