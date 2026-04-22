"""Playwright-backed extractor implementation."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from bs4 import BeautifulSoup

try:  # pragma: no cover - optional dependency
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - fallback for environments without Playwright
    PlaywrightError = PlaywrightTimeoutError = Exception  # type: ignore[misc]
    async_playwright = None

from src.shared.contracts.extracted_content import ExtractedContent, ExtractionMetadata, ExtractionOptions, parse_options
from src.shared.processors.content_cleaner import clean_content
from src.shared.processors.metadata_extractor import enrich_metadata
from src.shared.processors.text_deduplicator import deduplicate_paragraphs
from src.shared.utils import amp_detector, consent_handler


class PlaywrightExtractor:
    """Executes JavaScript-capable extraction using Playwright."""

    _STEALTH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-web-security",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    _USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    _CONTENT_SELECTORS: tuple[str, ...] = (
        "article",
        "main article",
        "main",
        "section[data-testid='StoryBody']",
        "section[data-testid='story-body']",
        "section[data-testid='ArticleBody']",
        "section[name='article-body']",
        "div[data-testid='story-container']",
        "div[data-testid='story-main']",
        "div[data-testid='article-body']",
        "div[data-testid='StoryBody']",
        "div[class*='article-body']",
        "div[class*='StoryBody']",
        "div[class*='ArticleBody']",
        ".contentItem__padding",  # ESPN
        ".contentItem",  # ESPN fallback
        # NBC Sports selectors
        "div.article-content",
        "div.article__content",
        "div.post-content",
        "div.entry-content",
        ".article-body",
        ".post-body",
        "[data-module='article-body']",
    )

    _PARAGRAPH_SELECTORS: tuple[str, ...] = (
        "p",
        "li",
        "div[data-testid='Paragraph']",
        "div[data-testid='paragraph']",
        "p[data-testid='Paragraph']",
        "p[data-testid='paragraph']",
        "div[class*='paragraph']",
        "span[data-testid='Paragraph']",
        "span[class*='paragraph']",
        "div.contentItem__padding p",  # ESPN specific
        "div.contentItem p",  # ESPN specific
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
        return self._run_sync(validated)

    def _run_sync(self, options: ExtractionOptions) -> ExtractedContent:
        """Run a single-URL async extraction synchronously."""
        return self._run_async(self._extract(options), options.timeout_seconds + 10)

    def _run_async(self, coro, timeout_seconds: float):
        """Execute an async coroutine synchronously, even if a loop is running.

        When no loop is running (typical CLI / Cloud Function path) we use
        ``asyncio.run`` directly. When a loop is already running (e.g. test
        harness) we spin a fresh loop on a worker thread so the extraction
        doesn't try to reuse the caller's loop.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=timeout_seconds)

    # ------------------------------------------------------------------
    # Batch API — reuses browser + context across URLs (biggest perf win)
    # ------------------------------------------------------------------

    def extract_many(
        self,
        urls: Sequence[str],
        *,
        timeout: Optional[float] = None,
        options: dict | ExtractionOptions | None = None,
    ) -> List[ExtractedContent]:
        """Extract multiple URLs with a single browser + context instance.

        Launching Chromium costs ~2-3s per URL; reusing the browser across a
        batch amortizes that cost to once per batch. Yields results in the
        same order as ``urls``. Failures on individual URLs are returned as
        ``ExtractedContent(error=...)`` rather than raised.
        """
        url_list = [str(u) for u in urls]
        if not url_list:
            return []

        # Validate per URL so one malformed entry doesn't abort the whole batch
        # and force a fallback to per-URL extraction (losing browser-reuse).
        entries: List[Tuple[str, Optional[ExtractionOptions], Optional[str]]] = []
        for url in url_list:
            merged_options: dict[str, object] = {"url": url}
            if timeout:
                merged_options["timeout_seconds"] = int(timeout)
            if options:
                merged_options.update(
                    options if isinstance(options, dict) else options.model_dump()
                )
            try:
                entries.append((url, parse_options(merged_options), None))
            except Exception as exc:
                entries.append((url, None, f"Invalid extraction options: {exc}"))

        valid_options = [opt for _, opt, err in entries if opt is not None and err is None]
        if not valid_options:
            return [
                ExtractedContent(url=url, error=err or "Invalid URL")
                for url, _, err in entries
            ]

        total_timeout = sum(opt.timeout_seconds for opt in valid_options) + 30
        return self._run_async(self._extract_batch(entries), total_timeout)

    async def _extract_batch(
        self,
        entries: List[Tuple[str, Optional[ExtractionOptions], Optional[str]]],
    ) -> List[ExtractedContent]:
        if async_playwright is None:  # pragma: no cover - optional dep missing
            return [
                ExtractedContent(
                    url=url,
                    error=err or "Playwright is not available in the current environment",
                )
                for url, _, err in entries
            ]

        results: List[ExtractedContent] = []
        async with async_playwright() as playwright:
            browser = await self._launch_browser(playwright)
            try:
                context = await self._new_context(browser)
                try:
                    for url, opts, err in entries:
                        if opts is None or err is not None:
                            results.append(
                                ExtractedContent(url=url, error=err or "Invalid URL")
                            )
                            continue
                        context.set_default_navigation_timeout(
                            opts.timeout_seconds * 1000
                        )
                        results.append(await self._extract_one(context, opts))
                finally:
                    await context.close()
            finally:
                await browser.close()
        return results

    # ------------------------------------------------------------------
    # Single-URL extraction (unchanged API, now routed through shared helpers)
    # ------------------------------------------------------------------

    async def _extract(self, options: ExtractionOptions) -> ExtractedContent:
        """Single-URL extraction (browser lifecycle scoped to one URL)."""
        if async_playwright is None:
            return ExtractedContent(
                url=str(options.url),
                error="Playwright is not available in the current environment",
            )

        async with async_playwright() as playwright:
            browser = await self._launch_browser(playwright)
            try:
                context = await self._new_context(browser)
                context.set_default_navigation_timeout(options.timeout_seconds * 1000)
                try:
                    return await self._extract_one(context, options)
                finally:
                    await context.close()
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _launch_browser(self, playwright):
        return await playwright.chromium.launch(
            headless=True,
            args=self._STEALTH_ARGS,
            channel=None,  # Use bundled Chromium
        )

    async def _new_context(self, browser):
        context = await browser.new_context(
            user_agent=self._USER_AGENT,
            locale="en-US",
            timezone_id="America/New_York",
            ignore_https_errors=True,
            viewport={"width": 1920, "height": 1080},
            screen={"width": 1920, "height": 1080},
            device_scale_factor=1,
            has_touch=False,
            is_mobile=False,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            },
        )
        await context.add_init_script(self._ANTI_DETECTION_SCRIPT)
        return context

    async def _extract_one(
        self, context, options: ExtractionOptions
    ) -> ExtractedContent:
        """Open a page, extract one URL, close the page. Never raises."""
        start = time.perf_counter()
        self._logger.debug("Starting Playwright extraction for %s", options.url)
        page = None
        html = ""
        try:
            page = await context.new_page()
            await self._navigate(page, str(options.url), options)

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            await consent_handler.solve_consent(page, logger=self._logger)
            await page.wait_for_timeout(500)

            # Gated scroll: only hosts that lazy-render articles pay the
            # ~1-2s scroll cost.
            from .extractor_factory import is_heavy_url

            if is_heavy_url(str(options.url)):
                try:
                    for _ in range(3):
                        await page.mouse.wheel(0, 800)
                        await page.wait_for_timeout(250)
                except PlaywrightError:
                    pass

            url_lower = str(options.url).lower()
            if "espn.com" in url_lower or "nbcsports" in url_lower:
                self._logger.debug("JS-heavy host detected — waiting 3s")
                await page.wait_for_timeout(3000)

            html = await page.content()

            # Follow AMP alternate if present (and we're not already on AMP).
            amp_target = amp_detector.find_amp_alternate(html, str(options.url))
            if amp_target and not amp_detector.is_amp_url(str(options.url)):
                self._logger.debug("Following AMP link for %s", options.url)
                await self._navigate(page, amp_target, options)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except PlaywrightTimeoutError:
                    pass
                try:
                    await page.mouse.wheel(0, 500)
                    await page.wait_for_timeout(300)
                except PlaywrightError:
                    pass
                await consent_handler.solve_consent(page, logger=self._logger)
                html = await page.content()

            # Primary: JS tree-walker (most robust on JS-heavy sites).
            tree_paragraphs = await self._extract_with_tree_walker(page)
            if tree_paragraphs and len(tree_paragraphs) >= 3:
                self._logger.debug(
                    "Tree walker found %d paragraphs", len(tree_paragraphs)
                )
                html = await page.content()
                content = self._parse_html(html, page.url)
                content.paragraphs = tree_paragraphs
            else:
                # Last-chance scroll nudge, then re-parse.
                self._logger.debug(
                    "Tree walker insufficient (%d paragraphs); final scroll",
                    len(tree_paragraphs) if tree_paragraphs else 0,
                )
                for _ in range(2):
                    await page.mouse.wheel(0, 1000)
                    await page.wait_for_timeout(300)
                html = await page.content()
                content = self._parse_html(html, page.url)
                if not content.paragraphs or len(content.paragraphs) < 2:
                    tree_paragraphs = await self._extract_with_tree_walker(page)
                    if tree_paragraphs:
                        content.paragraphs = tree_paragraphs
        except Exception as exc:  # pragma: no cover - defensive umbrella
            self._logger.exception(
                "Playwright extraction failed for %s", options.url
            )
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    self._logger.debug("Page close error", exc_info=True)
            return ExtractedContent(url=str(options.url), error=str(exc))

        try:
            await page.close()
        except Exception:
            self._logger.debug("Page close error", exc_info=True)

        elapsed = time.perf_counter() - start
        metadata = content.metadata or ExtractionMetadata(
            fetched_at=datetime.now(timezone.utc),
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

    # Anti-detection init script (shared across all contexts).
    _ANTI_DETECTION_SCRIPT = """
        // Remove webdriver property
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // Add chrome object
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };

        // Override permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // Add realistic properties
        Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
            ]
        });

        delete navigator.__proto__.webdriver;

        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
                saveData: false
            })
        });
    """

    async def _navigate(self, page: Any, url: str, options: ExtractionOptions) -> None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=options.timeout_seconds * 1000)
        except PlaywrightTimeoutError as exc:  # pragma: no cover - network variability
            self._logger.warning("Navigation timeout for %s", url)
            raise RuntimeError(f"Navigation timeout for {url}") from exc
        except PlaywrightError as exc:  # pragma: no cover - unexpected Playwright error
            raise RuntimeError(f"Playwright navigation failed: {exc}") from exc

    async def _extract_with_tree_walker(self, page: Any) -> list[str]:
        """Tree walker extraction (like the JS grab() function) - more robust for ESPN and NBC Sports."""
        
        script = """() => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            const scopes = [];
            const selList = [
                'article',
                '[role="main"] article',
                'main article',
                '[itemprop="articleBody"]',
                '[data-testid="Article"]',
                '.article-body',
                '.article-content',
                '.article__content',
                '.post-content',
                '.entry-content',
                '.post-body',
                '[data-module="article-body"]',
                'main', '[role="main"]'
            ];
            
            for (const sel of selList) {
                const el = document.querySelector(sel);
                if (el) scopes.push(el);
            }
            if (!scopes.length) scopes.push(document.body);
            
            const bad = new Set(['NAV', 'ASIDE', 'FOOTER', 'SCRIPT', 'STYLE', 'NOSCRIPT', 'FORM', 'HEADER', 'FIGURE', 'FIGCAPTION']);
            const blocks = [];
            const MIN = 50;
            const seen = new Set();
            
            const pushFrom = (root) => {
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
                while (walker.nextNode()) {
                    const el = walker.currentNode;
                    if (bad.has(el.tagName)) continue;
                    // Skip elements with bad classes
                    const className = el.className || '';
                    if (typeof className === 'string' && 
                        (className.includes('social') || className.includes('share') || 
                         className.includes('ad-') || className.includes('sidebar') ||
                         className.includes('related') || className.includes('newsletter'))) {
                        continue;
                    }
                    if (['P', 'LI', 'BLOCKQUOTE', 'DIV'].includes(el.tagName)) {
                        const t = norm(el.innerText);
                        // Only take text from leaf-like elements (few children)
                        const childCount = el.querySelectorAll('p, li, div').length;
                        if (t && t.length > 20 && childCount < 3 && !seen.has(t)) {
                            seen.add(t);
                            blocks.push(t);
                        }
                    }
                }
            };
            
            scopes.forEach(pushFrom);
            
            // Merge small blocks
            const merged = [];
            for (const t of blocks) {
                if (merged.length && (merged[merged.length - 1].length < MIN || t.length < MIN)) {
                    merged[merged.length - 1] += ' ' + t;
                } else {
                    merged.push(t);
                }
            }
            
            return merged;
        }"""
        
        try:
            result = await page.evaluate(script)
            if isinstance(result, list):
                return [str(entry) for entry in result if isinstance(entry, str) and len(entry.strip()) > 50]
            return []
        except PlaywrightError:
            return []

    def _parse_html(self, html: str, url: str) -> ExtractedContent:
        soup = BeautifulSoup(html, "lxml")
        article = self._locate_article_root(soup)
        paragraphs: list[str] = []
        if article:
            nodes = article.select(", ".join(self._PARAGRAPH_SELECTORS))
            if nodes:
                paragraphs = []
                for node in nodes:
                    if not node:
                        continue
                    text = node.get_text(" ", strip=True)
                    if text:
                        paragraphs.append(text)
            if not paragraphs:
                paragraphs = [
                    element.get_text(" ", strip=True)
                    for element in article.find_all(["p", "li"])  # type: ignore[union-attr]
                ]
        quotes = [element.get_text(" ", strip=True) for element in soup.find_all("blockquote")]
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        return ExtractedContent(
            url=url,
            title=title,
            paragraphs=paragraphs,
            quotes=quotes,
        )

    def _locate_article_root(self, soup: BeautifulSoup):
        for selector in self._CONTENT_SELECTORS:
            target = soup.select_one(selector)
            if target:
                return target
        return soup.find("article") or soup.find("main") or soup.body
