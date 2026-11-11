"""The Phoenix trace viewer, published to administrators only (plan 044, D-036).

Phoenix stays on loopback with no sign-in of its own (`src/phoenix_upstream.py`).
These routes put it at `/phoenix/` behind the app's sessions. Not behind
`current_admin`: that one lets everybody through in open mode, as the local
stand-in, and that convenience must never make a store of prompts and
questionnaires reachable from outside. Here only a real administrator's session
passes, whatever the mode.

Phoenix is opened by its own URL, so a browser that arrives without a session
is shown a sign-in form rather than a bare 401 it cannot act on. Phoenix's own
fetches come through the same route, and those get the usual JSON error: HTML
where a script expected JSON would be the worse failure.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src import identity, phoenix_upstream
from src.config import settings
from src.errors import Forbidden, SignInRequired
from src.routes.pages import NO_CACHE, STATIC_DIR

router = APIRouter()

SIGN_IN_PAGE = "phoenix_sign_in.html"
_ERROR_SLOT = '<div class="error" id="error" hidden></div>'


def _is_page_request(request: Request) -> bool:
    """Whether a browser is opening a page, rather than a script fetching data or an asset."""
    return request.method in ("GET", "HEAD") and "text/html" in request.headers.get("accept", "")


def _sign_in_page(note: str = "") -> HTMLResponse:
    """The sign-in form, with `note` in its error slot when there is something to say."""
    html = (STATIC_DIR / SIGN_IN_PAGE).read_text(encoding="utf-8")
    if note:
        html = html.replace(_ERROR_SLOT, f'<div class="error" id="error">{escape(note)}</div>')
    return HTMLResponse(html, status_code=401, headers=NO_CACHE)


def refusal(request: Request) -> HTMLResponse | None:
    """None for a signed-in administrator. Anyone else: the sign-in page for a browser, an error for a script.

    A dependency that returns the page rather than raising it, so the route
    decides what to send and no error class exists only to carry HTML.
    """
    user = identity.resolve(request.cookies.get(identity.SESSION_COOKIE))
    if user is not None and user.is_admin:
        return None
    if _is_page_request(request):
        return _sign_in_page("" if user is None else f"Signed in as {user.email}, which is not an administrator.")
    if user is None:
        raise SignInRequired("Sign in as an administrator to view Phoenix.", code="phoenix_sign_in_required")
    raise Forbidden("Administrator access is required.", code="admin_required")


@router.api_route("/phoenix", methods=["GET", "HEAD"], include_in_schema=False)
def phoenix_root(refused: HTMLResponse | None = Depends(refusal)) -> Response:
    """Phoenix's address without its slash. Relative, like `/chat`'s, so it stays under the deployment's prefix."""
    return refused or RedirectResponse("phoenix/", status_code=308)


@router.api_route(
    "/phoenix/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def phoenix(path: str, request: Request, refused: HTMLResponse | None = Depends(refusal)) -> Response:
    """Phoenix's UI and API, for an administrator.

    nginx removes `/assessment` before a request reaches the app, and Phoenix is
    started with `PHOENIX_HOST_ROOT_PATH=/assessment/phoenix`, so the links it
    writes come back through nginx and this route.
    """
    if refused is not None:
        return refused
    answer = await phoenix_upstream.forward(
        request.method,
        path,
        request.url.query,
        request.headers.items(),
        await request.body(),
        forwarded={
            "X-Forwarded-Host": request.headers.get("host", ""),
            "X-Forwarded-Prefix": settings.phoenix_host_root_path,
            "X-Forwarded-Proto": request.headers.get("x-forwarded-proto", request.url.scheme),
        },
    )
    return Response(content=answer.content, status_code=answer.status, headers=answer.headers)
