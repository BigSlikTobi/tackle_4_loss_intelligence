"""
Base extractor interface for news sources.

Defines the contract that all source-specific extractors must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..contracts import NewsItem
from ..config import SourceConfig
from ..utils import HttpClient


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
    ) -> NewsItem:
        """
        Helper to create a NewsItem with source metadata.

        Args:
            url: Article URL
            source: Source configuration
            **kwargs: Additional fields for NewsItem

        Returns:
            NewsItem with source metadata populated
        """
        return NewsItem(
            url=url,
            publisher=source.publisher,
            source_name=source.name,
            source_type=source.type,
            is_nfl_content=source.nfl_only,
            **kwargs,
        )
