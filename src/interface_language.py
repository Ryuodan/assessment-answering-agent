"""The language each person sees the pages in: English or Arabic (plan 038).

Kept with the person, so it follows them to another browser or device, and
apart from their answer preferences (`src/preferences.py`): it changes how the
pages read, never what an answer says. Answers keep following the question's
language, or the language a questionnaire is forced into.

The pages hold a copy on the device, to be drawn in it from the first paint;
the session (`GET /api/auth/session`) says which it is, and a page whose copy
differs takes the person's.
"""

from __future__ import annotations

from src import store
from src.errors import PreferenceError
from src.identity import normalise

LANGUAGES = ("en", "ar")
DEFAULT = "en"


def get(email: str) -> str:
    """This person's interface language, English when they have chosen none."""
    row = (
        store.connect()
        .execute("SELECT language FROM interface_languages WHERE email = ?", (normalise(email),))
        .fetchone()
    )
    return row["language"] if row is not None and row["language"] in LANGUAGES else DEFAULT


def choose(email: str, language: str) -> str:
    """Keep `language` as this person's, and return it."""
    if language not in LANGUAGES:
        raise PreferenceError("The interface is in English or Arabic: en or ar.", code="language_invalid")
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO interface_languages (email, language, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET language = excluded.language, updated_at = excluded.updated_at
        """,
        (normalise(email), language, store.utcnow()),
    )
    conn.commit()
    return language
