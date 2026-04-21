"""
URL processor for validation, deduplication, and filtering.

Processes extracted NewsItems to ensure quality and remove duplicates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Set
from urllib.parse import urlparse
import logging

from ..contracts import NewsItem
from ..utils.dates import ensure_utc

logger = logging.getLogger(__name__)


class UrlProcessor:
    """
    Process and filter NewsItem collections.

    Handles deduplication, validation, date filtering, and other
    quality checks on extracted news items.
    """

    def process(
        self,
        items: List[NewsItem],
        deduplicate: bool = True,
        days_back: int = None,
        nfl_only: bool = None,
    ) -> List[NewsItem]:
        """
        Process a list of news items.

        Args:
            items: Raw NewsItem list from extractors
            deduplicate: Remove duplicate URLs
            days_back: Filter to items within this many days (overrides item-level filter)
            nfl_only: Filter to NFL content only (overrides item-level setting)

        Returns:
            Processed and filtered NewsItem list
        """
        logger.info(f"Processing {len(items)} news items")

        # seen_urls is local so repeated calls (e.g. Cloud Function warm
        # invocations) don't drop valid new URLs as "duplicates".
        seen_urls: Set[str] = set()
        processed = []

        for item in items:
            if not self._is_valid_url(item.url):
                logger.debug(f"Skipping invalid URL: {item.url}")
                continue

            if deduplicate:
                if item.url in seen_urls:
                    logger.debug(f"Skipping duplicate URL: {item.url}")
                    continue
                seen_urls.add(item.url)

            if days_back and not self._is_within_date_range(item, days_back):
                logger.debug(f"Filtering out old article: {item.url}")
                continue

            # Only filter when nfl_only is explicitly True. `False` means "don't
            # enforce an NFL check" (not "exclude NFL items"), matching the
            # documented "Filter to NFL content only" semantics.
            if nfl_only is True and not item.is_nfl_content:
                logger.debug(f"Filtering out non-NFL content: {item.url}")
                continue

            processed.append(item)

        logger.info(f"Processed {len(processed)} items ({len(items) - len(processed)} filtered)")
        return processed

    def _is_valid_url(self, url: str) -> bool:
        """Validate URL format and requirements."""
        if not url:
            return False

        if not url.startswith(("http://", "https://")):
            return False

        try:
            parsed = urlparse(url)
            return bool(parsed.netloc)
        except Exception:
            return False

    def _is_within_date_range(self, item: NewsItem, days_back: int) -> bool:
        """Check if item is within the specified date range."""
        if not item.published_date:
            return True

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

        published = ensure_utc(item.published_date)
        return published >= cutoff
