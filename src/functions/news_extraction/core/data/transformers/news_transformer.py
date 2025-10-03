"""
News URL transformer.

Transforms NewsItem objects into NewsUrl database records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
import logging

from ...contracts import NewsItem, NewsUrl

logger = logging.getLogger(__name__)


class NewsTransformer:
    """
    Transform NewsItem objects to NewsUrl database records.

    Handles conversion from extraction format to database schema.
    """

    def transform(self, items: List[NewsItem]) -> List[Dict[str, Any]]:
        """
        Transform a list of NewsItem objects into database records.

        Args:
            items: List of NewsItem objects from extractors

        Returns:
            List of dictionaries ready for database insertion
        """
        logger.info(f"Transforming {len(items)} news items")

        extracted_date = datetime.utcnow()
        records = []

        for item in items:
            try:
                news_url = NewsUrl.from_news_item(item, extracted_date)
                records.append(news_url.to_dict())

            except Exception as e:
                logger.warning(f"Error transforming item {item.url}: {e}")
                continue

        logger.info(f"Transformed {len(records)} records")
        return records
