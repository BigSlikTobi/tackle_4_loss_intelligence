"""Rate limiting utilities for Gemini requests."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator


_LOCK = threading.Lock()
_LAST_TICK = 0.0
_REQUEST_INTERVAL = 60.0 / 60  # 60 requests per minute by default


@contextmanager
def rate_limiter(max_requests_per_minute: int = 60) -> Iterator[None]:
    """Simple token bucket rate limiter shared across threads."""

    global _LAST_TICK, _REQUEST_INTERVAL
    interval = 60.0 / max_requests_per_minute
    with _LOCK:
        now = time.monotonic()
        wait_for = interval - (now - _LAST_TICK)
        if wait_for > 0:
            time.sleep(wait_for)
        _LAST_TICK = time.monotonic()
        _REQUEST_INTERVAL = interval
    try:
        yield
    finally:
        pass
