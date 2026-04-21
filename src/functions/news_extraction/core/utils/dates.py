"""Shared date parsing helpers for news extractors.

All parsed datetimes are normalised to timezone-aware UTC so that downstream
comparisons (watermarks, cutoff filters) behave consistently regardless of
feed-provided timezones.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from dateutil import parser as date_parser


def ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Return *value* as tz-aware UTC. Naive inputs are treated as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_feed_date(value: Any) -> Optional[datetime]:
    """Parse a date-like value into tz-aware UTC, or return None on failure.

    Accepts ISO strings, RFC 822 strings, ``datetime`` instances, and
    ``time.struct_time`` / 9-tuple instances produced by ``feedparser``.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return ensure_utc(value)

    # feedparser exposes parsed dates as struct_time / 9-tuples.
    if isinstance(value, (tuple, list)) and len(value) >= 6:
        try:
            return datetime(*value[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    if hasattr(value, "tm_year"):
        try:
            return datetime(*tuple(value)[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    if isinstance(value, str):
        try:
            return ensure_utc(date_parser.parse(value))
        except (ValueError, TypeError, OverflowError):
            return None

    return None
