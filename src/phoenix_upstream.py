"""Phoenix, the trace collector, reached on loopback for the administrators' page (plan 044).

Phoenix has no sign-in of its own, and every trace it holds is a copy of a
prompt: policy text and the customer's questionnaire. So it listens on
`PHOENIX_HOST:PHOENIX_PORT` on this machine only, and `src/routes/phoenix.py`
publishes it to administrators. That route decides who may look; this module
carries one request to Phoenix and its answer back.

The upstream address comes from the settings alone. A request chooses the path
and the query, never the host, so this cannot become a general-purpose proxy.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from src.config import settings
from src.errors import Unavailable
from src.logs import get_logger

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(300.0, connect=5.0)
"""Phoenix's own queries over a large project can be slow; a collector that is down is known in five seconds."""

_REQUEST_HEADERS_TO_DROP = frozenset(
    {
        # The app's own session. It proves access to this process; Phoenix
        # neither needs it nor should keep a copy of it in its request logs.
        "authorization",
        "cookie",
        # Meaningful for one connection only, or set again by the client.
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

_RESPONSE_HEADERS_TO_DROP = frozenset(
    {
        # httpx decodes a compressed body before it is read, so passing on the
        # encoding would have the browser decompress plain bytes a second time.
        "content-encoding",
        # A cookie of Phoenix's would be set on the app's origin.
        "set-cookie",
        "connection",
        "content-length",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


@dataclass(frozen=True)
class Answer:
    """Phoenix's response, as it goes back to the browser."""

    status: int
    headers: dict[str, str]
    content: bytes


def upstream_url(path: str, query: str) -> httpx.URL:
    """Where a request for `path` goes: Phoenix's address, whatever the path says.

    Built from its parts, so a path such as `//elsewhere.example/` stays a path
    on Phoenix's host rather than naming another one.
    """
    return httpx.URL(
        scheme="http",
        host=settings.phoenix_host,
        port=settings.phoenix_port,
        path="/" + path.lstrip("/"),
        query=query.encode("latin-1"),
    )


async def forward(
    method: str,
    path: str,
    query: str,
    headers: Iterable[tuple[str, str]],
    body: bytes,
    forwarded: dict[str, str],
) -> Answer:
    """Send one request to Phoenix and return its answer, less the headers that must not cross.

    `forwarded` is what Phoenix is told about the original request: its host,
    scheme and prefix, so the links it writes point back through the app.
    """
    sent = {name: value for name, value in headers if name.lower() not in _REQUEST_HEADERS_TO_DROP}
    sent.update(forwarded)
    sent["Accept-Encoding"] = "identity"
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT) as client:
            response = await client.request(method, upstream_url(path, query), content=body, headers=sent)
    except httpx.HTTPError as error:
        logger.warning(
            "phoenix.unreachable",
            host=settings.phoenix_host,
            port=settings.phoenix_port,
            error=type(error).__name__,
            fix="start it with ./serve-phoenix.sh",
        )
        raise Unavailable("Phoenix is not available.", code="phoenix_unavailable") from error
    kept = {name: value for name, value in response.headers.items() if name.lower() not in _RESPONSE_HEADERS_TO_DROP}
    return Answer(status=response.status_code, headers=kept, content=response.content)
