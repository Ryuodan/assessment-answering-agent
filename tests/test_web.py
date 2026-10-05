"""Request IDs, the request log line, and error bodies (src/web.py, plan 005)."""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from src import logs, service
from src.api import app


@pytest.fixture
def lines():
    """JSON log lines written while the test runs, one dict per line."""
    root = logging.getLogger()
    before_handlers, before_level = list(root.handlers), root.level
    buffer = io.StringIO()
    logs.configure("INFO", "json", stream=buffer)

    def read() -> list[dict]:
        return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]

    yield read
    for handler in list(root.handlers):
        if handler not in before_handlers:
            root.removeHandler(handler)
    root.setLevel(before_level)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_every_response_carries_a_request_id(client):
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) >= 8


def test_a_well_formed_incoming_id_is_kept_and_anything_else_replaced(client):
    assert (
        client.get("/api/runs", headers={"X-Request-ID": "proxy-req-0001"}).headers["x-request-id"] == "proxy-req-0001"
    )
    replaced = client.get("/api/runs", headers={"X-Request-ID": "bad id <script>"}).headers["x-request-id"]
    assert replaced != "bad id <script>" and " " not in replaced


def test_an_error_body_names_the_same_id_as_its_header(client):
    response = client.get("/api/runs/nope")
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.headers.get_list("x-request-id") == [response.headers["x-request-id"]], "set once, not twice"


def test_a_request_is_logged_once_by_its_route_never_its_path_or_query(client, lines):
    response = client.get(
        "/api/documents/uploaded/uploaded/Contoso-vendor-review.pdf/file", params={"q": "secret words"}
    )
    [line] = [line for line in lines() if line.get("event") == "http.request"]
    assert line["route"] == "/api/documents/{origin}/{category}/{name}/file"
    assert (line["method"], line["status"], line["request_id"]) == ("GET", 404, response.headers["x-request-id"])
    # The server's own lines; the test client's HTTP library logs the URL it sent, which is client side.
    server = json.dumps([line for line in lines() if line["logger"].startswith("src.")])
    assert "Contoso" not in server and "secret" not in server


def test_an_unexpected_failure_is_logged_under_the_id_the_person_is_shown(client, lines, monkeypatch):
    def failing(*args, **kwargs):
        raise RuntimeError("internal detail")

    monkeypatch.setattr(service, "list_documents", failing)
    response = client.get("/api/documents")
    assert response.status_code == 500
    request_id = response.json()["request_id"]
    assert response.headers["x-request-id"] == request_id
    [error] = [line for line in lines() if line.get("event") == "http.unhandled_error"]
    assert error["request_id"] == request_id and "RuntimeError: internal detail" in error["exception"]
    assert "internal detail" not in response.text
    [request] = [line for line in lines() if line.get("event") == "http.request"]
    assert (request["status"], request["request_id"]) == (500, request_id)
