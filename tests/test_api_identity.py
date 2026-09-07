"""Sign-in, gating, administration and history through the app.

The unit tests cover the rules. These cover the wiring: that a cookie is
actually set, that the admin routes refuse a member, that removing someone on
the page takes effect on their next request, and that finishing a run leaves
something behind to find later.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import events, identity, runs
from src.api import app
from src.config import settings
from src.models import AnsweredQuestion, Question

ALICE = "m.alsaif@t2.sa"
BOB = "mohammed.sa.alsaif@gmail.com"
CODE = "TEAM-CODE-FOR-TESTS"
ADMIN_PASSWORD = "a-long-admin-password"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def gated():
    """A team with a code, one member and one administrator."""
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)
    identity.add_user(BOB, role=identity.ADMIN, password=ADMIN_PASSWORD)


def _sign_in(client: TestClient, email: str = ALICE, code: str = CODE):
    return client.post("/api/auth/session", json={"email": email, "code": code})


def _as_admin(client: TestClient):
    assert _sign_in(client, BOB, ADMIN_PASSWORD).status_code == 200
    return client


# --- open mode (nobody added yet) ------------------------------------------


def test_before_anyone_is_added_requests_pass_as_the_local_user(client):
    response = client.get("/api/auth/session")
    assert response.status_code == 200
    assert response.json()["email"] == identity.LOCAL_EMAIL
    assert response.json()["sign_in_required"] is False


def test_before_anyone_is_added_history_is_reachable(client):
    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/events").status_code == 200


# --- gated mode ------------------------------------------------------------


@pytest.mark.usefixtures("gated")
def test_whoami_reports_that_sign_in_is_needed(client):
    response = client.get("/api/auth/session")
    assert response.status_code == 200, "the sign-in screen asks this; it must not 401"
    assert response.json() == {
        "email": None, "team": None, "role": None, "is_admin": False, "sign_in_required": True
    }


@pytest.mark.usefixtures("gated")
def test_history_is_refused_before_signing_in(client):
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/events").status_code == 401


@pytest.mark.usefixtures("gated")
def test_sign_in_sets_a_session_cookie(client):
    response = _sign_in(client)
    assert response.status_code == 200
    assert response.json()["email"] == ALICE
    assert response.cookies.get(identity.SESSION_COOKIE)
    assert "httponly" in response.headers["set-cookie"].lower()


@pytest.mark.usefixtures("gated")
def test_the_cookie_is_not_secure_over_plain_http(client):
    """A Secure cookie on http:// is discarded without a word, so sign-in would
    appear to succeed and then do nothing. Secure follows the connection."""
    assert "secure" not in _sign_in(client).headers["set-cookie"].lower()


@pytest.mark.usefixtures("gated")
def test_the_cookie_is_secure_over_https():
    with TestClient(app, base_url="https://testserver") as secure_client:
        assert "secure" in _sign_in(secure_client).headers["set-cookie"].lower()


@pytest.mark.usefixtures("gated")
def test_the_cookie_then_carries_the_session(client):
    _sign_in(client)
    assert client.get("/api/auth/session").json()["email"] == ALICE
    assert client.get("/api/runs").status_code == 200


@pytest.mark.usefixtures("gated")
def test_the_wrong_code_is_refused(client):
    response = _sign_in(client, ALICE, "not-the-code")
    assert response.status_code == 403
    assert response.json()["detail"] == "That email and access code do not match."
    assert client.get("/api/runs").status_code == 401


@pytest.mark.usefixtures("gated")
def test_an_unknown_address_is_refused_identically(client):
    """The form must not become a way to find out who has an account."""
    unknown = _sign_in(client, "stranger@example.com", CODE)
    assert unknown.json()["detail"] == "That email and access code do not match."


@pytest.mark.usefixtures("gated")
def test_signing_out_ends_the_session(client):
    _sign_in(client)
    assert client.delete("/api/auth/session").json() == {"signed_out": True}
    assert client.get("/api/runs").status_code == 401


@pytest.mark.usefixtures("gated")
def test_a_forged_cookie_is_refused(client):
    client.cookies.set(identity.SESSION_COOKIE, "made-up-token")
    assert client.get("/api/runs").status_code == 401


@pytest.mark.usefixtures("gated")
def test_signing_in_is_recorded(client):
    _sign_in(client)
    assert events.SIGNED_IN in [e.kind for e in events.recent(settings.default_team)]


# --- administration --------------------------------------------------------


@pytest.mark.usefixtures("gated")
def test_a_member_cannot_reach_the_admin_routes(client):
    _sign_in(client)
    assert client.get("/api/admin/overview").status_code == 403
    assert client.post("/api/admin/users", json={"email": "x@t2.sa"}).status_code == 403


@pytest.mark.usefixtures("gated")
def test_a_signed_out_visitor_cannot_reach_the_admin_routes(client):
    assert client.get("/api/admin/overview").status_code == 401


@pytest.mark.usefixtures("gated")
def test_an_admin_signs_in_with_their_password(client):
    response = _sign_in(client, BOB, ADMIN_PASSWORD)
    assert response.status_code == 200
    assert response.json()["is_admin"] is True
    assert client.get("/api/admin/overview").status_code == 200


@pytest.mark.usefixtures("gated")
def test_the_overview_lists_people_and_teams(client):
    body = _as_admin(client).get("/api/admin/overview").json()
    assert {user["email"] for user in body["users"]} == {ALICE, BOB}
    assert [team["id"] for team in body["teams"]] == [settings.default_team]
    assert body["you"]["email"] == BOB


@pytest.mark.usefixtures("gated")
def test_an_admin_can_add_someone_who_can_then_sign_in(client):
    _as_admin(client).post("/api/admin/users", json={"email": "New.Person@T2.sa"})

    with TestClient(app) as fresh:
        assert _sign_in(fresh, "new.person@t2.sa", CODE).status_code == 200


@pytest.mark.usefixtures("gated")
def test_adding_someone_is_attributed(client):
    _as_admin(client).post("/api/admin/users", json={"email": "new@t2.sa"})
    [event] = events.for_subject("user", "new@t2.sa")
    assert event.kind == events.USER_ADDED and event.actor_email == BOB


@pytest.mark.usefixtures("gated")
def test_removing_someone_takes_effect_on_their_next_request(client):
    with TestClient(app) as member:
        _sign_in(member)
        assert member.get("/api/runs").status_code == 200
        _as_admin(client).delete(f"/api/admin/users/{ALICE}")
        assert member.get("/api/runs").status_code == 401


@pytest.mark.usefixtures("gated")
def test_suspending_someone_takes_effect_immediately(client):
    with TestClient(app) as member:
        _sign_in(member)
        _as_admin(client).patch(f"/api/admin/users/{ALICE}", json={"disabled": True})
        assert member.get("/api/runs").status_code == 401


@pytest.mark.usefixtures("gated")
def test_the_last_administrator_cannot_remove_themselves(client):
    response = _as_admin(client).delete(f"/api/admin/users/{BOB}")
    assert response.status_code == 400
    assert "only administrator" in response.json()["detail"]


@pytest.mark.usefixtures("gated")
def test_the_last_administrator_cannot_demote_themselves(client):
    response = _as_admin(client).patch(f"/api/admin/users/{BOB}", json={"role": "member"})
    assert response.status_code == 400


@pytest.mark.usefixtures("gated")
def test_an_admin_can_step_down_once_someone_else_is_promoted(client):
    _as_admin(client).patch(f"/api/admin/users/{ALICE}", json={"role": "admin"})
    assert client.patch(f"/api/admin/users/{BOB}", json={"role": "member"}).status_code == 200


@pytest.mark.usefixtures("gated")
def test_rotating_a_code_returns_it_once_and_breaks_the_old_one(client):
    body = _as_admin(client).post(
        f"/api/admin/teams/{settings.default_team}/access-code"
    ).json()
    assert body["access_code"] and body["access_code"] != CODE

    with TestClient(app) as member:
        assert _sign_in(member, ALICE, CODE).status_code == 403
        assert _sign_in(member, ALICE, body["access_code"]).status_code == 200


@pytest.mark.usefixtures("gated")
def test_rotating_an_unknown_team_is_a_404(client):
    assert _as_admin(client).post("/api/admin/teams/nope/access-code").status_code == 404


@pytest.mark.usefixtures("gated")
def test_a_new_team_needs_its_own_code_before_anyone_can_use_it(client):
    admin = _as_admin(client)
    admin.post("/api/admin/teams", json={"id": "privacy", "name": "Privacy"})
    admin.patch(f"/api/admin/users/{ALICE}", json={"team": "privacy"})

    with TestClient(app) as member:
        assert _sign_in(member, ALICE, CODE).status_code == 403, "the old team's code must not carry over"
        code = admin.post("/api/admin/teams/privacy/access-code").json()["access_code"]
        assert _sign_in(member, ALICE, code).status_code == 200


@pytest.mark.usefixtures("gated")
def test_a_team_id_must_be_a_slug(client):
    assert _as_admin(client).post(
        "/api/admin/teams", json={"id": "Not A Slug!", "name": "x"}
    ).status_code == 422


@pytest.mark.usefixtures("gated")
def test_a_team_with_members_cannot_be_removed(client):
    response = _as_admin(client).delete(f"/api/admin/teams/{settings.default_team}")
    assert response.status_code == 400
    assert "member" in response.json()["detail"]


@pytest.mark.usefixtures("gated")
def test_the_break_glass_admins_password_cannot_be_changed_here(client, monkeypatch):
    """It would be restored on the next restart, so refusing says so plainly."""
    monkeypatch.setattr(settings, "admin_email", BOB)
    response = _as_admin(client).post(
        f"/api/admin/users/{BOB}/password", json={"password": "something-else"}
    )
    assert response.status_code == 400
    assert "restart" in response.json()["detail"]


@pytest.mark.usefixtures("gated")
def test_setting_a_password_switches_someone_off_the_team_code(client):
    _as_admin(client).post(f"/api/admin/users/{ALICE}/password", json={"password": "own-password-here"})
    with TestClient(app) as member:
        assert _sign_in(member, ALICE, CODE).status_code == 403
        assert _sign_in(member, ALICE, "own-password-here").status_code == 200


@pytest.mark.usefixtures("gated")
def test_setting_a_password_for_an_unknown_user_is_a_404(client):
    assert _as_admin(client).post(
        "/api/admin/users/nobody@t2.sa/password", json={"password": "x"}
    ).status_code == 404


@pytest.mark.usefixtures("gated")
def test_the_admin_deep_link_serves_the_app_itself(client):
    """The panel lives inside the app, because a deployment may expose only the
    application's own address. `/admin` is a convenience, not a boundary."""
    response = _as_admin(client).get("/admin")
    assert response.status_code == 200
    # The app's own page, identified by markup only it has — not a whole-file
    # comparison, which would fail on line endings rather than on substance.
    assert 'id="adminDrawer"' in response.text
    assert 'id="questionListPanel"' in response.text


