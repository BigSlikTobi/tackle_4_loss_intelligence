"""Thread-safe browser instance pooling for web content extraction."""

from __future__ import annotations

import logging
import threading
from queue import Empty, Queue
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BrowserPool:
    """Thread-safe pool of browser instances for concurrent web scraping.
    
    Manages a pool of browser instances that can be acquired and released
    by multiple threads. Supports lazy initialization and graceful shutdown.
    
    Example:
        pool = BrowserPool(max_browsers=4)
        
        def process_url(url):
            browser = pool.acquire()
            try:
                # Use browser to fetch content
                content = fetch_with_browser(browser, url)
                return content
            finally:
                pool.release(browser)
        
        # When done
        pool.shutdown()
    """

    def __init__(self, max_browsers: int = 4):
        """Initialize browser pool.

        Args:
            max_browsers: Maximum number of browser instances
        """
        self.max_browsers = max_browsers
        self.browsers: Queue = Queue(maxsize=max_browsers)
        self.initialized = 0
        self.lock = threading.Lock()
        self.closed = False

    def acquire(self, timeout: Optional[float] = None) -> Any:
        """Acquire a browser instance from the pool.
        
        If no browser is available and we haven't reached max_browsers,
        returns a token indicating a new browser should be created.
        Otherwise blocks until a browser is available.

        Args:
            timeout: Optional timeout in seconds for blocking

        Returns:
            Browser instance or "BROWSER_TOKEN" for new creation
            
        Raises:
            RuntimeError: If pool is closed
        """
        if self.closed:
            raise RuntimeError("Browser pool is closed")

        try:
            browser = self.browsers.get(block=False)
            logger.debug("Reused existing browser from pool")
            return browser
        except Empty:
            pass

        with self.lock:
            if self.initialized < self.max_browsers:
                self.initialized += 1
                logger.info(
                    "Creating new browser instance (%s/%s)",
                    self.initialized,
                    self.max_browsers,
                )
                return "BROWSER_TOKEN"

        logger.debug("Waiting for available browser from pool")
        return self.browsers.get(block=True, timeout=timeout)

    def release(self, browser: Any) -> None:
        """Return a browser instance to the pool.

        Args:
            browser: Browser instance to release
        """
        if self.closed or browser is None:
            return
        try:
            self.browsers.put(browser, block=False)
            logger.debug("Released browser back to pool")
        except Exception as exc:
            logger.warning("Failed to release browser to pool: %s", exc)

    def close_idle_browsers(self, keep: int = 1) -> int:
        """Close idle browsers, keeping a minimum number.

        Args:
            keep: Minimum number of browsers to keep

        Returns:
            Number of browsers closed
        """
        with self.lock:
            closed_count = 0
            browsers_to_keep = []

            while not self.browsers.empty():
                try:
                    browser = self.browsers.get(block=False)
                    if len(browsers_to_keep) < keep:
                        browsers_to_keep.append(browser)
                    else:
                        try:
                            if hasattr(browser, "close"):
                                browser.close()
                            closed_count += 1
                        except Exception as exc:
                            logger.warning("Error closing browser: %s", exc)
                except Empty:
                    break

            for browser in browsers_to_keep:
                try:
                    self.browsers.put(browser, block=False)
                except Exception:
                    pass

            self.initialized = len(browsers_to_keep)
            if closed_count:
                logger.info("Closed %s idle browsers (keeping %s)", closed_count, keep)

            return closed_count

    def shutdown(self) -> None:
        """Shutdown the pool and close all browsers."""
        with self.lock:
            self.closed = True
            closed_count = 0

            while not self.browsers.empty():
                try:
                    browser = self.browsers.get(block=False)
                    if hasattr(browser, "close"):
                        try:
                            browser.close()
                        except Exception as exc:
                            logger.warning("Error closing browser: %s", exc)
                    closed_count += 1
                except Empty:
                    break
                except Exception as exc:
                    logger.warning("Error during browser shutdown: %s", exc)

            logger.info("Browser pool shutdown complete (closed %d)", closed_count)

    def get_stats(self) -> Dict[str, int]:
        """Get pool statistics.

        Returns:
            Dict with pool metrics
        """
        return {
            "max_browsers": self.max_browsers,
            "initialized": self.initialized,
            "available": self.browsers.qsize(),
            "in_use": self.initialized - self.browsers.qsize(),
        }
