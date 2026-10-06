"""The SQLite schema, as an ordered list of migrations. Applied by `src.store`.

Moved out of `src/store.py` unchanged (plan 019): the list only grows, and the
module that applies it was at its size limit. A migration is SQL, or the name
of a function in this module taking the connection, when it needs a setting.
"""

from __future__ import annotations

import sqlite3

from src.config import settings

# Ordered, append-only. Each entry moves the schema forward exactly one step and
# `PRAGMA user_version` records how far a file has got. Never edit a migration
# that has shipped — add another.
MIGRATIONS: list[str] = [
    # 1 — identity, sessions, the event log, and answered runs.
    """
    CREATE TABLE teams (
        id          TEXT PRIMARY KEY,
        created_at  TEXT NOT NULL
    );

    CREATE TABLE users (
        email       TEXT PRIMARY KEY,
        team_id     TEXT NOT NULL REFERENCES teams(id),
        created_at  TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );

    CREATE TABLE sessions (
        token_hash  TEXT PRIMARY KEY,
        email       TEXT NOT NULL REFERENCES users(email),
        created_at  TEXT NOT NULL,
        expires_at  TEXT NOT NULL
    );
    CREATE INDEX sessions_email ON sessions(email);

    CREATE TABLE events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at   TEXT NOT NULL,
        team_id      TEXT NOT NULL,
        actor_email  TEXT NOT NULL,
        kind         TEXT NOT NULL,
        subject_type TEXT NOT NULL DEFAULT '',
        subject_id   TEXT NOT NULL DEFAULT '',
        payload      TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX events_team_time ON events(team_id, id DESC);
    CREATE INDEX events_subject ON events(subject_type, subject_id);

    CREATE TABLE runs (
        run_id          TEXT PRIMARY KEY,
        team_id         TEXT NOT NULL,
        actor_email     TEXT NOT NULL,
        source_name     TEXT NOT NULL,
        language        TEXT NOT NULL,
        questions_found INTEGER NOT NULL,
        created_at      TEXT NOT NULL
    );
    CREATE INDEX runs_team_time ON runs(team_id, created_at DESC);

    CREATE TABLE run_answers (
        run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        ordinal       INTEGER NOT NULL,
        question_id   TEXT NOT NULL,
        question      TEXT NOT NULL,
        answer        TEXT NOT NULL,
        confidence    REAL NOT NULL,
        needs_review  INTEGER NOT NULL,
        attempts      INTEGER NOT NULL,
        error         TEXT NOT NULL DEFAULT '',
        payload       TEXT NOT NULL,
        PRIMARY KEY (run_id, ordinal)
    );
    """,
    # 2 — access is administered from inside the application rather than from
    # the environment. Whoever runs this system may not be whoever decides who
    # uses it, and an allow-list in `.env` can only be changed by the former.
    # A `users` row now *is* the allow-list; `ALLOWED_EMAILS` seeds it once.
    """
    ALTER TABLE teams ADD COLUMN name TEXT NOT NULL DEFAULT '';
    ALTER TABLE teams ADD COLUMN access_code_hash TEXT NOT NULL DEFAULT '';
    ALTER TABLE teams ADD COLUMN code_set_at TEXT NOT NULL DEFAULT '';

    ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
    ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT '';
    ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN added_by TEXT NOT NULL DEFAULT '';

    -- A shared code is only as strong as the number of guesses allowed against
    -- it, so the guesses are counted.
    CREATE TABLE sign_in_attempts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        email      TEXT NOT NULL,
        created_at TEXT NOT NULL,
        succeeded  INTEGER NOT NULL
    );
    CREATE INDEX sign_in_attempts_email_time ON sign_in_attempts(email, created_at);
    """,
    # 3 -- a questionnaire someone uploaded, and the answers written for it.
    #
    # Separate from `runs` because it is a different thing. A run is one pass
    # over a list of questions and is finished when it returns. A batch is a
    # document somebody comes back to: answered in parts, corrected by hand,
    # filled in and downloaded, then perhaps answered again where it was left
    # blank. So its answers are keyed by question rather than by position, and
    # writing one twice merges rather than replaces.
    """
    CREATE TABLE form_batches (
        batch_id    TEXT PRIMARY KEY,
        team_id     TEXT NOT NULL,
        actor_email TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_path TEXT NOT NULL,
        format      TEXT NOT NULL,
        detected    TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX form_batches_team_time ON form_batches(team_id, created_at DESC);

    CREATE TABLE batch_answers (
        batch_id    TEXT NOT NULL REFERENCES form_batches(batch_id) ON DELETE CASCADE,
        question_id TEXT NOT NULL,
        answered_at TEXT NOT NULL,
        edited_by   TEXT NOT NULL DEFAULT '',
        payload     TEXT NOT NULL,
        PRIMARY KEY (batch_id, question_id)
    );
    """,
    # 4 -- a conversation with the assistant.
    #
    # Kept for the same reason a batch is: the work outlives the request. A
    # person says "read this file", waits four minutes for 183 answers, comes
    # back after lunch and says "now make the governance ones shorter" -- and
    # the second sentence only means anything if the first is still there.
    #
    # Messages are stored as LangChain serialised them, tool calls included,
    # rather than as a tidy transcript. The agent has to *resume*, and it can
    # only do that from what it actually said and saw; a display transcript
    # would lose which tool returned what, which is exactly the part a
    # follow-up instruction depends on.
    """
    CREATE TABLE conversations (
        conversation_id TEXT PRIMARY KEY,
        team_id         TEXT NOT NULL,
        actor_email     TEXT NOT NULL,
        title           TEXT NOT NULL DEFAULT '',
        batch_id        TEXT REFERENCES form_batches(batch_id) ON DELETE SET NULL,
        messages        TEXT NOT NULL DEFAULT '[]',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );
    CREATE INDEX conversations_team_time ON conversations(team_id, updated_at DESC);
    """,
    # 5 -- take the plumbing back out of the titles it leaked into.
    #
    # A message with a file attached carries a note telling the agent the file
    # is there. It belongs in the stored message, because that history is what
    # the agent re-reads -- but it was also going into the conversation's
    # title, so a person's own history read as a list of
    # "Read this file. [A file has been uploaded to this conversation: HR…"
    # rather than a list of what they had asked for.
    #
    # Fixed at the source, and repaired here for the conversations that already
    # have it: those titles are display text and nothing reads them back, so
    # trimming is safe. The note is truncated to three different lengths by the
    # title's own length limit, and every one of them starts the same way.
    """
    UPDATE conversations
       SET title = RTRIM(SUBSTR(title, 1, INSTR(title, '[A file has been') - 1))
     WHERE INSTR(title, '[A file has been') > 0;
    """,
    # 6 -- how long the answers in this questionnaire should be.
    #
    # Per questionnaire rather than per user or per team, because the reason
    # anybody wants short answers is the size of the file in front of them: 183
    # rows due on Thursday is a different job from twenty rows for a bank that
    # will read every word. The same person wants both, in different weeks.
    """
    ALTER TABLE form_batches ADD COLUMN detail TEXT NOT NULL DEFAULT 'full';
    """,
    # 7 -- the answer memory, as a record rather than only as vectors.
    #
    # What we have said before is worth about seventeen points of agreement with
    # the security team, which makes it the most valuable thing in the system and
    # the thing most worth keeping true. Chroma holds the text and the vectors and
    # is the right place for "what did we say about encryption"; it is the wrong
    # place for "who approved this, when, and what did it replace", which is a
    # record with an owner and a history. That lives here.
    #
    # A superseded entry is kept. It was true when it was written, an assessor may
    # ask what we said last year, and a memory that quietly rewrites its own
    # history cannot be audited. It is simply no longer retrieved.
    """
    CREATE TABLE memory_entries (
        entry_id      TEXT PRIMARY KEY,
        team_id       TEXT NOT NULL DEFAULT '',
        question      TEXT NOT NULL,
        answer        TEXT NOT NULL,
        section       TEXT NOT NULL DEFAULT '',
        from_file     TEXT NOT NULL DEFAULT '',
        origin        TEXT NOT NULL DEFAULT 'import',
        approved_by   TEXT NOT NULL DEFAULT '',
        approved_on   TEXT NOT NULL DEFAULT '',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        scanned_at    TEXT NOT NULL DEFAULT '',
        superseded_by TEXT NOT NULL DEFAULT '',
        superseded_on TEXT NOT NULL DEFAULT '',
        because       TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX memory_entries_updated ON memory_entries(updated_at DESC);
    CREATE INDEX memory_entries_pending ON memory_entries(scanned_at);

    -- Two answers that disagree and nothing saying which is current. Not a
    -- versioning problem: two people believed different things, and no rule
    -- here can decide which is right, so it waits for one of them.
    CREATE TABLE memory_conflicts (
        entry_id    TEXT NOT NULL,
        other_id    TEXT NOT NULL,
        because     TEXT NOT NULL DEFAULT '',
        raised_at   TEXT NOT NULL,
        resolved_at TEXT NOT NULL DEFAULT '',
        resolved_by TEXT NOT NULL DEFAULT '',
        resolution  TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (entry_id, other_id)
    );
    CREATE INDEX memory_conflicts_open ON memory_conflicts(resolved_at);
    """,
    # 8 -- preferences and skills: how one person wants answers worded.
    #
    # Personal, both of them. The answer memory and the knowledge base are the
    # team's, because they are facts about the organisation; how a particular
    # reviewer likes an answer phrased is a fact about that reviewer. Keyed by
    # address rather than by a users row, so the open, unsigned-in deployment --
    # which has no users table rows at all -- keeps its preferences too.
    #
    # Neither is ever read by the drafter. A style is applied by rewording an
    # answer that has already been grounded and reviewed, which is the only
    # place a free-text instruction cannot argue with the evidence.
    """
    CREATE TABLE user_preferences (
        email          TEXT PRIMARY KEY,
        style          TEXT NOT NULL DEFAULT '',
        default_length TEXT NOT NULL DEFAULT 'full',
        updated_at     TEXT NOT NULL
    );

    CREATE TABLE skills (
        skill_id     TEXT PRIMARY KEY,
        owner_email  TEXT NOT NULL,
        name         TEXT NOT NULL,
        description  TEXT NOT NULL DEFAULT '',
        instruction  TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    );
    CREATE UNIQUE INDEX skills_owner_name ON skills(owner_email, name COLLATE NOCASE);
    """,
    # 9 -- preferences as choices rather than a paragraph.
    #
    # Migration 8 kept a preference as one free-text instruction, which made it
    # the same kind of thing as a skill -- and nobody could tell the two apart.
    # A preference is now a handful of fixed choices applied to every answer;
    # `style` stays, as the optional "also, always" line beneath them, so any
    # instruction already saved keeps applying. Every default is "as drafted":
    # nobody's answers change until they choose something.
    """
    ALTER TABLE user_preferences ADD COLUMN verdict_first INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE user_preferences ADD COLUMN refer_to TEXT NOT NULL DEFAULT '';
    ALTER TABLE user_preferences ADD COLUMN policy_references TEXT NOT NULL DEFAULT 'keep';
    ALTER TABLE user_preferences ADD COLUMN tone TEXT NOT NULL DEFAULT 'as_drafted';
    """,
    # 10 -- the answer memory belongs to a team, as the knowledge base does.
    #
    # It was one memory for the whole organisation: every team's answers were
    # retrieved for every other team's questionnaires, and any member could
    # correct or forget another team's entries. Entries are now keyed by team
    # as well as id -- two teams may each import a questionnaire of the same
    # name, and `<file>::<n>` would otherwise collide -- and everything already
    # remembered belongs to the team the system was set up for.
    "_team_the_answer_memory",
    # 11 -- products (plan 020). A team's products, each of which will have a
    # knowledge base and an answer memory of its own beside the team's shared
    # ones. The name is unique per team whatever its case; `src.products`
    # checks that too, for letters NOCASE does not fold, such as Arabic.
    #
    # `seeds` records which one-off seedings have run, so that deleting what
    # a seeding added is not undone by the next restart.
    """
    CREATE TABLE products (
        product_id  TEXT PRIMARY KEY,
        team_id     TEXT NOT NULL,
        name        TEXT NOT NULL,
        color       TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_by  TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE UNIQUE INDEX products_team_name ON products(team_id, name COLLATE NOCASE);

    CREATE TABLE seeds (
        name       TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    """,
]


