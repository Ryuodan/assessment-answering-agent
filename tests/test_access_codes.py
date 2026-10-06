"""A generated access code is shown on the Access panel and the console, never logged (TD-029)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src import access_codes, identity
from src.api import app
from src.config import settings

ADMIN = "admin@example.com"
ADMIN_PASSWORD = "a-long-admin-password"


def _upgrade_without_a_code(monkeypatch):
    """A deployment with people in it but no access code: what bootstrap repairs."""
    identity.ensure_team(settings.default_team)
    identity.add_user("member@example.com")
    monkeypatch.setattr(settings, "admin_email", ADMIN)
    monkeypatch.setattr(settings, "admin_password", ADMIN_PASSWORD)


def test_the_generated_code_goes_to_the_console_and_the_panel_not_the_log(monkeypatch, caplog, no_console):
    _upgrade_without_a_code(monkeypatch)
    identity.bootstrap()

    code = access_codes.waiting(settings.default_team)
    assert code and identity.team_has_code(settings.default_team)
    assert any(code in text for text in no_console), "shown on the console"
    assert code not in caplog.text, "never written to the log"
    assert "identity.access_code_generated" in caplog.text and "access panel, console" in caplog.text
    [team] = [t for t in identity.list_teams() if t["id"] == settings.default_team]
    assert team["generated_code"] == code


def test_without_a_terminal_the_panel_is_the_only_place(monkeypatch, caplog):
    monkeypatch.setattr(access_codes, "_to_console", lambda text: False)
    _upgrade_without_a_code(monkeypatch)
    identity.bootstrap()
    assert access_codes.waiting(settings.default_team)
    assert 'shown_on="access panel"' in caplog.text


def test_the_code_works_and_issuing_a_new_one_takes_it_off_the_panel(monkeypatch):
    _upgrade_without_a_code(monkeypatch)
    identity.bootstrap()
    code = access_codes.waiting(settings.default_team)
    member = TestClient(app)
    assert member.post("/api/auth/session", json={"email": "member@example.com", "code": code}).status_code == 200

    admin = TestClient(app)
    assert admin.post("/api/auth/session", json={"email": ADMIN, "code": ADMIN_PASSWORD}).status_code == 200
    [team] = [t for t in admin.get("/api/admin/overview").json()["teams"] if t["id"] == settings.default_team]
    assert team["generated_code"] == code

    admin.post(f"/api/admin/teams/{settings.default_team}/access-code")
    [team] = [t for t in admin.get("/api/admin/overview").json()["teams"] if t["id"] == settings.default_team]
    assert team["generated_code"] is None


def test_the_code_is_never_shown_to_a_member(monkeypatch):
    _upgrade_without_a_code(monkeypatch)
    identity.bootstrap()
    member = TestClient(app)
    code = access_codes.waiting(settings.default_team)
    member.post("/api/auth/session", json={"email": "member@example.com", "code": code})
    response = member.get("/api/admin/overview")
    assert response.status_code == 403 and code not in response.text
