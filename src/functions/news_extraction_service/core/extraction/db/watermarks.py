"""High-water mark tracking for news sources.

This store keeps the most recent published date we have processed for
each source so scheduled runs can avoid re-processing the same feeds.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)

_PAGE_SIZE = 1000


class NewsSourceWatermarkStore:
    """Persist per-source high-water marks for news extraction."""

    TABLE_NAME = "news_source_watermarks"

    def __init__(self, client: Optional[Any] = None) -> None:
        """Initialize the store.

        Args:
            client: Optional Supabase client. If omitted, falls back to
                ``src.shared.db.connection.get_supabase_client``. Watermarks are
                an optimization; if no client is available (unit tests / local
                runs without credentials) the store degrades gracefully.
        """
        if client is not None:
            self.client = client
            return
        try:
            self.client = get_supabase_client()
        except (ValueError, ImportError) as exc:
            self.client = None
            logger.info("News source watermarks disabled (Supabase unavailable): %s", exc)

    def fetch_watermarks(self) -> Dict[str, datetime]:
        """Return the latest published date per source."""
        if self.client is None:
            return {}
        try:
            watermarks: Dict[str, datetime] = {}
            offset = 0
            while True:
                response = (
                    self.client.table(self.TABLE_NAME)
                    .select("source_name,last_published_at")
                    .range(offset, offset + _PAGE_SIZE - 1)
                    .execute()
                )
                rows = getattr(response, "data", []) or []
                if not rows:
                    break
                for row in rows:
                    value = row.get("last_published_at")
                    if not value:
                        continue
                    if isinstance(value, str):
                        try:
                            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        except ValueError:
                            logger.warning(
                                "Skipping invalid watermark value for %s",
                                row.get("source_name"),
                            )
                            continue
                    if isinstance(value, datetime):
                        watermarks[row.get("source_name", "")] = value
                if len(rows) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE
            logger.info("Loaded %d source watermarks", len(watermarks))
            return watermarks
        except Exception as exc:
            logger.warning("Failed to load source watermarks: %s", exc)
            return {}

    def update_watermarks(self, updates: Dict[str, datetime]) -> None:
        """Upsert new watermarks."""
        if not updates:
            return
        if self.client is None:
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
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        if not payload:
            return

        try:
            self.client.table(self.TABLE_NAME).upsert(payload).execute()
            logger.info("Updated %d source watermarks", len(payload))
        except Exception as exc:
            logger.warning("Failed to update source watermarks: %s", exc)
