"""
Base extractor interface for news sources.

Defines the contract that all source-specific extractors must implement.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.parse import urlparse

from ..contracts import NewsItem
from ..config import SourceConfig
from ..utils import HttpClient


# Mixed-sport sites (ESPN, CBS, Yahoo, ...) segregate NFL content under a
# dedicated /nfl/ path segment. We require the segment boundary on both
# sides so slug text like "-nfl-style-draft" (soccer analogy) or
# "-nfl-fan-pga-tour" (golf article) doesn't false-positive. Title-based
# matching was tested and dropped for the same reason.
_NFL_URL_RE = re.compile(r"/nfl(?:/|$)", re.IGNORECASE)

# NFL-dedicated hosts: every URL is NFL by definition, regardless of path.
# Add subdomains as needed (e.g. operations.nfl.com, www.nfl.com).
_NFL_HOSTS = {"nfl.com"}


def _looks_nfl(url: str, title: Optional[str] = None) -> bool:
    """Return True when the URL is identifiably NFL-related.

    Two signals, either of which is sufficient:

    1. URL path contains a ``/nfl/`` segment (mixed-sport sites).
    2. URL host is an NFL-dedicated domain (currently nfl.com + subdomains).
    """
    if not url:
        return False
    if _NFL_URL_RE.search(url):
        return True
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    # Match exact host or any subdomain of an NFL-dedicated domain.
    if host in _NFL_HOSTS:
        return True
    return any(host.endswith("." + nfl_host) for nfl_host in _NFL_HOSTS)


class BaseExtractor(ABC):
    """
    Abstract base class for news source extractors.

    All extractors (RSS, Sitemap, HTML) must implement the extract() method.
    """

    def __init__(self, http_client: HttpClient):
        """
        Initialize extractor with HTTP client.

        Args:
            http_client: Configured HttpClient for making requests
        """
        self.http_client = http_client

    @abstractmethod
    def extract(self, source: SourceConfig, **kwargs) -> List[NewsItem]:
        """
        Extract news items from a source.

        Args:
            source: Source configuration
            **kwargs: Additional parameters (e.g., template variables, filters)

        Returns:
            List of extracted NewsItem objects

        Raises:
            Exception: On extraction errors (specific to implementation)
        """
        pass

    def _create_news_item(
        self,
        url: str,
        source: SourceConfig,
        **kwargs,
    ) -> Optional[NewsItem]:
        """
        Helper to create a NewsItem with source metadata.

        Returns ``None`` when ``source.nfl_only`` is True but the item
        doesn't look like NFL content. Both RSS and sitemap parsers
        already drop ``None`` items, so this is the single point of
        per-source NFL filtering — sources that pull from a general
        sports feed (e.g. ESPN's /espn/rss/news, which mixes NBA/MLB/NFL)
        get item-level filtering for free.
        """
        title = kwargs.get("title")
        # Trust feed-context: when the source's own feed URL is NFL-specific
        # (e.g. https://sports.yahoo.com/nfl/rss/), every item it returns is
        # NFL by definition — even if the per-article URL no longer carries
        # a /nfl/ path segment after a publisher URL-structure change.
        feed_url = getattr(source, "url", None)
        is_nfl = _looks_nfl(url, title) or (bool(feed_url) and _looks_nfl(feed_url))
        if source.nfl_only and not is_nfl:
            return None
        return NewsItem(
            url=url,
            publisher=source.publisher,
            source_name=source.name,
            source_type=source.type,
            is_nfl_content=is_nfl,
            **kwargs,
        )
