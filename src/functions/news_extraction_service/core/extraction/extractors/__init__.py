"""Extractors for different news source types."""

from .base import BaseExtractor
from .rss import RssExtractor
from .sitemap import SitemapExtractor
from .factory import get_extractor

__all__ = ["BaseExtractor", "RssExtractor", "SitemapExtractor", "get_extractor"]
