"""
HTTP client with rate limiting, circuit breaker, and comprehensive error handling.

Provides a production-ready HTTP client configured with appropriate timeouts,
user agents, rate limiting, and resilience patterns for fetching RSS feeds and sitemaps.
"""

from __future__ import annotations

import time
import hashlib
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

logger = logging.getLogger(__name__)

# Caching constants
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes
MAX_CACHE_SIZE = 100


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    
    Prevents cascading failures by opening the circuit when failures exceed threshold.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED

    def call(self, func, *args, **kwargs):
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            RuntimeError: When circuit is open
        """
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
            else:
                raise RuntimeError("Circuit breaker is OPEN - service unavailable")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self.last_failure_time:
            return True
        return (datetime.now(timezone.utc) - self.last_failure_time).total_seconds() >= self.recovery_timeout

    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker OPENED after {self.failure_count} failures")


class RateLimiter:
    """
    Simple rate limiter based on sliding window.

    Tracks request timestamps and blocks if rate limit would be exceeded.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in the window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: deque[datetime] = deque()

    def acquire(self) -> None:
        """
        Wait if necessary to respect rate limit.

        Blocks until a request slot is available within the rate limit.
        """
        while True:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(seconds=self.window_seconds)

            # Remove old requests outside the window
            while self.requests and self.requests[0] < cutoff:
                self.requests.popleft()

            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return

            oldest = self.requests[0]
            sleep_time = (oldest - cutoff).total_seconds()
            if sleep_time <= 0:
                # Window already advanced past the oldest entry; loop re-sweeps.
                continue
            logger.debug(f"Rate limit reached, sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)


class SimpleCache:
    """
    Simple in-memory cache with TTL support.

    Thread-safe cache for HTTP responses to reduce redundant requests.
    """

    def __init__(self, max_size: int = MAX_CACHE_SIZE, default_ttl: int = DEFAULT_CACHE_TTL_SECONDS):
        """
        Initialize cache.

        Args:
            max_size: Maximum number of cached items
            default_ttl: Default time-to-live in seconds
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _generate_key(self, url: str, **kwargs) -> str:
        """Generate cache key from URL and parameters."""
        key_data = f"{url}:{str(sorted(kwargs.items()))}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Get cached response if available and not expired."""
        key = self._generate_key(url, **kwargs)
        now = datetime.now(timezone.utc)

        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            if now > entry["expires_at"]:
                self._remove_locked(key)
                self._misses += 1
                return None

            self._access_times[key] = now
            self._hits += 1
            logger.debug(f"Cache hit for {url}")
            return entry["response"]

    def put(self, url: str, response: requests.Response, ttl: Optional[int] = None, **kwargs):
        """Cache response with TTL."""
        key = self._generate_key(url, **kwargs)
        ttl = ttl or self.default_ttl
        now = datetime.now(timezone.utc)

        with self._lock:
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._evict_lru_locked()

            self._cache[key] = {
                "response": response,
                "expires_at": now + timedelta(seconds=ttl),
                "cached_at": now,
            }
            self._access_times[key] = now

        logger.debug(f"Cached response for {url} (TTL: {ttl}s)")

    def _remove_locked(self, key: str):
        """Remove entry from cache. Caller must hold self._lock."""
        self._cache.pop(key, None)
        self._access_times.pop(key, None)

    def _evict_lru_locked(self):
        """Evict least recently used entry. Caller must hold self._lock."""
        if not self._access_times:
            return

        lru_key = min(self._access_times.keys(), key=lambda k: self._access_times[k])
        self._remove_locked(lru_key)
        logger.debug(f"Evicted LRU cache entry: {lru_key}")

    def clear(self):
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
            }


class HttpClient:
    """
    Production-ready HTTP client with rate limiting, circuit breaker, retries, and proper headers.

    Configured for fetching news feeds with comprehensive error handling and resilience patterns.
    """

    def __init__(
        self,
        user_agent: str = "T4L-End2End/1.0",
        timeout: int = 30,
        max_requests_per_minute: int = 60,
        max_retries: int = 3,
        circuit_breaker_threshold: int = 5,
        enable_cache: bool = True,
        cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
    ):
        """
        Initialize HTTP client.

        Args:
            user_agent: User-Agent header value
            timeout: Request timeout in seconds
            max_requests_per_minute: Rate limit for requests
            max_retries: Number of retry attempts on failure
            circuit_breaker_threshold: Failures before opening circuit
            enable_cache: Whether to enable response caching
            cache_ttl: Cache time-to-live in seconds
        """
        self.user_agent = user_agent
        self.timeout = timeout
        self.rate_limiter = RateLimiter(max_requests=max_requests_per_minute, window_seconds=60)
        self.circuit_breaker = CircuitBreaker(failure_threshold=circuit_breaker_threshold)
        
        # Initialize cache if enabled
        self.cache = SimpleCache(default_ttl=cache_ttl) if enable_cache else None

        # Configure session with retries
        self.session = requests.Session()

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set default headers
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "application/xml, application/rss+xml, text/html, */*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def get(self, url: str, **kwargs) -> requests.Response:
        """
        Perform a GET request with rate limiting and circuit breaker protection.

        Args:
            url: URL to fetch
            **kwargs: Additional arguments passed to requests.get()

        Returns:
            Response object

        Raises:
            requests.RequestException: On HTTP errors
            RuntimeError: When circuit breaker is open
        """
        return self.circuit_breaker.call(self._do_get, url, **kwargs)

    def _do_get(self, url: str, **kwargs) -> requests.Response:
        """Internal GET method with rate limiting, caching, and error handling."""
        # Check cache first
        if self.cache:
            cached_response = self.cache.get(url, **kwargs)
            if cached_response:
                return cached_response

        self.rate_limiter.acquire()

        # Merge timeout with any provided kwargs
        kwargs.setdefault("timeout", self.timeout)

        logger.debug(f"Fetching {url}")

        try:
            response = self.session.get(url, **kwargs)
            response.raise_for_status()
            
            # Cache successful responses
            if self.cache and response.status_code == 200:
                # Only cache GET requests with 200 status
                self.cache.put(url, response, **kwargs)
            
            # Log response details for monitoring
            logger.debug(f"Successfully fetched {url} - Status: {response.status_code}, Size: {len(response.content)} bytes")
            
            return response

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "Unknown"
            logger.error(f"HTTP {status_code} error fetching {url}: {e}")
            raise

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error fetching {url}: {e}")
            raise

        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout ({self.timeout}s) fetching {url}: {e}")
            raise

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error fetching {url}: {e}")
            raise

    def clear_cache(self) -> None:
        """Clear all cached responses."""
        if self.cache:
            self.cache.clear()
            logger.debug("HTTP cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        if self.cache:
            return self.cache.stats()
        return {"cache_enabled": False}

    def close(self) -> None:
        """Close the HTTP session."""
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close session."""
        self.close()
