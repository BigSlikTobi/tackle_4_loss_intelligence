"""Placeholder for rate limiting utilities."""

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def rate_limiter() -> Iterator[None]:  # pragma: no cover - placeholder
    """Yield control while enforcing rate limits in future work."""
    yield
