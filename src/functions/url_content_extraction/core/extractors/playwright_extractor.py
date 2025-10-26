"""Playwright-backed extractor implementation."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

from bs4 import BeautifulSoup

try:  # pragma: no cover - optional dependency
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - fallback for environments without Playwright
    PlaywrightError = PlaywrightTimeoutError = Exception  # type: ignore[misc]
    async_playwright = None

from ..contracts.extracted_content import ExtractedContent, ExtractionMetadata, ExtractionOptions, parse_options
from ..processors.content_cleaner import clean_content
from ..processors.metadata_extractor import enrich_metadata
from ..processors.text_deduplicator import deduplicate_paragraphs
from ..utils import amp_detector, consent_handler


class PlaywrightExtractor:
    """Executes JavaScript-capable extraction using Playwright."""

    _STEALTH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]
    _USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    )

    def __init__(self, *, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def extract(
        self,
        url: str,
        *,
        timeout: Optional[float] = None,
        options: dict | ExtractionOptions | None = None,
    ) -> ExtractedContent:
        """Run the Playwright extraction synchronously with validated options."""

        merged_options: dict[str, object] = {"url": url}
        if timeout:
            merged_options["timeout_seconds"] = int(timeout)
        if options:
            merged_options.update(options if isinstance(options, dict) else options.model_dump())
        validated = parse_options(merged_options)
        return self._run_sync(self._extract(validated))

    @staticmethod
    def _run_sync(coro: "asyncio.Future[ExtractedContent]") -> ExtractedContent:
        try:
            return asyncio.run(coro)
        except RuntimeError:  # pragma: no cover - already running loop
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    @asynccontextmanager
    async def _browser_context(self, options: ExtractionOptions):  # pragma: no cover - thin wrapper
        if async_playwright is None:
            msg = "Playwright is not available in the current environment"
            raise RuntimeError(msg)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=self._STEALTH_ARGS)
            context = await browser.new_context(
                user_agent=self._USER_AGENT,
                locale="en-US",
                timezone_id="UTC",
                ignore_https_errors=True,
            )
            context.set_default_navigation_timeout(options.timeout_seconds * 1000)
            try:
                yield context
            finally:
                await context.close()
                await browser.close()

    async def _extract(self, options: ExtractionOptions) -> ExtractedContent:
        start = time.perf_counter()
        self._logger.debug("Starting Playwright extraction for %s", options.url)
        try:
            async with self._browser_context(options) as context:
                page = await context.new_page()
                await self._navigate(page, str(options.url), options)
                html = await page.content()
                amp_target = amp_detector.find_amp_alternate(html, str(options.url))
                if amp_target and not amp_detector.is_amp_url(str(options.url)):
                    self._logger.debug("Following AMP link for %s", options.url)
                    await self._navigate(page, amp_target, options)
                    html = await page.content()
                await consent_handler.solve_consent(page, logger=self._logger)
                html = await page.content()
                content = self._parse_html(html, page.url)
        except Exception as exc:  # pragma: no cover - defensive umbrella
            self._logger.exception("Playwright extraction failed for %s", options.url)
            return ExtractedContent(url=str(options.url), error=str(exc))

        elapsed = time.perf_counter() - start
        metadata = content.metadata or ExtractionMetadata(
            fetched_at=datetime.utcnow(),
            extractor="playwright",
            duration_seconds=elapsed,
        )
        metadata.duration_seconds = elapsed
        metadata.extractor = "playwright"
        metadata.raw_url = metadata.raw_url or str(options.url)
        content.metadata = metadata

        content = enrich_metadata(content, html=html, extractor_name="playwright")
        content = deduplicate_paragraphs(content)
        content = clean_content(content)
        content.trim(max_paragraphs=options.max_paragraphs)
        if not content.is_valid():
            content.error = content.error or "Insufficient content extracted"
        return content

    async def _navigate(self, page: Any, url: str, options: ExtractionOptions) -> None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=options.timeout_seconds * 1000)
        except PlaywrightTimeoutError as exc:  # pragma: no cover - network variability
            self._logger.warning("Navigation timeout for %s", url)
            raise RuntimeError(f"Navigation timeout for {url}") from exc
        except PlaywrightError as exc:  # pragma: no cover - unexpected Playwright error
            raise RuntimeError(f"Playwright navigation failed: {exc}") from exc

    def _parse_html(self, html: str, url: str) -> ExtractedContent:
        soup = BeautifulSoup(html, "lxml")
        article = soup.find("article") or soup.find("main") or soup.body
        paragraphs = [
            element.get_text(" ", strip=True)
            for element in article.find_all(["p", "li"])  # type: ignore[union-attr]
        ] if article else []
        quotes = [element.get_text(" ", strip=True) for element in soup.find_all("blockquote")]
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        return ExtractedContent(
            url=url,
            title=title,
            paragraphs=paragraphs,
            quotes=quotes,
        )
