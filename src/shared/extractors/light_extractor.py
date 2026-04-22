"""HTTP-only extractor implementation using httpx and BeautifulSoup.

Uses a module-level ``httpx.Client`` so connection pooling, DNS caching,
and TLS session resumption amortize across all ``LightExtractor`` calls in
the same process. ``httpx.Client`` is thread-safe, so a single shared
instance works fine for the ThreadPoolExecutor callers.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.shared.contracts.extracted_content import ExtractedContent, ExtractionMetadata, ExtractionOptions, parse_options
from src.shared.processors.content_cleaner import clean_content
from src.shared.processors.metadata_extractor import enrich_metadata
from src.shared.processors.text_deduplicator import deduplicate_paragraphs
from src.shared.utils import amp_detector


_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Module-level shared client. Lazy-initialized, protected by a lock for
# correctness under concurrent first-access. Lifetime is process-scope.
_shared_client: Optional[httpx.Client] = None
_shared_client_lock = threading.Lock()


def _get_shared_client() -> httpx.Client:
    global _shared_client
    client = _shared_client
    if client is not None:
        return client
    with _shared_client_lock:
        if _shared_client is None:
            _shared_client = httpx.Client(
                headers=_DEFAULT_HEADERS,
                follow_redirects=True,
                # Reasonable default; per-call timeout is applied on .get() below.
                timeout=30.0,
                http2=True,
                # Bound connection pool so a single pipeline run can't exhaust
                # local file descriptors under high concurrency.
                limits=httpx.Limits(
                    max_connections=50, max_keepalive_connections=20
                ),
            )
        return _shared_client


def close_shared_client() -> None:
    """Close the process-wide client (call at shutdown in long-running jobs)."""
    global _shared_client
    with _shared_client_lock:
        if _shared_client is not None:
            try:
                _shared_client.close()
            except Exception:
                pass
            _shared_client = None


class LightExtractor:
    """Performs fast HTTP extraction for simple pages."""

    _DEFAULT_HEADERS = _DEFAULT_HEADERS  # Kept for back-compat imports.

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
        return self._extract(validated)

    def _fetch(self, options: ExtractionOptions) -> tuple[str, str]:
        client = _get_shared_client()
        response = client.get(str(options.url), timeout=options.timeout_seconds)
        response.raise_for_status()
        html = response.text
        amp_alternate = amp_detector.find_amp_alternate(html, str(options.url))
        if amp_alternate:
            self._logger.debug("Discovered AMP alternate for %s", options.url)
            response = client.get(amp_alternate, timeout=options.timeout_seconds)
            response.raise_for_status()
            return amp_alternate, response.text
        return str(options.url), html

    def _extract(self, options: ExtractionOptions) -> ExtractedContent:
        start = time.perf_counter()
        self._logger.debug("Starting lightweight extraction for %s", options.url)
        try:
            target_url, html = self._fetch(options)
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
                fetched_at=datetime.now(timezone.utc),
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

        # Before paying the Playwright cost, try the richer selector set from
        # PlaywrightExtractor._parse_html against the HTML we already have.
        # Many sites have article content in markup we simply didn't target in
        # the first pass; re-parsing is nearly free.
        from .playwright_extractor import PlaywrightExtractor  # Local import to avoid circular dependency

        pw = PlaywrightExtractor(logger=self._logger)
        reparsed = pw._parse_html(html, target_url)  # noqa: SLF001 - intentional reuse
        if reparsed.paragraphs:
            reparsed.metadata = content.metadata
            reparsed = enrich_metadata(reparsed, html=html, extractor_name="light")
            reparsed = deduplicate_paragraphs(reparsed)
            reparsed = clean_content(reparsed)
            reparsed.trim(max_paragraphs=options.max_paragraphs)
            if reparsed.is_valid(min_paragraphs=1):
                return reparsed

        return pw.extract(
            url=str(options.url),
            options=options.model_dump(),
        )
