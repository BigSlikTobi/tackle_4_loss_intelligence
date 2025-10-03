"""
Sitemap extractor.

Fetches and parses XML sitemaps to extract article URLs and metadata.
Optimized for production use with comprehensive error handling.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from dateutil import parser as date_parser
import logging

from ..contracts import NewsItem
from ..config import SourceConfig
from .base import BaseExtractor

logger = logging.getLogger(__name__)

# Sitemap processing constants
MAX_URLS_TO_PROCESS = 5000  # Prevent memory issues with huge sitemaps
SITEMAP_TIMEOUT_SECONDS = 45


class SitemapExtractor(BaseExtractor):
    """Extract news items from XML sitemaps."""

    def extract(self, source: SourceConfig, **kwargs) -> List[NewsItem]:
        """
        Extract news items from a sitemap.

        Args:
            source: Sitemap source configuration
            **kwargs: Template variables (YYYY, MM) and filters (days_back, max_articles)

        Returns:
            List of NewsItem objects extracted from the sitemap

        Raises:
            Exception: On fetch or parse errors
        """
        # Resolve template variables (e.g., {YYYY}/{MM})
        template_vars = self._get_template_vars(**kwargs)
        url = source.get_url(**template_vars)

        logger.info(f"Extracting from sitemap: {source.name} ({url})")

        # Validate URL
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid sitemap URL: {url}")

        try:
            # Fetch the sitemap with timeout
            response = self.http_client.get(url, timeout=SITEMAP_TIMEOUT_SECONDS)
            
            if not response.content:
                logger.warning(f"Empty response from sitemap: {source.name}")
                return []

            # Parse XML with error handling
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as e:
                logger.error(f"XML parse error for sitemap {source.name}: {e}")
                raise RuntimeError(f"Invalid XML in sitemap {source.name}") from e

            # Handle namespaces
            namespaces = {
                "ns": "http://www.sitemaps.org/schemas/sitemap/0.9",
                "news": "http://www.google.com/schemas/sitemap-news/0.9",
            }

            items = []
            max_articles = kwargs.get("max_articles") or source.max_articles
            days_back = kwargs.get("days_back") or source.days_back

            # Find all <url> elements with limit to prevent memory issues
            url_elements = root.findall("ns:url", namespaces)[:MAX_URLS_TO_PROCESS]
            
            for url_elem in url_elements:
                try:
                    news_item = self._parse_url_element(url_elem, source, namespaces, days_back)
                    if news_item:
                        items.append(news_item)

                        # Respect max_articles limit
                        if max_articles and len(items) >= max_articles:
                            break

                except Exception as e:
                    logger.warning(f"Error parsing sitemap URL element from {source.name}: {e}")
                    continue

            logger.info(f"Extracted {len(items)} items from {source.name}")
            return items

        except ET.ParseError as e:
            logger.error(f"XML parse error for sitemap {source.name}: {e}")
            raise RuntimeError(f"Sitemap XML parsing failed for {source.name}: {e}") from e

        except Exception as e:
            logger.error(f"Error extracting from sitemap {source.name}: {e}")
            raise RuntimeError(f"Sitemap extraction failed for {source.name}: {e}") from e

    def _parse_url_element(
        self,
        url_elem: ET.Element,
        source: SourceConfig,
        namespaces: dict,
        days_back: int = None,
    ) -> NewsItem | None:
        """
        Parse a single <url> element into a NewsItem.

        Args:
            url_elem: XML <url> element
            source: Source configuration
            namespaces: XML namespaces dict
            days_back: Optional filter - only return items within this many days

        Returns:
            NewsItem or None if filtered out
        """
        # Extract URL
        loc_elem = url_elem.find("ns:loc", namespaces)
        if loc_elem is None or not loc_elem.text:
            logger.debug("Sitemap URL element missing <loc>, skipping")
            return None

        url = loc_elem.text.strip()

        # Extract lastmod date
        published_date = None
        lastmod_elem = url_elem.find("ns:lastmod", namespaces)
        if lastmod_elem is not None and lastmod_elem.text:
            try:
                published_date = date_parser.parse(lastmod_elem.text)
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not parse lastmod date: {e}")

        # Try to extract title from news:news element
        title = None
        news_elem = url_elem.find("news:news", namespaces)
        if news_elem is not None:
            title_elem = news_elem.find("news:title", namespaces)
            if title_elem is not None and title_elem.text:
                title = title_elem.text.strip()

            # Also try to get publication date from news namespace
            if not published_date:
                pub_date_elem = news_elem.find("news:publication_date", namespaces)
                if pub_date_elem is not None and pub_date_elem.text:
                    try:
                        published_date = date_parser.parse(pub_date_elem.text)
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Could not parse news publication date: {e}")

        # Filter by date if specified
        if days_back and published_date:
            cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            if published_date.tzinfo is None:
                published_date = published_date.replace(tzinfo=timezone.utc)
                
            age_days = (cutoff - published_date).days

            if age_days > days_back:
                logger.debug(f"Filtering out old article ({age_days} days old)")
                return None

        # Create NewsItem with extracted data
        return self._create_news_item(
            url=url,
            source=source,
            title=title,
            published_date=published_date,
        )

    def _get_template_vars(self, **kwargs) -> dict:
        """
        Generate template variables for URL construction.

        Args:
            **kwargs: Optional YYYY, MM overrides

        Returns:
            Dict with YYYY, MM keys for current date (or overrides)
        """
        now = datetime.utcnow()
        return {
            "YYYY": kwargs.get("YYYY", str(now.year)),
            "MM": kwargs.get("MM", f"{now.month:02d}"),
        }

    def _is_valid_url(self, url: str) -> bool:
        """Validate sitemap URL format."""
        try:
            result = urlparse(url)
            return all([result.scheme in ('http', 'https'), result.netloc])
        except Exception:
            return False
