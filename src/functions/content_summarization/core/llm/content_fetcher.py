"""
Web content fetcher with fallback strategies.

Provides multiple methods to fetch web content when URL context API fails.
"""

import logging
import time
from typing import Optional, Tuple
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class ContentFetcher:
    """
    Production-ready web content fetcher with fallback strategies.
    
    Features:
    - Connection pooling for efficiency
    - Automatic retry with exponential backoff
    - Multiple fallback strategies
    - Rate limiting awareness
    - Circuit breaker pattern
    
    Strategy:
    1. URL Context API (via Gemini) - Fastest, free
    2. Simple HTTP + BeautifulSoup - Works for simple sites
    3. Manual extraction with headers - Bypasses basic bot detection
    """
    
    # Common headers to mimic browser
    BROWSER_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    def __init__(
        self,
        timeout: int = 10,
        max_content_length: int = 500000,
        max_retries: int = 3,
        pool_connections: int = 10,
        pool_maxsize: int = 20,
    ):
        """
        Initialize production-ready content fetcher.
        
        Args:
            timeout: Request timeout in seconds
            max_content_length: Maximum content length to process (chars)
            max_retries: Maximum retry attempts for failed requests
            pool_connections: Number of connection pools to cache
            pool_maxsize: Maximum number of connections per pool
        """
        self.timeout = timeout
        self.max_content_length = max_content_length
        self.max_retries = max_retries
        
        # Create session with connection pooling and retry strategy
        self.session = self._create_session(pool_connections, pool_maxsize, max_retries)
        
        # Circuit breaker state
        self._failure_count = {}
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_timeout = 300  # 5 minutes
        
        logger.info(
            f"Initialized ContentFetcher with connection pooling "
            f"(pools={pool_connections}, max_size={pool_maxsize}, retries={max_retries})"
        )
    
    def _create_session(
        self, pool_connections: int, pool_maxsize: int, max_retries: int
    ) -> requests.Session:
        """
        Create a requests session with connection pooling and retry logic.
        
        Args:
            pool_connections: Number of connection pools
            pool_maxsize: Maximum connections per pool
            max_retries: Maximum retry attempts
            
        Returns:
            Configured requests Session
        """
        session = requests.Session()
        
        # Configure retry strategy with exponential backoff
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,  # 1s, 2s, 4s, 8s...
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        
        # Configure adapter with connection pooling
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy,
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _is_circuit_open(self, url: str) -> bool:
        """
        Check if circuit breaker is open for a URL's domain.
        
        Args:
            url: URL to check
            
        Returns:
            True if circuit is open (should skip), False otherwise
        """
        domain = urlparse(url).netloc
        
        if domain not in self._failure_count:
            return False
        
        failure_data = self._failure_count[domain]
        failure_count = failure_data.get("count", 0)
        last_failure_time = failure_data.get("last_failure", 0)
        
        # Circuit is open if threshold exceeded and timeout not elapsed
        if failure_count >= self._circuit_breaker_threshold:
            time_since_failure = time.time() - last_failure_time
            if time_since_failure < self._circuit_breaker_timeout:
                logger.warning(
                    f"Circuit breaker OPEN for {domain} "
                    f"({failure_count} failures, {int(self._circuit_breaker_timeout - time_since_failure)}s remaining)"
                )
                return True
            else:
                # Reset after timeout
                logger.info(f"Circuit breaker RESET for {domain}")
                self._failure_count[domain] = {"count": 0, "last_failure": 0}
                return False
        
        return False
    
    def _record_failure(self, url: str):
        """Record a failure for circuit breaker tracking."""
        domain = urlparse(url).netloc
        
        if domain not in self._failure_count:
            self._failure_count[domain] = {"count": 0, "last_failure": 0}
        
        self._failure_count[domain]["count"] += 1
        self._failure_count[domain]["last_failure"] = time.time()
    
    def _record_success(self, url: str):
        """Record a success to reset circuit breaker."""
        domain = urlparse(url).netloc
        
        if domain in self._failure_count:
            self._failure_count[domain] = {"count": 0, "last_failure": 0}
    
    def fetch_with_fallback(self, url: str) -> Tuple[Optional[str], str]:
        """
        Fetch content with fallback strategies and circuit breaker protection.
        
        Args:
            url: URL to fetch
            
        Returns:
            Tuple of (content, method_used)
            - content: Extracted text content or None if all methods fail
            - method_used: Description of which method worked
        """
        logger.info(f"Attempting to fetch content from: {url}")
        
        # Check circuit breaker
        if self._is_circuit_open(url):
            logger.warning(f"Circuit breaker OPEN for {url}, skipping fetch attempts")
            return None, "circuit_breaker_open"
        
        # Try simple HTTP request first
        content = self._try_simple_http(url)
        if content:
            self._record_success(url)
            return content, "simple_http"
        
        # Try with browser headers
        content = self._try_with_headers(url)
        if content:
            self._record_success(url)
            return content, "browser_headers"
        
        # Record failure for circuit breaker
        self._record_failure(url)
        
        logger.warning(f"All fallback methods failed for: {url}")
        return None, "all_failed"
    
    def _try_simple_http(self, url: str) -> Optional[str]:
        """Try simple HTTP GET request with session pooling."""
        try:
            logger.debug(f"Trying simple HTTP for: {url}")
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()
            
            # Check content size
            if len(response.text) > self.max_content_length:
                logger.warning(
                    f"Content too large for {url}: {len(response.text)} chars "
                    f"(max: {self.max_content_length})"
                )
                # Truncate instead of failing
                html = response.text[: self.max_content_length]
            else:
                html = response.text
            
            # Parse HTML
            content = self._extract_article_content(html, url)
            if content and len(content) > 100:  # Minimum meaningful content
                logger.info(f"Simple HTTP succeeded for: {url}")
                return content
                
        except requests.exceptions.Timeout:
            logger.debug(f"Timeout for {url} after {self.timeout}s")
        except requests.exceptions.TooManyRedirects:
            logger.debug(f"Too many redirects for {url}")
        except requests.exceptions.RequestException as e:
            logger.debug(f"Simple HTTP failed for {url}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error in simple HTTP for {url}: {e}")
        
        return None
    
    def _try_with_headers(self, url: str) -> Optional[str]:
        """Try with browser-like headers to bypass basic bot detection."""
        try:
            logger.debug(f"Trying with browser headers for: {url}")
            response = self.session.get(
                url,
                headers=self.BROWSER_HEADERS,
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()
            
            # Check content size
            if len(response.text) > self.max_content_length:
                logger.warning(
                    f"Content too large for {url}: {len(response.text)} chars "
                    f"(max: {self.max_content_length})"
                )
                html = response.text[: self.max_content_length]
            else:
                html = response.text
            
            # Parse HTML
            content = self._extract_article_content(html, url)
            if content and len(content) > 100:
                logger.info(f"Browser headers succeeded for: {url}")
                return content
                
        except requests.exceptions.Timeout:
            logger.debug(f"Timeout for {url} after {self.timeout}s")
        except requests.exceptions.TooManyRedirects:
            logger.debug(f"Too many redirects for {url}")
        except requests.exceptions.RequestException as e:
            logger.debug(f"Browser headers failed for {url}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error in browser headers for {url}: {e}")
        
        return None
    
    def _extract_article_content(self, html: str, url: str) -> Optional[str]:
        """
        Extract main article content from HTML with improved error handling.
        
        Focuses on common article container tags to avoid nav/footer noise.
        
        Args:
            html: HTML content
            url: Source URL for logging
            
        Returns:
            Extracted text content or None if extraction fails
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
                script.decompose()
            
            # Try common article containers in priority order
            content = None
            
            # Strategy 1: Look for article tag
            article = soup.find('article')
            if article:
                content = article.get_text(separator='\n', strip=True)
                if len(content) > 100:
                    logger.debug(f"Extracted content from <article> tag for {url}")
                    return self._clean_content(content)
            
            # Strategy 2: Look for main content divs with common class names
            selectors = [
                'main',
                'div.article-body',
                'div.story-body',
                'div.entry-content',
                'div.post-content',
                'div.content-body',
                'div[class*="article"]',
                'div[class*="content"]',
            ]
            
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    for element in elements:
                        content = element.get_text(separator='\n', strip=True)
                        if len(content) > 100:
                            logger.debug(f"Extracted content from {selector} for {url}")
                            return self._clean_content(content)
            
            # Strategy 3: Find largest text block as fallback
            all_divs = soup.find_all('div')
            if all_divs:
                largest = max(all_divs, key=lambda d: len(d.get_text()), default=None)
                if largest:
                    content = largest.get_text(separator='\n', strip=True)
                    if len(content) > 100:
                        logger.debug(f"Extracted content from largest div for {url}")
                        return self._clean_content(content)
            
            # Strategy 4: Get all text as last resort
            content = soup.get_text(separator='\n', strip=True)
            if len(content) > 100:
                logger.debug(f"Extracted all text content for {url}")
                return self._clean_content(content)
            
            logger.warning(f"Could not extract meaningful content from {url}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting content from {url}: {e}")
            return None
    
    def _clean_content(self, content: str) -> str:
        """
        Clean extracted content by removing excessive whitespace.
        
        Args:
            content: Raw extracted text
            
        Returns:
            Cleaned text
        """
        # Remove excessive whitespace
        lines = [line.strip() for line in content.split('\n')]
        lines = [line for line in lines if line]  # Remove empty lines
        
        # Rejoin with single newlines
        cleaned = '\n'.join(lines)
        
        # Limit length
        if len(cleaned) > self.max_content_length:
            cleaned = cleaned[: self.max_content_length]
            logger.debug(f"Truncated content to {self.max_content_length} chars")
        
        return cleaned
    
    def is_likely_blocked(self, url: str) -> bool:
        """
        Check if URL is likely to be blocked by URL context API.
        
        Based on domain patterns observed to fail frequently.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL is likely blocked, False otherwise
        """
        domain = urlparse(url).netloc.lower()
        
        # Known problematic domains for URL context API
        blocked_patterns = [
            'espn.com',
            'nfl.com',
            # Add more as discovered through monitoring
        ]
        
        return any(pattern in domain for pattern in blocked_patterns)
    
    def close(self):
        """Close the session and clean up resources."""
        if hasattr(self, 'session'):
            self.session.close()
            logger.debug("Closed ContentFetcher session")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
