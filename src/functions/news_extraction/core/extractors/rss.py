"""
RSS feed extractor.

Fetches and parses RSS feeds to extract article URLs and metadata.
Optimized for production use with comprehensive error handling.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import feedparser
from dateutil import parser as date_parser
import logging

from ..contracts import NewsItem
from ..config import SourceConfig
from .base import BaseExtractor

logger = logging.getLogger(__name__)

# RSS parsing constants
MAX_ENTRIES_TO_PROCESS = 1000  # Prevent memory issues with huge feeds
RSS_TIMEOUT_SECONDS = 30


class RssExtractor(BaseExtractor):
    """Extract news items from RSS feeds."""

    def extract(self, source: SourceConfig, **kwargs) -> List[NewsItem]:
        """
        Extract news items from an RSS feed.

        Args:
            source: RSS source configuration
            **kwargs: Optional filters (days_back, max_articles)

        Returns:
            List of NewsItem objects extracted from the feed

        Raises:
            ValueError: On invalid source configuration
            RuntimeError: On feed parsing or network errors
        """
        url = source.get_url(**kwargs)
        logger.info(f"Extracting from RSS feed: {source.name} ({url})")

        # Validate URL
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid RSS URL: {url}")

        try:
            # Fetch the feed with timeout
            response = self.http_client.get(url, timeout=RSS_TIMEOUT_SECONDS)
            
            if not response.content:
                logger.warning(f"Empty response from RSS feed: {source.name}")
                return []

            # Parse RSS feed
            feed = feedparser.parse(response.content)
            
            # Validate feed structure
            if not self._is_valid_feed(feed, source.name):
                return []

            # Check for feed-level errors
            if hasattr(feed, 'bozo') and feed.bozo:
                logger.warning(f"RSS feed parsing warnings for {source.name}: {getattr(feed, 'bozo_exception', 'Unknown')}")

            items = []
            max_articles = kwargs.get("max_articles") or source.max_articles
            days_back = kwargs.get("days_back") or source.days_back

            # Process each entry
            for entry in feed.entries:
                try:
                    news_item = self._parse_entry(entry, source, days_back)
                    if news_item:
                        items.append(news_item)

                        # Respect max_articles limit
                        if max_articles and len(items) >= max_articles:
                            break

                except Exception as e:
                    logger.warning(f"Error parsing RSS entry: {e}")
                    continue

            logger.info(f"Extracted {len(items)} items from {source.name}")
            return items

        except Exception as e:
            logger.error(f"Error extracting from RSS feed {source.name}: {e}")
            raise

    def _parse_entry(
        self,
        entry: dict,
        source: SourceConfig,
        days_back: int = None,
    ) -> NewsItem | None:
        """
        Parse a single RSS entry into a NewsItem.

        Args:
            entry: feedparser entry dict
            source: Source configuration
            days_back: Optional filter - only return items within this many days

        Returns:
            NewsItem or None if filtered out
        """
        # Extract URL
        url = entry.get("link")
        if not url:
            logger.debug("RSS entry missing link, skipping")
            return None

        # Extract publish date
        published_date = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_date = datetime(*entry.published_parsed[:6])
            except (TypeError, ValueError):
                pass

        # Try alternative date fields
        if not published_date:
            for date_field in ["published", "updated", "created"]:
                date_str = entry.get(date_field)
                if date_str:
                    try:
                        published_date = date_parser.parse(date_str)
                        break
                    except (ValueError, TypeError):
                        continue

        # Filter by date if specified
        if days_back and published_date:
            cutoff = datetime.utcnow()
            cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
            age_days = (cutoff - published_date.replace(tzinfo=None)).days

            if age_days > days_back:
                logger.debug(f"Filtering out old article ({age_days} days old)")
                return None

        # Extract other metadata
        title = entry.get("title")
        description = entry.get("summary") or entry.get("description")
        author = entry.get("author")

        # Extract tags
        tags = []
        if hasattr(entry, "tags"):
            tags = [tag.term for tag in entry.tags if hasattr(tag, "term")]

        return self._create_news_item(
            url=url,
            source=source,
            title=title,
            published_date=published_date,
            description=description,
            author=author,
            tags=tags,
        )

    def _is_valid_url(self, url: str) -> bool:
        """Validate RSS URL format."""
        try:
            result = urlparse(url)
            return all([result.scheme in ('http', 'https'), result.netloc])
        except Exception:
            return False

    def _is_valid_feed(self, feed: feedparser.FeedParserDict, source_name: str) -> bool:
        """Validate feed structure and content."""
        if not hasattr(feed, 'entries'):
            logger.error(f"Invalid RSS feed structure for {source_name}: no entries")
            return False
            
        if not feed.entries:
            logger.warning(f"RSS feed {source_name} contains no entries")
            return False
            
        return True
