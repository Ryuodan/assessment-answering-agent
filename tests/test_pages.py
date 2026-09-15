"""The pages, as a browser receives them.

What broke: a page and the shared script it calls are two downloads, cached
separately, and served with no caching instructions. After an update a browser
kept yesterday's `cards.js` while fetching today's page, the page called a
function the old script did not have, and the assistant's answer panel opened
empty. Nothing in the code was wrong; the two files were simply from different
days. These tests hold the arrangement that makes that impossible.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from src import api
from src.api import app

PAGES = ["/", "/workbench", "/memory", "/preferences", "/admin"]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("path", PAGES)
def test_every_page_names_its_shared_assets_by_their_content(client, path):
    body = client.get(path).text

    referenced = re.findall(r'"/static/(cards\.(?:js|css))(\?v=[0-9a-f]+)?"', body)
    assert referenced, "each page loads the shared stylesheet at least"
    for asset, version in referenced:
        assert version == f"?v={api._fingerprint(asset)}", f"{path} loads {asset} unversioned"


@pytest.mark.parametrize("path", PAGES)
def test_every_page_is_revalidated_rather_than_reused(client, path):
    assert client.get(path).headers["cache-control"] == "no-cache"


def test_the_shared_assets_are_revalidated_too(client):
    response = client.get("/static/cards.js")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers.get("etag"), "so an unchanged file costs a 304, not a download"


def test_changing_a_shared_asset_changes_its_url(tmp_path, monkeypatch):
    """The whole mechanism: a new script is a new URL, which no cache holds."""
    (tmp_path / "cards.js").write_text("const Cards = {};", encoding="utf-8")
    monkeypatch.setattr(api, "STATIC_DIR", tmp_path)
    before = api._fingerprint("cards.js")

    (tmp_path / "cards.js").write_text("const Cards = { skillPicker() {} };", encoding="utf-8")

    assert api._fingerprint("cards.js") != before
