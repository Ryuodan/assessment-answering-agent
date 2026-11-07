"""The language each person sees the pages in (plan 038).

Kept with the person, read by every page from the session, and apart from the
answer preferences: choosing Arabic changes how the pages read, never an answer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import identity, interface_language, preferences
from src.api import app
from src.config import settings
from src.errors import PreferenceError

ALICE = "m.alsaif@t2.sa"
BOB = "mohammed.sa.alsaif@gmail.com"
CODE = "TEAM-CODE-FOR-TESTS"


def test_english_until_a_person_chooses() -> None:
    assert interface_language.get(ALICE) == "en"


def test_a_choice_is_kept_per_person() -> None:
    interface_language.choose(ALICE, "ar")

    assert interface_language.get(ALICE) == "ar"
    assert interface_language.get(ALICE.upper()) == "ar", "the address as the person typed it"
    assert interface_language.get(BOB) == "en"
    interface_language.choose(ALICE, "en")
    assert interface_language.get(ALICE) == "en"


def test_only_english_or_arabic() -> None:
    with pytest.raises(PreferenceError):
        interface_language.choose(ALICE, "fr")
    assert interface_language.get(ALICE) == "en"


def test_the_session_says_which_and_the_route_changes_it() -> None:
    client = TestClient(app)
    assert client.get("/api/auth/session").json()["interface_language"] == "en"

    body = client.put("/api/preferences/language", json={"language": "ar"})

    assert body.status_code == 200 and body.json() == {"interface_language": "ar"}
    assert client.get("/api/auth/session").json()["interface_language"] == "ar"
    assert client.put("/api/preferences/language", json={"language": "de"}).status_code == 422


def test_choosing_arabic_changes_no_answer_preference() -> None:
    client = TestClient(app)
    before = client.get("/api/preferences").json()

    client.put("/api/preferences/language", json={"language": "ar"})

    after = client.get("/api/preferences").json()
    assert after["preferences"] == before["preferences"] and after["instruction"] == before["instruction"]
    assert preferences.load(identity.local_user().email) == preferences.Preferences()


def test_each_signed_in_person_has_their_own() -> None:
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)
    identity.add_user(BOB)
    alice, bob = TestClient(app), TestClient(app)
    for client, email in ((alice, ALICE), (bob, BOB)):
        assert client.post("/api/auth/session", json={"email": email, "code": CODE}).status_code == 200

    alice.put("/api/preferences/language", json={"language": "ar"})

    assert alice.get("/api/auth/session").json()["interface_language"] == "ar"
    assert bob.get("/api/auth/session").json()["interface_language"] == "en"
