"""A file being read is not removed by deleting other work made from it (TD-078).

`save_upload` gives identical content one name, so the same file can be read again
while a questionnaire already made from it is deleted. Deletion asked only whether a
saved questionnaire read the file, so it removed the file from under the new read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import batches, chat_running, lists, reading, service, tools
from src.api import app
from tests import forms_fixtures as shapes


@pytest.fixture(autouse=True)
def nothing_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_running, "_RUNNING", {})


def opened(client: TestClient, path: Path) -> dict[str, Any]:
    response = client.post("/api/forms", files={"file": (path.name, path.read_bytes())}, data={"product": ""})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_hold_counts_its_readers_and_lets_go(tmp_path: Path) -> None:
    path = tmp_path / "vendor.xlsx"
    assert not reading.being_read(path)
    with reading.holding(path):
        assert reading.being_read(path) and not reading.being_read(path, besides=1)
        with reading.holding(tmp_path / "." / "vendor.xlsx"):
            assert reading.being_read(path, besides=1), "the same file, however it is spelt"
    assert not reading.being_read(path)
    with pytest.raises(RuntimeError), reading.holding(path):
        raise RuntimeError("the read failed")
    assert not reading.being_read(path), "let go however the read ends"


def test_deleting_a_questionnaire_leaves_its_file_to_a_read_of_it_under_way(tmp_path: Path) -> None:
    client = TestClient(app)
    first = opened(client, shapes.simple(tmp_path / "vendor.xlsx"))
    source = batches.load(first["id"]).source_path

    with reading.holding(source):  # the same file, given again, being read
        assert client.delete(f"/api/forms/{first['id']}").status_code == 200
        assert source.is_file(), "the new read still has its file"
    assert client.get(f"/api/forms/{first['id']}").status_code == 404, "the questionnaire went"


@pytest.mark.asyncio
async def test_a_list_that_found_nothing_leaves_a_file_another_read_holds(tmp_path: Path, monkeypatch) -> None:
    from src import identity

    path = tmp_path / "questions.pdf"
    path.write_bytes(b"%PDF-1.4")

    async def nothing(_path):
        return "en", []

    monkeypatch.setattr(service, "extract_assessment_questions", nothing)
    with reading.holding(path), reading.holding(path):  # this read, and another of the same file
        with pytest.raises(Exception):
            await lists.read_list(identity.local_user(), path)
    assert path.is_file()

    with reading.holding(path):  # this read alone
        with pytest.raises(Exception):
            await lists.read_list(identity.local_user(), path)
    assert not path.exists(), "with no other read, the empty upload goes as before"


def test_each_route_holds_the_file_while_it_reads_it(tmp_path: Path, monkeypatch) -> None:
    seen: list[bool] = []
    real_open = tools.open_form

    def open_form(user, path, **kwargs):
        seen.append(reading.being_read(path))
        return real_open(user, path, **kwargs)

    monkeypatch.setattr(tools, "open_form", open_form)
    opened(TestClient(app), shapes.simple(tmp_path / "vendor.xlsx"))

    real_list = lists.read_list

    async def read_list(user, path, **kwargs):
        seen.append(reading.being_read(path))
        return await real_list(user, path, **kwargs)

    async def found(_path):
        from src.models import Question

        return "en", [Question(id="1", text="Do you encrypt backups?", language="en")]

    monkeypatch.setattr(lists, "read_list", read_list)
    monkeypatch.setattr(service, "extract_assessment_questions", found)
    response = TestClient(app).post(
        "/api/forms/list", files={"file": ("questions.pdf", b"%PDF-1.4")}, data={"product": ""}
    )
    assert response.status_code == 200, response.text
    assert seen == [True, True]
