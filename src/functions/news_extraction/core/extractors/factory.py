"""
Extractor factory.

Provides factory function to get the appropriate extractor for a source type.
"""

from __future__ import annotations

from typing import Type
import logging

from ..utils import HttpClient
from .base import BaseExtractor
from .rss import RssExtractor
from .sitemap import SitemapExtractor

logger = logging.getLogger(__name__)


# Mapping of source types to extractor classes
EXTRACTOR_MAP: dict[str, Type[BaseExtractor]] = {
    "rss": RssExtractor,
    "sitemap": SitemapExtractor,
    # Future: 'html': HtmlExtractor
}


def get_extractor(source_type: str, http_client: HttpClient) -> BaseExtractor:
    """
    Get the appropriate extractor for a source type.

    Args:
        source_type: Type of source ('rss', 'sitemap', 'html')
        http_client: Configured HTTP client to use

    Returns:
        Instantiated extractor for the source type

    Raises:
        ValueError: If source_type is not supported
    """
    extractor_class = EXTRACTOR_MAP.get(source_type)

    if not extractor_class:
        supported = ", ".join(EXTRACTOR_MAP.keys())
        raise ValueError(f"Unsupported source type '{source_type}'. Supported: {supported}")

    return extractor_class(http_client)
