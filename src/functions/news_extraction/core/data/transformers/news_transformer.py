"""
News URL transformer.

Transforms NewsItem objects into NewsUrl database records.
"""

from __future__ import annotations

from datetime import datetime, timezone
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

        extracted_date = datetime.now(timezone.utc)
        records = [
            NewsUrl.from_news_item(item, extracted_date).to_dict() for item in items
        ]

        logger.info(f"Transformed {len(records)} records")
        return records