def test_the_admin_deep_link_needs_no_session(client):
    """It is only a document. What it can *do* is gated by /api/admin/*, which
    is what a request without an administrator session actually hits."""
    assert client.get("/admin").status_code == 200


# --- history ---------------------------------------------------------------


def test_runs_starts_empty(client):
    assert client.get("/api/runs").json() == {"runs": []}


def test_an_unknown_run_is_a_404(client):
    assert client.get("/api/runs/nope").status_code == 404


def test_answering_leaves_a_run_behind(client, monkeypatch):
    """The Phase 0 gate: every answer traces to a person and a run."""
    async def fake_answer_questions(questions, language=None, run_id=None, **_):
        return [
            AnsweredQuestion(
                question=questions[0],
                answer="Yes, AES-256 is applied.",
                confidence=0.9,
                needs_review=False,
                citations=["T2 - Cryptography Policy.pdf §3.5.1"],
            )
        ]

    monkeypatch.setattr("src.api.service.answer_questions", fake_answer_questions)

    response = client.post(
        "/api/assessments/answer-questions",
        json={
            "questions": [{"text": "Do you encrypt data at rest?"}],
            "run_id": "run-abc",
            "source_name": "PSAT Questionnaire v2.1.xlsx",
        },
    )
    assert response.status_code == 200

    listed = client.get("/api/runs").json()["runs"]
    assert [run["run_id"] for run in listed] == ["run-abc"]
    assert listed[0]["actor_email"] == identity.LOCAL_EMAIL

    detail = client.get("/api/runs/run-abc").json()
    assert detail["answers"][0]["answer"] == "Yes, AES-256 is applied."
    assert [entry["kind"] for entry in detail["history"]] == [events.RUN_FINISHED]


