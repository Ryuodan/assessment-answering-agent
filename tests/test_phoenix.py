"""The Phoenix trace viewer: administrators only, and the request carried without the session (plan 044).

Phoenix holds a copy of every prompt, policy text and questionnaire included,
and has no sign-in of its own. These hold the gate in front of it, what crosses
to it, and the launcher that starts it.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts import serve_phoenix
from src import identity
from src.api import app
from src.config import PROJECT_ROOT, Settings, settings
from src.routes.phoenix import SIGN_IN_PAGE
from src.routes.pages import STATIC_DIR

MEMBER = "member@example.com"
ADMIN = "admin@example.com"
CODE = "TEAM-CODE-FOR-TESTS"
ADMIN_PASSWORD = "a-long-admin-password"
PAGE = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
JSON = {"accept": "application/json"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def gated():
    """A team with a code, one member and one administrator."""
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(MEMBER)
    identity.add_user(ADMIN, role=identity.ADMIN, password=ADMIN_PASSWORD)


def _sign_in(client: TestClient, email: str, code: str) -> None:
    assert client.post("/api/auth/session", json={"email": email, "code": code}).status_code == 200


@pytest.fixture
def upstream(monkeypatch):
    """Phoenix, faked at httpx: what was sent to it, and a gzipped answer with a cookie of its own."""
    seen: dict = {}

    async def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=str(url), headers=kwargs.get("headers", {}), content=kwargs.get("content"))
        return httpx.Response(
            200,
            content=gzip.compress(b"Phoenix is reachable"),
            headers={"content-encoding": "gzip", "content-type": "text/plain", "set-cookie": "phoenix=1"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    return seen


# --- who may look -------------------------------------------------------------


def test_open_mode_never_lets_the_local_stand_in_through(client, upstream):
    """With nobody added the app runs open, as an administrator-shaped stand-in. Phoenix must not."""
    response = client.get("/phoenix/", headers=JSON)

    assert response.status_code == 401
    assert response.json()["code"] == "phoenix_sign_in_required"
    assert upstream == {}


@pytest.mark.usefixtures("gated")
def test_a_script_without_a_session_gets_json(client, upstream):
    """Phoenix's own fetches come through this route: HTML where they expect JSON would be worse than a 401."""
    response = client.get("/phoenix/graphql", headers=JSON)

    assert response.status_code == 401
    assert response.json()["code"] == "phoenix_sign_in_required"
    assert upstream == {}


@pytest.mark.usefixtures("gated")
def test_a_member_is_refused(client, upstream):
    _sign_in(client, MEMBER, CODE)

    response = client.post("/phoenix/graphql", json={}, headers=JSON)

    assert response.status_code == 403
    assert response.json()["code"] == "admin_required"
    assert upstream == {}


@pytest.mark.usefixtures("gated")
def test_a_browser_without_a_session_is_offered_a_sign_in(client, upstream):
    """Phoenix is opened by its own URL, so the refusal has to say how to get in."""
    response = client.get("/phoenix/", headers=PAGE)

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("text/html")
    assert "Sign in to view Phoenix" in response.text
    assert upstream == {}


@pytest.mark.usefixtures("gated")
def test_the_sign_in_page_says_when_the_account_is_not_an_administrator(client):
    _sign_in(client, MEMBER, CODE)

    response = client.get("/phoenix/", headers=PAGE)

    assert response.status_code == 401
    assert f"Signed in as {MEMBER}, which is not an administrator." in response.text


def test_the_sign_in_page_names_the_api_without_the_deployments_prefix():
    """nginx rewrites `/api/` in the HTML it serves. A prefix written here as well is applied twice."""
    html = (STATIC_DIR / SIGN_IN_PAGE).read_text(encoding="utf-8")

    assert '"/api/auth/session"' in html
    assert not re.search(r"[\"']/assessment", html), "a prefix in a string literal"
    assert not re.search(r"location\.(pathname|href)", html), "a prefix computed from the address"


# --- what crosses -------------------------------------------------------------


@pytest.mark.usefixtures("gated")
def test_an_administrator_reaches_phoenix_without_the_session_crossing(client, upstream):
    _sign_in(client, ADMIN, ADMIN_PASSWORD)

    response = client.get("/phoenix/projects?limit=1")

    assert response.status_code == 200
    assert response.text == "Phoenix is reachable"
    assert upstream["url"] == f"http://{settings.phoenix_host}:{settings.phoenix_port}/projects?limit=1"
    assert "cookie" not in {name.lower() for name in upstream["headers"]}
    assert upstream["headers"]["Accept-Encoding"] == "identity"
    assert "content-encoding" not in response.headers
    assert "set-cookie" not in response.headers


@pytest.mark.usefixtures("gated")
def test_a_path_cannot_name_another_host(client, upstream):
    _sign_in(client, ADMIN, ADMIN_PASSWORD)

    client.get("/phoenix///elsewhere.example/steal")

    assert httpx.URL(upstream["url"]).host == settings.phoenix_host
    assert httpx.URL(upstream["url"]).port == settings.phoenix_port


@pytest.mark.usefixtures("gated")
def test_a_body_is_carried(client, upstream):
    _sign_in(client, ADMIN, ADMIN_PASSWORD)

    client.post("/phoenix/graphql", content=b'{"query": "{ projects }"}', headers={"content-type": "application/json"})

    assert upstream["method"] == "POST"
    assert upstream["content"] == b'{"query": "{ projects }"}'


@pytest.mark.usefixtures("gated")
def test_phoenix_down_is_unavailable_not_a_crash(client, monkeypatch):
    async def refused(self, method, url, **kwargs):
        raise httpx.ConnectError("Connection refused", request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", refused)
    _sign_in(client, ADMIN, ADMIN_PASSWORD)

    response = client.get("/phoenix/", headers=JSON)

    assert response.status_code == 503
    assert response.json()["code"] == "phoenix_unavailable"


@pytest.mark.usefixtures("gated")
def test_the_address_without_its_slash_stays_under_the_prefix(client):
    _sign_in(client, ADMIN, ADMIN_PASSWORD)

    response = client.get("/phoenix", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "phoenix/"


@pytest.mark.usefixtures("gated")
def test_the_address_without_its_slash_is_gated_too(client):
    response = client.get("/phoenix", headers=JSON, follow_redirects=False)

    assert response.status_code == 401


# --- the launcher ---------------------------------------------------------------


def test_the_launcher_passes_only_the_server_settings_that_are_set():
    config = Settings(phoenix_port=6010, phoenix_host_root_path="/assessment/phoenix", phoenix_root_url="")

    env = serve_phoenix.server_environment(config, {"PATH": "/usr/bin"})

    assert env["PATH"] == "/usr/bin"
    assert env["PHOENIX_PORT"] == "6010"
    assert env["PHOENIX_HOST_ROOT_PATH"] == "/assessment/phoenix"
    assert "PHOENIX_ROOT_URL" not in env
    assert "PHOENIX_WORKING_DIR" not in env


def test_a_relative_working_directory_is_the_projects():
    assert serve_phoenix.working_dir("data/phoenix") == str((PROJECT_ROOT / "data" / "phoenix").resolve())
    assert serve_phoenix.working_dir("/srv/phoenix") == "/srv/phoenix"


def test_the_launcher_refuses_a_missing_command(tmp_path: Path):
    with pytest.raises(SystemExit, match="PHOENIX_EXECUTABLE"):
        serve_phoenix.executable(Settings(phoenix_executable=str(tmp_path / "no-such-phoenix")))
