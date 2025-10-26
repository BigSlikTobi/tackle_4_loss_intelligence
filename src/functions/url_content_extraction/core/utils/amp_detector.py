"""Detect AMP pages or alternative markup variants."""

from urllib.parse import urlparse


def is_amp_url(url: str) -> bool:
    """Return True when the URL looks like an AMP page (implementation pending)."""
    parsed = urlparse(url)
    return parsed.path.endswith("/amp") or "/amp/" in parsed.path
