"""Choosing a product on the Workbench before reading a file, for browser tests that are about something else."""

from __future__ import annotations

from playwright.sync_api import Page


def choose_general(page: Page) -> None:
    """Reading a file waits for a product since plan 029 (D-022, the user's decision of
    2026-11-05): nothing is chosen for the person. These tests read as General, chosen on purpose,
    which is what they read as before."""
    page.select_option("#formProduct", "general")
