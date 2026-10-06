"""The read-only diagnostics behind `python -m src.cli doctor` and `inspect request`."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src import cli, diagnostics, store
from src.config import settings


def by_name(checks: list[diagnostics.Check]) -> dict[str, diagnostics.Check]:
    return {check.name: check for check in checks}


def test_doctor_writes_nothing(tmp_path: Path) -> None:
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    diagnostics.doctor()
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


def test_missing_storage_is_a_warning_not_a_failure() -> None:
    checks = by_name(diagnostics.doctor())
    assert checks["storage.db_path"].status == diagnostics.WARN
    assert checks["database"].status == diagnostics.WARN
    assert "created on first start" in checks["database"].detail


def test_database_is_described_once_it_exists() -> None:
    store.connect()
    check = diagnostics.database()
    assert check.status == diagnostics.OK
    assert check.detail.startswith("schema version ")
    assert "0 users" in check.detail


def test_a_missing_groq_key_fails_with_a_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "")
    check = by_name(diagnostics.doctor())["config.groq_api_key"]
    assert check.status == diagnostics.FAIL
    assert "GROQ_API_KEY" in check.fix


def test_a_secret_is_reported_as_set_never_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "gsk_" + "x" * 30
    monkeypatch.setattr(settings, "groq_api_key", secret)
    checks = diagnostics.doctor()
    assert by_name(checks)["config.groq_api_key"].detail == "set"
    assert all(secret not in json.dumps(check.as_dict()) for check in checks)


def test_network_probes_report_each_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "docling_base_url", "http://docling.test")

    def answer(request: httpx.Request) -> httpx.Response:
        if "groq" in request.url.host:
            return httpx.Response(401)
        if request.url.host == "docling.test":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(answer)) as client:
        checks = by_name(diagnostics.network(client))

    assert checks["network.groq"].status == diagnostics.FAIL
    assert "refused" in checks["network.groq"].fix
    assert checks["network.embeddings"].status == diagnostics.OK
    assert checks["network.docling"].status == diagnostics.FAIL
    assert "ConnectError" in checks["network.docling"].detail


def test_request_lines_finds_both_log_formats(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_text(
        "2026-10-06 10:00:00 INFO     src.web http.request route=/api/forms status=200 request_id=abc123\n"
        "2026-10-06 10:00:01 INFO     src.web http.request route=/api/forms status=200 request_id=other\n"
        '{"event": "http.request", "request_id": "abc123"}\n'
        'INFO:     127.0.0.1:5000 - "GET /api/forms HTTP/1.1" 200 OK\n',
        encoding="utf-8",
    )
    lines = list(diagnostics.request_lines("abc123", log))
    assert len(lines) == 2
    assert all("abc123" in line for line in lines)


def test_cli_doctor_exit_code_follows_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "")
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  config.groq_api_key" in out
    assert "FIX: set GROQ_API_KEY in .env" in out

    monkeypatch.setattr(settings, "groq_api_key", "configured")
    assert cli.main(["doctor", "--json"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["name"] for row in rows} >= {"python.interpreter", "database"}


def test_cli_inspect_request(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "server.log"
    log.write_text("x request_id=r1\ny request_id=r2\n", encoding="utf-8")
    assert cli.main(["inspect", "request", "r1", "--log", str(log)]) == 0
    assert capsys.readouterr().out == "x request_id=r1\n"
    assert cli.main(["inspect", "request", "nope", "--log", str(log)]) == 1
    assert cli.main(["inspect", "request", "r1", "--log", str(tmp_path / "missing.log")]) == 1
    assert "FIX" in capsys.readouterr().err
