"""JSON API extractor for app-facing news endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import logging

from ..config import SourceConfig
from ..contracts import NewsItem
from ..utils.dates import parse_feed_date
from .base import BaseExtractor

logger = logging.getLogger(__name__)

MAX_ARTICLES_TO_PROCESS = 1000
JSON_API_TIMEOUT_SECONDS = 30
DEFAULT_REQUEST_LIMIT = 50
MAX_REQUEST_LIMIT = 50
SUPPORTED_ARTICLE_TYPES = {"Story", "HeadlineNews"}
JSON_ACCEPT_HEADER = "application/json,text/plain;q=0.9,*/*;q=0.8"


class JsonApiExtractor(BaseExtractor):
    """Extract article URLs from a JSON news feed."""

    def extract(self, source: SourceConfig, **kwargs) -> List[NewsItem]:
        url = self._build_request_url(
            source.get_url(**kwargs),
            requested_max_articles=kwargs.get("max_articles") or source.max_articles,
        )
        logger.info("Extracting from JSON API: %s (%s)", source.name, url)

        try:
            response = self.http_client.get(
                url,
                timeout=JSON_API_TIMEOUT_SECONDS,
                headers={"Accept": JSON_ACCEPT_HEADER},
            )
            payload = response.json()
        except ValueError as exc:
            logger.error("Invalid JSON from %s: %s", source.name, exc)
            raise RuntimeError(f"Invalid JSON response from {source.name}") from exc
        except Exception as exc:
            logger.error("Error extracting from JSON API %s: %s", source.name, exc)
            raise

        articles = payload.get("articles")
        if not isinstance(articles, list):
            logger.warning("JSON API %s missing articles list", source.name)
            return []

        items: List[NewsItem] = []
        max_articles = kwargs.get("max_articles") or source.max_articles
        days_back = kwargs.get("days_back") or source.days_back

        for article in articles[:MAX_ARTICLES_TO_PROCESS]:
            try:
                item = self._parse_article(article, source, days_back=days_back)
            except Exception as exc:
                logger.warning("Error parsing JSON API article for %s: %s", source.name, exc)
                continue

            if item is None:
                continue

            items.append(item)
            if max_articles and len(items) >= max_articles:
                break

        logger.info("Extracted %d items from %s", len(items), source.name)
        return items

    def _parse_article(
        self,
        article: Dict[str, Any],
        source: SourceConfig,
        *,
        days_back: Optional[int] = None,
    ) -> Optional[NewsItem]:
        article_type = article.get("type")
        if article_type not in SUPPORTED_ARTICLE_TYPES:
            return None

        url = self._extract_url(article)
        if not url:
            logger.debug("JSON API article missing web href, skipping")
            return None

        published_date = parse_feed_date(
            article.get("published") or article.get("lastModified")
        )
        if days_back and published_date:
            cutoff = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            age_days = (cutoff - published_date).days
            if age_days > days_back:
                return None

        return self._create_news_item(
            url=url,
            source=source,
            title=article.get("headline"),
            published_date=published_date,
            description=article.get("description"),
            author=article.get("byline"),
            tags=self._extract_tags(article),
        )

    def _extract_url(self, article: Dict[str, Any]) -> Optional[str]:
        links = article.get("links")
        if not isinstance(links, dict):
            return None
        web = links.get("web")
        if not isinstance(web, dict):
            return None
        href = web.get("href")
        if isinstance(href, str) and href.startswith(("http://", "https://")):
            return href
        return None

    def _extract_tags(self, article: Dict[str, Any]) -> List[str]:
        categories = article.get("categories")
        if not isinstance(categories, list):
            return []

        tags: List[str] = []
        for category in categories:
            if not isinstance(category, dict):
                continue
            description = category.get("description")
            if isinstance(description, str) and description:
                tags.append(description)
        return tags

    def _build_request_url(
        self,
        base_url: str,
        *,
        requested_max_articles: Optional[int],
    ) -> str:
        limit = requested_max_articles or DEFAULT_REQUEST_LIMIT
        limit = max(1, min(int(limit), MAX_REQUEST_LIMIT))

        parsed = urlparse(base_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["limit"] = str(limit)
        return urlunparse(parsed._replace(query=urlencode(query)))
