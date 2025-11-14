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
    "button:has-text('Allow all')",
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Continue')",
    "button[aria-label='Agree']",
    "button[aria-label='Accept']",
    "button[aria-label='Accept all']",
    "button[title='Accept all']",
    "button[id*='accept']",
    "button[id*='consent']",
    "button[class*='accept']",
    "button[class*='consent']",
    "#onetrust-accept-btn-handler",
    "button.sp_choice_type_11",  # Common consent button class
    "button[data-testid='accept-all']",
    "button[data-testid='consent-accept']",
)


async def solve_consent(page: Page, *, logger: logging.Logger) -> None:
    """Best-effort attempt to dismiss consent dialogs."""

    # Wait a moment for consent dialog to appear
    await asyncio.sleep(0.5)
    
    for selector in _BUTTON_SELECTORS:
        try:
            # Try to find button with a short timeout
            button = await page.wait_for_selector(selector, timeout=500, state="visible")
        except Exception:  # pragma: no cover - defensive
            continue
        
        if not button:
            continue
            
        try:
            # Click and wait for navigation/changes
            await button.click()
            await asyncio.sleep(0.3)  # Let page reflow after consent
            logger.debug("Dismissed consent dialog using selector '%s'", selector)
            return
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("Failed to click consent selector '%s': %s", selector, e)
            
    logger.debug("No consent dialog handled for page %s", page.url)
