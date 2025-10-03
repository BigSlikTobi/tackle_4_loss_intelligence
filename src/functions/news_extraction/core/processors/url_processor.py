"""
URL processor for validation, deduplication, and filtering.

Processes extracted NewsItems to ensure quality and remove duplicates.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Set
from urllib.parse import urlparse
import logging

from ..contracts import NewsItem

logger = logging.getLogger(__name__)


class UrlProcessor:
    """
    Process and filter NewsItem collections.

    Handles deduplication, validation, date filtering, and other
    quality checks on extracted news items.
    """

    def __init__(self):
        """Initialize URL processor."""
        self.seen_urls: Set[str] = set()

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

        processed = []

        for item in items:
            # Validate URL
            if not self._is_valid_url(item.url):
                logger.debug(f"Skipping invalid URL: {item.url}")
                continue

            # Deduplicate
            if deduplicate:
                if item.url in self.seen_urls:
                    logger.debug(f"Skipping duplicate URL: {item.url}")
                    continue
                self.seen_urls.add(item.url)

            # Filter by date
            if days_back and not self._is_within_date_range(item, days_back):
                logger.debug(f"Filtering out old article: {item.url}")
                continue

            # Filter NFL content
            if nfl_only is not None and not item.is_nfl_content:
                logger.debug(f"Filtering out non-NFL content: {item.url}")
                continue

            processed.append(item)

        logger.info(f"Processed {len(processed)} items ({len(items) - len(processed)} filtered)")
        return processed

    def _is_valid_url(self, url: str) -> bool:
        """
        Validate URL format and requirements.

        Args:
            url: URL to validate

        Returns:
            True if URL is valid
        """
        if not url:
            return False

        # Must start with http/https
        if not url.startswith(("http://", "https://")):
            return False

        # Parse URL
        try:
            parsed = urlparse(url)
            # Must have a valid domain
            if not parsed.netloc:
                return False
            return True

        except Exception:
            return False

    def _is_within_date_range(self, item: NewsItem, days_back: int) -> bool:
        """
        Check if item is within the specified date range.

        Args:
            item: NewsItem to check
            days_back: Maximum age in days

        Returns:
            True if item is within range (or has no date)
        """
        if not item.published_date:
            # No date available - include by default
            return True

        cutoff = datetime.utcnow() - timedelta(days=days_back)
        cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

        # Remove timezone info for comparison
        published = item.published_date.replace(tzinfo=None)

        return published >= cutoff

    def reset(self) -> None:
        """Reset seen URLs for a fresh processing session."""
        self.seen_urls.clear()
