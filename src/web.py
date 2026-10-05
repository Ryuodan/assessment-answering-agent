"""What every HTTP request shares: its ID, its log line, and how errors answer.

    web.install(app)

* **Request ID.** A well-formed incoming `X-Request-ID` (8 to 64 letters,
  digits, `.`, `_`, `-`; a proxy may set one) is kept, anything else replaced.
  It is on every log record made while the request runs (`src/logs.py`), in
  the response's `X-Request-ID` header, and in every error body.
* **One log line per request**, `http.request`, with the method, the route
  *template* (`/api/documents/{origin}/{category}/{name}/file`), the status
  and the time taken. Never the raw path or the query string: they carry file
  names and search text, which can be a customer's.
* **Errors.** `{"detail": <message>, "code": <code>, "request_id": <id>}` for
  every error: the application's own (`src/errors.py`, D-013), FastAPI's
  refusals, validation failures, and anything unexpected, whose detail goes to
  the log and never to the response.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src import logs
from src.errors import AppError

REQUEST_ID_HEADER = "X-Request-ID"
_WELL_FORMED = re.compile(r"[A-Za-z0-9._-]{8,64}")
# Codes for the errors FastAPI raises itself (an unknown route, a wrong method).
_FRAMEWORK_CODES = {404: "route_not_found", 405: "method_not_allowed"}

log = logs.get_logger(__name__)


def install(app: FastAPI) -> None:
    app.add_middleware(RequestContext)
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _framework_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(Exception, _unhandled)


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or logs.current_request_id()


def _route(scope: Scope) -> str:
    route = scope.get("route")
    return str(getattr(route, "path", "")) or "(no route)"


class RequestContext:
    """Pure ASGI middleware: background work and streamed responses keep the ID."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(REQUEST_ID_HEADER.lower().encode(), b"").decode("latin-1")
        request_id = incoming if _WELL_FORMED.fullmatch(incoming) else uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500  # unless a response starts: an exception escaping the app is answered with a 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                if not any(name.lower() == b"x-request-id" for name, _ in headers):  # error responses set it already
                    message = {**message, "headers": [*headers, (b"x-request-id", request_id.encode())]}
            await send(message)

        with logs.request_context(request_id):
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                log.info(
                    "http.request",
                    method=scope.get("method", ""),
                    route=_route(scope),
                    status=status,
                    ms=round((time.perf_counter() - started) * 1000, 1),
                )


def _error(
    request: Request, status: int, detail: Any, code: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    request_id = request_id_of(request)
    return JSONResponse(
        status_code=status,
        content={"detail": detail, "code": code, "request_id": request_id},
        headers={**(headers or {}), REQUEST_ID_HEADER: request_id},
    )


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    """An error the application raised on purpose: its message is safe to show."""
    error = cast(AppError, exc)  # registered for AppError only
    if error.status >= 500:
        log.warning("http.app_error", code=error.code, status=error.status, route=_route(request.scope))
    return _error(request, error.status, error.message, error.code)


async def _framework_error(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's own refusals, given a code like everything else."""
    error = cast(StarletteHTTPException, exc)  # registered for HTTPException only
    code = _FRAMEWORK_CODES.get(error.status_code, "http_error")
    return _error(request, error.status_code, error.detail, code, getattr(error, "headers", None))


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """A body or parameter that does not match its model: FastAPI's detail, plus a code."""
    error = cast(RequestValidationError, exc)  # registered for RequestValidationError only
    return _error(request, 422, jsonable_encoder(error.errors()), "validation_failed")


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Turn an unexpected failure into a clean 500 rather than a traceback.

    Everything behind the routes talks to something that can be down -- Chroma,
    the embedding host, Groq, Docling, the disk. Without this FastAPI returns its
    default error page, which carries server paths into the browser and tells the
    person nothing they can act on. The detail stays in the log, under the same
    request ID the person is shown.

    This runs outside the request middleware (Starlette calls it from its
    outermost layer), so the request's context is entered again here.
    """
    with logs.request_context(request_id_of(request)):
        log.exception("http.unhandled_error", method=request.method, route=_route(request.scope))
    return _error(request, 500, "Something went wrong on the server. The details are in its log.", "internal_error")