def test_a_failure_to_save_does_not_lose_the_answers(client, monkeypatch, caplog):
    """A run costs minutes. Losing the history is bad; losing the answers is worse."""
    async def fake_answer_questions(questions, language=None, run_id=None, **_):
        return [AnsweredQuestion(question=questions[0], answer="Yes.", confidence=0.9)]

    def explode(*args, **kwargs):
        raise RuntimeError("disk is full")

    monkeypatch.setattr("src.api.service.answer_questions", fake_answer_questions)
    monkeypatch.setattr(runs, "save", explode)

    response = client.post(
        "/api/assessments/answer-questions",
        json={"questions": [{"text": "Do you encrypt data at rest?"}]},
    )
    assert response.status_code == 200
    assert response.json()["answers"][0]["answer"] == "Yes."
    assert "Could not save run" in caplog.text


@pytest.mark.usefixtures("gated")
def test_a_run_is_attributed_to_whoever_signed_in(client, monkeypatch):
    async def fake_answer_questions(questions, language=None, run_id=None, **_):
        return [AnsweredQuestion(question=questions[0], answer="Yes.", confidence=0.9)]

    monkeypatch.setattr("src.api.service.answer_questions", fake_answer_questions)
    _sign_in(client)

    client.post(
        "/api/assessments/answer-questions",
        json={"questions": [{"text": "Do you encrypt data at rest?"}], "run_id": "r9"},
    )
    assert client.get("/api/runs").json()["runs"][0]["actor_email"] == ALICE


