"""HTTP-only extractor implementation using httpx and BeautifulSoup."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from ..contracts.extracted_content import ExtractedContent, ExtractionMetadata, ExtractionOptions, parse_options
from ..processors.content_cleaner import clean_content
from ..processors.metadata_extractor import enrich_metadata
from ..processors.text_deduplicator import deduplicate_paragraphs
from ..utils import amp_detector


class LightExtractor:
    """Performs fast HTTP extraction for simple pages."""

    _DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, *, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def extract(
        self,
        url: str,
        *,
        timeout: Optional[float] = None,
        options: dict | ExtractionOptions | None = None,
    ) -> ExtractedContent:
        merged: dict[str, object] = {"url": url}
        if timeout:
            merged["timeout_seconds"] = int(timeout)
        if options:
            merged.update(options if isinstance(options, dict) else options.model_dump())
        validated = parse_options(merged)
        return self._run_sync(validated)

    def _run_sync(self, options: ExtractionOptions) -> ExtractedContent:
        """Execute async extraction synchronously, handling existing event loops."""
        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - safe to use asyncio.run()
            return asyncio.run(self._extract(options))
        
        # Running loop exists - create and use a new one in a thread-safe way
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, self._extract(options))
            return future.result(timeout=options.timeout_seconds + 10)

    async def _fetch(self, options: ExtractionOptions) -> tuple[str, str]:
        async with httpx.AsyncClient(headers=self._DEFAULT_HEADERS, follow_redirects=True, timeout=options.timeout_seconds) as client:
            response = await client.get(str(options.url))
            response.raise_for_status()
            html = response.text
            amp_alternate = amp_detector.find_amp_alternate(html, str(options.url))
            if amp_alternate:
                self._logger.debug("Discovered AMP alternate for %s", options.url)
                response = await client.get(amp_alternate)
                response.raise_for_status()
                html = response.text
                return amp_alternate, html
            return str(options.url), html

    async def _extract(self, options: ExtractionOptions) -> ExtractedContent:
        start = time.perf_counter()
        self._logger.debug("Starting lightweight extraction for %s", options.url)
        try:
            target_url, html = await self._fetch(options)
        except httpx.HTTPError as exc:
            self._logger.warning("HTTP extraction failed for %s: %s", options.url, exc)
            return ExtractedContent(url=str(options.url), error=str(exc))

        soup = BeautifulSoup(html, "lxml")
        article = soup.find("article") or soup.find("main") or soup.body
        paragraphs = [
            element.get_text(" ", strip=True)
            for element in article.find_all("p")  # type: ignore[union-attr]
        ] if article else []
        quotes = [element.get_text(" ", strip=True) for element in soup.find_all("blockquote")]
        title = soup.title.string.strip() if soup.title and soup.title.string else None

        content = ExtractedContent(
            url=target_url,
            title=title,
            paragraphs=paragraphs,
            quotes=quotes,
            metadata=ExtractionMetadata(
                fetched_at=datetime.utcnow(),
                extractor="light",
                duration_seconds=time.perf_counter() - start,
                raw_url=str(options.url),
            ),
        )

        content = enrich_metadata(content, html=html, extractor_name="light")
        content = deduplicate_paragraphs(content)
        content = clean_content(content)
        content.trim(max_paragraphs=options.max_paragraphs)

        if content.is_valid(min_paragraphs=1):
            return content

        self._logger.debug("Light extractor found insufficient content for %s", options.url)
        if options.force_playwright:
            content.error = content.error or "Insufficient content extracted by light strategy"
            return content

        from .playwright_extractor import PlaywrightExtractor  # Local import to avoid circular dependency

        return PlaywrightExtractor(logger=self._logger).extract(
            url=str(options.url),
            options=options.model_dump(),
        )
