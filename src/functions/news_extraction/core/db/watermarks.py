"""High-water mark tracking for news sources.

This store keeps the most recent published date we have processed for
each source so scheduled runs can avoid re-processing the same feeds.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict

from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)


class NewsSourceWatermarkStore:
    """Persist per-source high-water marks for news extraction."""

    TABLE_NAME = "news_source_watermarks"

    def __init__(self) -> None:
        self.client = get_supabase_client()

    def fetch_watermarks(self) -> Dict[str, datetime]:
        """Return the latest published date per source.

        Returns:
            Mapping of source name to last processed published timestamp.
        """
        try:
            response = (
                self.client.table(self.TABLE_NAME)
                .select("source_name,last_published_at")
                .execute()
            )
            rows = getattr(response, "data", []) or []
            watermarks: Dict[str, datetime] = {}
            for row in rows:
                value = row.get("last_published_at")
                if not value:
                    continue
                if isinstance(value, str):
                    try:
                        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        logger.warning("Skipping invalid watermark value for %s", row.get("source_name"))
                        continue
                if isinstance(value, datetime):
                    watermarks[row.get("source_name", "")] = value
            logger.info("Loaded %d source watermarks", len(watermarks))
            return watermarks
        except Exception as exc:
            logger.warning("Failed to load source watermarks: %s", exc)
            return {}

    def update_watermarks(self, updates: Dict[str, datetime]) -> None:
        """Upsert new watermarks.

        Args:
            updates: Mapping of source name to newest published timestamp.
        """
        if not updates:
            return

        payload = []
        for source, watermark in updates.items():
            if not source or not isinstance(watermark, datetime):
                continue
            payload.append(
                {
                    "source_name": source,
                    "last_published_at": watermark.isoformat(),
                    "last_seen_at": watermark.isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )

        if not payload:
            return

        try:
            self.client.table(self.TABLE_NAME).upsert(payload).execute()
            logger.info("Updated %d source watermarks", len(payload))
        except Exception as exc:
            logger.warning("Failed to update source watermarks: %s", exc)
