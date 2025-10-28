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
        ".contentItem__padding",  # ESPN
        ".contentItem",  # ESPN fallback
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
                timezone_id="America/New_York",  # ESPN is US-centric
                ignore_https_errors=True,
                viewport={"width": 1280, "height": 1600},
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            
            # Anti-detection script (like your JS init script)
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = window.chrome || { runtime: {} };
                const originalQuery = navigator.permissions && navigator.permissions.query;
                if (originalQuery) {
                    navigator.permissions.query = (parameters) => (
                        parameters && parameters.name === 'notifications'
                            ? Promise.resolve({ state: 'denied', onchange: null })
                            : originalQuery(parameters)
                    );
                }
                Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            """)
            
            context.set_default_navigation_timeout(options.timeout_seconds * 1000)
            try:
                yield context
            finally:
                await context.close()
                await browser.close()

    async def _extract(self, options: ExtractionOptions) -> ExtractedContent:
        start = time.perf_counter()
        self._logger.debug("Starting Playwright extraction for %s", options.url)
        page = None
        context = None
        browser = None
        
        try:
            if async_playwright is None:
                msg = "Playwright is not available in the current environment"
                raise RuntimeError(msg)
            
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True, args=self._STEALTH_ARGS)
                context = await browser.new_context(
                    user_agent=self._USER_AGENT,
                    locale="en-US",
                    timezone_id="America/New_York",
                    ignore_https_errors=True,
                    viewport={"width": 1280, "height": 1600},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Upgrade-Insecure-Requests": "1",
                    },
                )
                
                # Anti-detection script
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = window.chrome || { runtime: {} };
                    const originalQuery = navigator.permissions && navigator.permissions.query;
                    if (originalQuery) {
                        navigator.permissions.query = (parameters) => (
                            parameters && parameters.name === 'notifications'
                                ? Promise.resolve({ state: 'denied', onchange: null })
                                : originalQuery(parameters)
                        );
                    }
                    Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                """)
                
                context.set_default_navigation_timeout(options.timeout_seconds * 1000)
                page = await context.new_page()
                
                await self._navigate(page, str(options.url), options)
                
                # Wait for DOM and do scrolling to trigger lazy content
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except PlaywrightTimeoutError:
                    pass
                
                # Scroll to trigger lazy-loaded content (critical for ESPN)
                try:
                    for _ in range(3):
                        await page.mouse.wheel(0, 800)
                        await page.wait_for_timeout(250)
                except PlaywrightError:
                    pass
                
                # Give ESPN's JavaScript time to populate content
                is_espn = "espn.com" in str(options.url).lower()
                if is_espn:
                    self._logger.debug("Detected ESPN - waiting for JS content")
                    await page.wait_for_timeout(2000)
                
                html = await page.content()
                
                # Handle consent dialogs
                await consent_handler.solve_consent(page, logger=self._logger)
                
                # Check for AMP
                amp_target = amp_detector.find_amp_alternate(html, str(options.url))
                if amp_target and not amp_detector.is_amp_url(str(options.url)):
                    self._logger.debug("Following AMP link for %s", options.url)
                    await self._navigate(page, amp_target, options)
                    await page.wait_for_timeout(1000)
                    html = await page.content()
                
                # Try tree walker extraction (most robust for ESPN)
                tree_paragraphs = await self._extract_with_tree_walker(page)
                if tree_paragraphs and len(tree_paragraphs) >= 3:
                    self._logger.debug("Tree walker found %d paragraphs", len(tree_paragraphs))
                    html = await page.content()
                    content = self._parse_html(html, page.url)
                    content.paragraphs = tree_paragraphs
                else:
                    # If content still insufficient, do one more scroll nudge
                    self._logger.debug("Tree walker found insufficient content (%d paragraphs), trying final scroll", len(tree_paragraphs) if tree_paragraphs else 0)
                    for _ in range(2):
                        await page.mouse.wheel(0, 1000)
                        await page.wait_for_timeout(300)
                    
                    html = await page.content()
                    content = self._parse_html(html, page.url)
                    
                    # Final fallback to tree walker
                    if not content.paragraphs or len(content.paragraphs) < 2:
                        tree_paragraphs = await self._extract_with_tree_walker(page)
                        if tree_paragraphs:
                            content.paragraphs = tree_paragraphs
                
                # Clean up before exiting context
                await page.close()
                await context.close()
                await browser.close()
                
        except Exception as exc:  # pragma: no cover - defensive umbrella
            self._logger.exception("Playwright extraction failed for %s", options.url)
            # Clean up on error
            try:
                if page:
                    await page.close()
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except:
                pass
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

    async def _await_content(self, page: Any, options: ExtractionOptions, *, phase: str) -> None:
        """Wait for the main article markup to be present before parsing."""

        timeout_ms = max(3000, min(15000, int(options.timeout_seconds * 1000 * 0.3)))
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            self._logger.debug("DOM content load timed out for %s during %s", page.url, phase)
        
        # Perform small scrolls to trigger lazy-loaded content (ESPN technique)
        try:
            for _ in range(3):
                await page.mouse.wheel(0, 800)
                await page.wait_for_timeout(250)
        except PlaywrightError:
            pass
        
        # For JavaScript-heavy sites like ESPN, use shorter network idle timeout
        is_espn = "espn.com" in str(page.url).lower()
        if is_espn:
            self._logger.debug("Detected ESPN - using enhanced extraction")
            network_timeout = min(5000, timeout_ms)
        else:
            network_timeout = timeout_ms
        
        try:
            await page.wait_for_load_state("networkidle", timeout=network_timeout)
        except PlaywrightTimeoutError:
            self._logger.debug("Network idle wait timed out for %s during %s", page.url, phase)

        min_threshold = max(60, options.min_paragraph_chars // 4)
        for selector in self._CONTENT_SELECTORS:
            handle = None
            try:
                handle = await page.wait_for_selector(selector, timeout=3000)
            except PlaywrightTimeoutError:
                continue
            except PlaywrightError:
                continue
            if not handle:
                continue
            try:
                await handle.scroll_into_view_if_needed()
            except PlaywrightError:
                pass
            try:
                snippet = await handle.inner_text()
            except PlaywrightError:
                snippet = ""
            if snippet and len(snippet.strip()) >= min_threshold:
                await handle.dispose()
                return
            paragraph_handle = None
            try:
                paragraph_handle = await handle.query_selector("p")
                if paragraph_handle:
                    text = await paragraph_handle.inner_text()
                    if text and len(text.strip()) >= min_threshold:
                        await paragraph_handle.dispose()
                        paragraph_handle = None
                        await handle.dispose()
                        return
            except PlaywrightError:
                pass
            finally:
                if paragraph_handle:
                    try:
                        await paragraph_handle.dispose()
                    except PlaywrightError:
                        pass
            await handle.dispose()

        paragraphs = await self._probe_paragraphs(page, min_threshold)
        if paragraphs:
            return

        self._logger.debug("No article selectors matched for %s after %s", page.url, phase)

    async def _probe_paragraphs(self, page: Any, min_threshold: int) -> list[str]:
        """Inspect the DOM for paragraph nodes using JavaScript for dynamic layouts."""

        selectors = list(self._PARAGRAPH_SELECTORS)
        script = (
            "(args) => {"
            "const selectors = args.selectors;"
            "const minLength = args.minLength;"
            "const seen = new Set();"
            "const all = [];"
            "for (const selector of selectors) {"
            "  const nodes = document.querySelectorAll(selector);"
            "  for (const node of nodes) {"
            "    if (!node || typeof node.innerText !== 'string') continue;"
            "    const text = node.innerText.trim();"
            "    if (!text || text.length < minLength) continue;"
            "    if (seen.has(text)) continue;"
            "    seen.add(text);"
            "    all.push(text);"
            "    if (all.length >= 3) return all;"
            "  }"
            "}"
            "return all;"
            "}"
        )
        try:
            result = await page.evaluate(script, {"selectors": selectors, "minLength": min_threshold})
        except PlaywrightError:
            return []
        if not isinstance(result, list):
            return []
        return [str(entry) for entry in result if isinstance(entry, str)]

    async def _extract_with_tree_walker(self, page: Any) -> list[str]:
        """Tree walker extraction (like the JS grab() function) - more robust for ESPN."""
        
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
                'main', '[role="main"]'
            ];
            
            for (const sel of selList) {
                const el = document.querySelector(sel);
                if (el) scopes.push(el);
            }
            if (!scopes.length) scopes.push(document.body);
            
            const bad = new Set(['NAV', 'ASIDE', 'FOOTER', 'SCRIPT', 'STYLE', 'NOSCRIPT', 'FORM', 'HEADER']);
            const blocks = [];
            const MIN = 50;
            
            const pushFrom = (root) => {
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
                while (walker.nextNode()) {
                    const el = walker.currentNode;
                    if (bad.has(el.tagName)) continue;
                    if (['P', 'LI', 'BLOCKQUOTE', 'DIV'].includes(el.tagName)) {
                        const t = norm(el.innerText);
                        // Only take text from leaf-like elements (few children)
                        const childCount = el.querySelectorAll('p, li, div').length;
                        if (t && t.length > 20 && childCount < 3) {
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
