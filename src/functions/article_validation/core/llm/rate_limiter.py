"""Async rate limiting utilities for outbound API requests."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from src.shared.utils.logging import get_logger

LOGGER = get_logger(__name__)


class RateLimitExceeded(RuntimeError):
    """Raised when the rate limiter cannot satisfy a request in time."""


@dataclass
class RateLimiter:
    """Simple token bucket rate limiter with exponential backoff."""

    max_requests_per_minute: int = 60
    max_backoff_seconds: float = 10.0
    min_sleep_seconds: float = 0.05
    _capacity: float = field(init=False, repr=False)
    _tokens: float = field(init=False, repr=False)
    _refill_rate: float = field(init=False, repr=False)
    _lock: asyncio.Lock = field(init=False, repr=False)
    _last_refill: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_requests_per_minute <= 0:
            raise ValueError("max_requests_per_minute must be positive")
        if self.min_sleep_seconds <= 0:
            raise ValueError("min_sleep_seconds must be positive")
        if self.max_backoff_seconds < self.min_sleep_seconds:
            raise ValueError("max_backoff_seconds must be >= min_sleep_seconds")

        self._capacity = float(self.max_requests_per_minute)
        self._tokens = float(self.max_requests_per_minute)
        self._refill_rate = self._capacity / 60.0
        self._lock = asyncio.Lock()
        self._last_refill = time.monotonic()

    async def acquire(self, timeout: Optional[float] = None) -> None:
        """Acquire a single token, waiting with backoff as needed.

        Args:
            timeout: Max seconds to wait for a token. None means wait indefinitely.

        Raises:
            RateLimitExceeded: If timeout elapses before a token becomes available.
        """

        attempt = 0
        start = time.monotonic()
        deadline = start + timeout if timeout is not None else None

        while True:
            wait_time = None
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_time = (1.0 - self._tokens) / self._refill_rate

            backoff = max(self.min_sleep_seconds, wait_time)
            if attempt:
                backoff = min(backoff * (2 ** attempt), self.max_backoff_seconds)
            else:
                backoff = min(backoff, self.max_backoff_seconds)

            now = time.monotonic()
            if deadline is not None and now + backoff > deadline:
                raise RateLimitExceeded(
                    "Timed out while waiting for rate limiter token"
                )

            LOGGER.debug(
                "Rate limiter backing off for %.2fs (attempt %d)",
                backoff,
                attempt + 1,
            )
            attempt += 1
            await asyncio.sleep(backoff)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(
            self._capacity,
            self._tokens + (elapsed * self._refill_rate),
        )
        self._last_refill = now

    def release(self) -> None:
        """Return a token to the bucket (used when calls fail early)."""

        if self._tokens >= self._capacity:
            return
        self._tokens += 1.0
        self._tokens = min(self._tokens, self._capacity)

    def snapshot(self) -> dict[str, float]:
        """Return diagnostic information about the limiter state."""

        return {
            "tokens": self._tokens,
            "capacity": self._capacity,
            "refill_rate_per_sec": self._refill_rate,
        }
