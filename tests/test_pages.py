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
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from src import api
from src.routes import pages
from src.api import app

PAGES = ["/", "/workbench", "/memory", "/preferences", "/admin", "/products"]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("path", PAGES)
def test_every_page_names_its_shared_assets_by_their_content(client, path):
    body = client.get(path).text

    referenced = re.findall(r'"static/(cards\.(?:js|css))(\?v=[0-9a-f]+)?"', body)
    assert referenced, "each page loads the shared stylesheet at least"
    for asset, version in referenced:
        assert version == f"?v={pages._fingerprint(asset)}", f"{path} loads {asset} unversioned"


@pytest.mark.parametrize("path", PAGES)
def test_every_page_is_revalidated_rather_than_reused(client, path):
    assert client.get(path).headers["cache-control"] == "no-cache"


def test_the_shared_assets_are_revalidated_too(client):
    response = client.get("/static/cards.js")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers.get("etag"), "so an unchanged file costs a 304, not a download"


# --- served under a prefix ---------------------------------------------------
#
# The deployment serves the app at /assessment/ behind nginx, which rewrites
# "/api/" in pages and scripts and nothing else (deploy/nginx-assessment.conf).
# The pages then grew a shared stylesheet, a shared script and links to each
# other, all written from the root -- so on the server `/static/cards.js` asked
# the domain rather than the app, the script never loaded, and every page that
# draws an answer card stopped working.

PREFIX = "/assessment"


def _as_nginx_serves_it(body: str) -> str:
    return body.replace("/api/", f"{PREFIX}/api/")


@pytest.mark.parametrize("path", PAGES)
def test_every_link_and_asset_stays_inside_the_prefix(client, path):
    from urllib.parse import urljoin, urlsplit

    body = _as_nginx_serves_it(client.get(path).text)
    page_url = f"https://host{PREFIX}{path if path != '/' else '/'}"

    for reference in re.findall(r'(?:href|src)="([^"#][^"]*)"', body):
        if reference.startswith(("http:", "https:", "mailto:", "data:", "javascript:")):
            continue
        resolved = urlsplit(urljoin(page_url, reference)).path
        assert resolved.startswith(f"{PREFIX}/"), f"{path}: {reference!r} leaves the app ({resolved})"
        inside = resolved[len(PREFIX) :] or "/"
        assert client.get(inside).status_code != 404, f"{path}: {reference!r} points at nothing"


def test_the_shared_script_names_no_root_path_but_the_api():
    script = (api.STATIC_DIR / "cards.js").read_text(encoding="utf-8")
    rooted = [
        literal
        for literal in re.findall(r"""["'`](/[^"'`\s]*)""", script)
        if not literal.startswith("/api/") and literal not in ("/",)
    ]
    assert not rooted, f"cards.js addresses {rooted} from the domain root"


def test_the_workbench_keeps_its_address_inside_the_prefix():
    """Plan 029, 1.1: the open questionnaire goes into the address. Written
    from the root, a reload under /assessment/ would leave the app."""
    page = (api.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    calls = re.findall(r"history\.(?:replaceState|pushState)\(([^;]*)\)", page)
    assert calls, "the workbench writes the open questionnaire into its address"
    for arguments in calls:
        assert not re.search(r"""["'`]/""", arguments), f"a rooted address: {arguments}"


def test_the_old_chat_address_redirects_within_the_prefix(client):
    response = client.get("/chat", follow_redirects=False)
    assert response.status_code == 308
    assert not response.headers["location"].startswith("/"), "a rooted redirect leaves the prefix"


# --- the bar across the top (TD-041) -----------------------------------------
#
# Five pages each wrote their own header, and they drifted: one had no Sign
# out, the links came in different orders, two carried arrows, and three drew
# them as plain blue text. The links are the same five everywhere, in one
# order, each page leaving out its own.

NAV = [
    ("./", "Assistant"),
    ("workbench", "Workbench"),
    ("memory", "Answer memory"),
    ("preferences", "Preferences"),
    ("products", "Products"),
]
OWN = {"/": "./", "/workbench": "workbench", "/admin": "workbench", "/memory": "memory"}
VOID = {"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Header(HTMLParser):
    """The links (href, text, title) and the ids inside the element with class "topbar"."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0  # inside the bar while > 0
        self.links: list[dict[str, str]] = []
        self.ids: set[str] = set()
        self._link: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = {key: value or "" for key, value in attrs}
        if not self.depth and "topbar" not in named.get("class", "").split():
            return
        if "id" in named:
            self.ids.add(named["id"])
        if tag == "a" and "ghost" in named.get("class", "").split():
            self._link = {"href": named.get("href", ""), "title": named.get("title", ""), "text": ""}
        if tag not in VOID:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag == "a" and self._link is not None:
            self._link["text"] = " ".join(self._link["text"].split())
            self.links.append(self._link)
            self._link = None
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self._link["text"] += data


def _header(client: TestClient, path: str) -> _Header:
    header = _Header()
    header.feed(client.get(path).text)
    return header


@pytest.mark.parametrize("path", PAGES)
def test_every_header_links_the_other_pages_the_same_way(client, path):
    header = _header(client, path)

    own = OWN.get(path, path.lstrip("/"))
    assert [(link["href"], link["text"]) for link in header.links] == [
        (href, text) for href, text in NAV if href != own
    ], f"{path}: the header's links are not the other pages', in the usual order and words"
    assert {"whoami", "whoamiEmail", "signOut", "themeToggle"} <= header.ids, f"{path}: the header lost a control"


def test_a_header_link_says_the_same_on_every_page(client):
    titles: dict[str, set[str]] = {}
    for path in PAGES:
        for link in _header(client, path).links:
            titles.setdefault(link["href"], set()).add(link["title"])

    assert set(titles) == {href for href, _ in NAV}
    for href, said in titles.items():
        assert len(said) == 1 and all(said), f"{href!r} is described differently across the pages: {said}"


def test_changing_a_shared_asset_changes_its_url(tmp_path, monkeypatch):
    """The whole mechanism: a new script is a new URL, which no cache holds."""
    (tmp_path / "cards.js").write_text("const Cards = {};", encoding="utf-8")
    monkeypatch.setattr(pages, "STATIC_DIR", tmp_path)
    before = pages._fingerprint("cards.js")

    (tmp_path / "cards.js").write_text("const Cards = { skillPicker() {} };", encoding="utf-8")

    assert pages._fingerprint("cards.js") != before
