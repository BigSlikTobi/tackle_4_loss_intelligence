"""Utilities for handling consent and cookie banners."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

try:  # pragma: no cover - optional dependency
    from playwright.async_api import Page  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback when Playwright unavailable
    class Page:  # type: ignore[too-few-public-methods]
        """Minimal stub to allow type checking without Playwright."""

        url: str = ""

        async def query_selector(self, *_args: Any, **_kwargs: Any) -> Any:
            return None


_BUTTON_SELECTORS: Iterable[str] = (
    "button:has-text('Accept')",
    "button:has-text('I Agree')",
    "button:has-text('Agree')",
    "button[aria-label='Agree']",
    "button[title='Accept all']",
    "#onetrust-accept-btn-handler",
)


async def solve_consent(page: Page, *, logger: logging.Logger) -> None:
    """Best-effort attempt to dismiss consent dialogs."""

    for selector in _BUTTON_SELECTORS:
        try:
            button = await page.query_selector(selector)
        except Exception:  # pragma: no cover - defensive
            continue
        if not button:
            continue
        try:
            await asyncio.wait_for(button.click(), timeout=2)
            logger.debug("Dismissed consent dialog using selector '%s'", selector)
            return
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed to click consent selector '%s'", selector)
    logger.debug("No consent dialog handled for page %s", page.url)