def _team_the_answer_memory(conn: sqlite3.Connection) -> None:
    """Migration 10, in Python because it needs to know the default team's name."""
    team = settings.default_team
    conn.executescript(
        """
        CREATE TABLE memory_entries_by_team (
            entry_id      TEXT NOT NULL,
            team_id       TEXT NOT NULL,
            question      TEXT NOT NULL,
            answer        TEXT NOT NULL,
            section       TEXT NOT NULL DEFAULT '',
            from_file     TEXT NOT NULL DEFAULT '',
            origin        TEXT NOT NULL DEFAULT 'import',
            approved_by   TEXT NOT NULL DEFAULT '',
            approved_on   TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            scanned_at    TEXT NOT NULL DEFAULT '',
            superseded_by TEXT NOT NULL DEFAULT '',
            superseded_on TEXT NOT NULL DEFAULT '',
            because       TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (team_id, entry_id)
        );
        CREATE TABLE memory_conflicts_by_team (
            team_id     TEXT NOT NULL,
            entry_id    TEXT NOT NULL,
            other_id    TEXT NOT NULL,
            because     TEXT NOT NULL DEFAULT '',
            raised_at   TEXT NOT NULL,
            resolved_at TEXT NOT NULL DEFAULT '',
            resolved_by TEXT NOT NULL DEFAULT '',
            resolution  TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (team_id, entry_id, other_id)
        );
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_entries_by_team
            (entry_id, team_id, question, answer, section, from_file, origin, approved_by,
             approved_on, created_at, updated_at, scanned_at, superseded_by, superseded_on, because)
        SELECT entry_id, CASE WHEN team_id = '' THEN ? ELSE team_id END, question, answer,
               section, from_file, origin, approved_by, approved_on, created_at, updated_at,
               scanned_at, superseded_by, superseded_on, because
          FROM memory_entries
        """,
        (team,),
    )
    # A disagreement belongs to the team whose entries it is between.
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_conflicts_by_team
            (team_id, entry_id, other_id, because, raised_at, resolved_at, resolved_by, resolution)
        SELECT COALESCE(NULLIF((SELECT e.team_id FROM memory_entries e WHERE e.entry_id = c.entry_id), ''), ?),
               entry_id, other_id, because, raised_at, resolved_at, resolved_by, resolution
          FROM memory_conflicts c
        """,
        (team,),
    )
    conn.executescript(
        """
        DROP TABLE memory_entries;
        DROP TABLE memory_conflicts;
        ALTER TABLE memory_entries_by_team RENAME TO memory_entries;
        ALTER TABLE memory_conflicts_by_team RENAME TO memory_conflicts;
        CREATE INDEX memory_entries_team_updated ON memory_entries(team_id, updated_at DESC);
        CREATE INDEX memory_entries_pending ON memory_entries(scanned_at);
        CREATE INDEX memory_conflicts_open ON memory_conflicts(team_id, resolved_at);
        """
    )
