"""Browser tests: the real pages in headless Chromium, against the app served in this process.

    uv run poe browser

The server runs in a thread of the test process, so the suite's fixtures
apply to it unchanged: storage in a temporary directory, no real `.env`, and
any monkeypatched model call. Each test gets a fresh server and a fresh page.

Chromium is a separate download, once per machine:

    uv run python -m playwright install chromium
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Browser, Error, Page, sync_playwright

from src.api import app


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def server() -> Iterator[str]:
    """The app on a free local port, for one test."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not instance.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("the test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            chromium = playwright.chromium.launch()
        except Error as error:
            pytest.fail(
                f"Chromium could not start: {str(error).splitlines()[0]}\n"
                "  FIX: uv run python -m playwright install chromium   (once per machine)"
            )
        yield chromium
        chromium.close()


@pytest.fixture
def page(browser: Browser, server: str) -> Iterator[Page]:
    context = browser.new_context(base_url=server)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    context.close()
    assert not errors, f"the page raised: {errors}"
