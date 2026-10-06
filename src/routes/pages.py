"""Serving the pages: each names its shared assets by a fingerprint of their content.

Moved out of `src/api.py` unchanged (plan 020), so that a router can serve a
page without importing the application module.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

STATIC_DIR = Path(__file__).parent.parent / "static"


SHARED_ASSETS = ("cards.js", "cards.css")
"""The scripts and styles every page loads, and the reason pages are not plain files.

A page and the shared script it calls are two downloads, and a browser caches
them separately. Served with no caching instructions, a browser that had
yesterday's `cards.js` kept it -- for hours, on its own heuristic -- while
fetching today's page, and the page called a function the old script did not
have: the assistant's answer panel opened and stayed empty. So each page names
its shared assets by a fingerprint of their content. A changed script is a new
URL, which no cache can hold an older copy of.
"""


NO_CACHE = {"Cache-Control": "no-cache"}
"""Revalidate every time. Not "do not store": an unchanged file still comes back
as a 304 against its ETag, so this costs a request and not a download."""


def _fingerprint(name: str) -> str:
    path = STATIC_DIR / name
    stat = path.stat()
    return _fingerprint_of(name, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=32)
def _fingerprint_of(name: str, mtime_ns: int, size: int) -> str:
    """Keyed on the file's timestamp and size, so an edit is a fresh hash."""
    return hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:12]


def page(name: str) -> HTMLResponse:
    """One of the pages, pointing at the exact version of the shared assets on disk.

    The pages name the assets and each other relatively -- `static/cards.js`,
    `memory` -- because the deployment serves this app under a prefix, and nginx
    rewrites only `/api/` into it. Every page is one level below the app's root,
    so a relative reference lands in the same place at `/` and at `/assessment/`.
    """
    html = (STATIC_DIR / name).read_text(encoding="utf-8")
    for asset in SHARED_ASSETS:
        html = html.replace(f'"static/{asset}"', f'"static/{asset}?v={_fingerprint(asset)}"')
    return HTMLResponse(html, headers=NO_CACHE)


class RevalidatedStatic(StaticFiles):
    """Static files a browser checks before reusing, for the same reason as `page`."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response
