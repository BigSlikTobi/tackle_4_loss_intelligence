"""Metadata enrichment helpers for extracted content."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from ..contracts.extracted_content import ExtractedContent, ExtractionMetadata


def _parse_meta(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def enrich_metadata(content: ExtractedContent, *, html: str, extractor_name: str) -> ExtractedContent:
    """Populate missing metadata fields from page markup."""

    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    description = _parse_meta(soup, "og:description", "twitter:description", "description")
    author = _parse_meta(soup, "article:author", "author", "og:author")
    published_raw = _parse_meta(soup, "article:published_time", "og:published_time", "pubdate")

    content.title = content.title or title
    content.description = content.description or description
    content.author = content.author or author
    published_at = _parse_datetime(published_raw)
    if published_at:
        content.published_at = content.published_at or published_at

    if not content.metadata:
        content.metadata = ExtractionMetadata(
            fetched_at=datetime.utcnow(),
            extractor=extractor_name,
            duration_seconds=0.0,
        )

    lang_tag = soup.find("html")
    if lang_tag and lang_tag.get("lang"):
        content.metadata.page_language = lang_tag["lang"]
    content.metadata.raw_url = content.metadata.raw_url or content.url

    return content
