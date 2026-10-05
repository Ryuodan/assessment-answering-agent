"""What the API answers when something goes wrong: status and body, per path.

Recorded before plan 004 replaced the four exception wrappers and the
hand-built HTTPExceptions with one error hierarchy, so that the change could
be reviewed as a diff: every difference must be one the plan intends.

Each scenario triggers one kind of error through the routes a person uses.
Settings are pinned to their defaults (`default_settings`), Docling is off, and
the model key is empty, so nothing here depends on a developer's .env or on a
network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import identity, service
from src.api import app
from src.config import settings

ALICE = "alice@example.com"
BOB = "bob@example.com"
CODE = "TEAM-CODE-FOR-TESTS"
ADMIN_PASSWORD = "a-long-admin-password"


def body(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def record(scenarios: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, call in scenarios.items():
        response = call()
        out[name] = {"status": response.status_code, "body": body(response)}
    return out


@pytest.fixture
def quiet(default_settings, monkeypatch):
    monkeypatch.setattr(settings, "docling_base_url", "")
    monkeypatch.setattr(settings, "groq_api_key", "")
    return settings


def test_open_mode_error_responses(quiet, monkeypatch, snapshot):
    client = TestClient(app, raise_server_exceptions=False)
    uploads = settings.user_upload_dir(settings.default_team, identity.LOCAL_EMAIL)
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "corrupt.docx").write_bytes(b"this is not a zip archive")
    flagged_only = {
        "run_id": "r1",
        "source_name": "form.xlsx",
        "language": "en",
        "questions_found": 1,
        "answers": [{"question": {"id": "1", "text": "Q?"}, "answer": "A.", "confidence": 0.2, "needs_review": True}],
    }

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("internal detail that must not reach a browser: C:/secret/path")

    def unexpected() -> Any:
        with monkeypatch.context() as patch:
            patch.setattr(service, "list_documents", failing)
            return client.get("/api/documents")

    scenarios = {
        "unknown route": lambda: client.get("/api/does-not-exist"),
        "questionnaire not found": lambda: client.get("/api/forms/nope"),
        "questionnaire with an unsupported suffix": lambda: client.post(
            "/api/forms", files={"file": ("notes.txt", b"hello", "text/plain")}
        ),
        "questionnaire that cannot be read": lambda: client.post(
            "/api/forms", files={"file": ("broken.xlsx", b"not a zip", "application/octet-stream")}
        ),
        "run not found": lambda: client.get("/api/runs/nope"),
        "conversation not found": lambda: client.get("/api/chat/nope"),
        "progress not found": lambda: client.get("/api/assessments/progress/nope"),
        "policy upload of an unsupported type": lambda: client.post(
            "/api/knowledge/guidelines", files=[("files", ("notes.txt", b"x", "text/plain"))]
        ),
        "policy upload without files": lambda: client.post("/api/knowledge/guidelines"),
        "policy to remove not found": lambda: client.delete("/api/knowledge/sources/missing.pdf"),
        "memory entry not found": lambda: client.patch("/api/memory/nope", json={"answer": "x"}),
        "skill not found": lambda: client.delete("/api/skills/nope"),
        "document name invalid": lambda: client.get("/api/documents/uploaded/uploaded/notes.txt/file"),
        "document location invalid": lambda: client.get("/api/documents/bundled/x/a.pdf/file"),
        "document not found": lambda: client.get("/api/documents/uploaded/uploaded/missing.pdf/file"),
        "search mode unknown": lambda: client.get("/api/search", params={"q": "x", "mode": "bogus"}),
        "export with nothing confident": lambda: client.post("/api/assessments/export/pdf", json=flagged_only),
        "request body that fails validation": lambda: client.put("/api/preferences", json={"tone": "shouty"}),
        "preference refused": lambda: client.put("/api/preferences", json={"refer_to": '"T2"'}),
        "assistant without a model": lambda: client.post("/api/chat", json={"message": "hi"}),
        "preview of a corrupt Word file": lambda: client.get("/api/documents/uploaded/uploaded/corrupt.docx/preview"),
        "text of a corrupt Word file": lambda: client.get("/api/documents/uploaded/uploaded/corrupt.docx/text"),
        "unexpected failure": unexpected,
    }
    snapshot("errors/open-mode", record(scenarios))


def test_signed_in_error_responses(quiet, snapshot):
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)
    identity.add_user(BOB, role=identity.ADMIN, password=ADMIN_PASSWORD)
    stranger = TestClient(app, raise_server_exceptions=False)
    member = TestClient(app, raise_server_exceptions=False)
    admin = TestClient(app, raise_server_exceptions=False)
    assert member.post("/api/auth/session", json={"email": ALICE, "code": CODE}).status_code == 200
    assert admin.post("/api/auth/session", json={"email": BOB, "code": ADMIN_PASSWORD}).status_code == 200

    scenarios = {
        "not signed in": lambda: stranger.get("/api/runs"),
        "wrong access code": lambda: stranger.post("/api/auth/session", json={"email": ALICE, "code": "WRONG"}),
        "member on an administrator route": lambda: member.get("/api/admin/overview"),
        "administrator refused": lambda: admin.delete(f"/api/admin/teams/{settings.default_team}"),
        "administrator: unknown user": lambda: admin.post(
            "/api/admin/users/nobody@example.com/password", json={"password": "another-long-password"}
        ),
        "administrator: the only administrator demoted": lambda: admin.patch(
            f"/api/admin/users/{BOB}", json={"role": "member"}
        ),
    }
    snapshot("errors/signed-in", record(scenarios))