def test_events_can_be_filtered_by_kind(client):
    user = identity.local_user()
    events.record(user, events.SIGNED_IN)
    events.record(user, events.RUN_FINISHED, subject_type="run", subject_id="r1")

    listed = client.get("/api/events", params={"kind": events.RUN_FINISHED}).json()["events"]
    assert [event["subject_id"] for event in listed] == ["r1"]


# --- the pages -------------------------------------------------------------


def _page(name: str) -> str:
    from src.api import STATIC_DIR

    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_the_sign_in_screen_asks_for_both_things():
    html = _page("index.html")
    for element in ("authGate", "authForm", "authEmail", "authCode", "authError", "signOut"):
        assert f'id="{element}"' in html, f"the sign-in screen lost #{element}"


def test_elements_that_set_display_restate_the_hidden_rule():
    """A class selector outranks the browser's own `[hidden] { display: none }`.

    `.auth-gate` sets `display: grid`, which silently defeated the `hidden`
    attribute and left the sign-in overlay covering the page for a user who was
    already signed in — the API said 200, the screen said sign in.
    """
    html = _page("index.html")
    assert ".auth-gate[hidden]" in html
    assert ".whoami[hidden]" in html


def test_the_access_panel_only_appears_for_administrators():
    html = _page("index.html")
    assert 'id="adminLink"' in html
    assert "session.is_admin" in html


def test_the_access_panel_lives_in_the_main_page():
    """There is one implementation, reachable without navigating anywhere."""
    html = _page("index.html")
    for element in ("adminDrawer", "adminUsers", "adminTeams", "adminCodeValue", "adminAddUser"):
        assert f'id="{element}"' in html, f"the access panel lost #{element}"
    assert "openAccessPanel" in html
    assert 'href = "/admin"' not in html, "the panel must not navigate away to reach itself"


def test_the_access_panel_classes_do_not_collide_with_the_app():
    """The panel shares a document with the app, which already owns .row,
    .panel and .status — so every rule it adds is prefixed."""
    html = _page("index.html")
    panel = html[html.index("--- access panel"):html.index("--- sign-in gate")]
    for line in panel.splitlines():
        stripped = line.strip()
        if stripped.startswith(".") and "{" in stripped:
            assert stripped.startswith(".adm-"), f"unprefixed panel rule: {stripped}"


def test_the_question_endpoint_still_works_before_anyone_is_added(client, monkeypatch):
    async def fake_extract(path):
        return "en", [Question(id="1", text="Do you encrypt data at rest?")]

    monkeypatch.setattr("src.api.service.extract_assessment_questions", fake_extract)
    monkeypatch.setattr("src.api.service.save_upload", lambda name, content: settings.upload_dir / name)

    response = client.post(
        "/api/assessments/extract",
        files={"file": ("questions.docx", b"stub", "application/octet-stream")},
    )
    assert response.status_code == 200
