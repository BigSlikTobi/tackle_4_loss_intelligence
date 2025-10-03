"""HTTP utilities for news extraction."""

from .client import HttpClient, RateLimiter

__all__ = ["HttpClient", "RateLimiter"]
