"""Database reader utilities for fact-level knowledge extraction."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)


class NewsFactReader:
    """Fetch news facts and knowledge extraction progress from Supabase."""

    def __init__(self) -> None:
        self.client = get_supabase_client()
        logger.info("Initialized NewsFactReader")

    def get_urls_pending_extraction(
        self,
        *,
        limit: Optional[int] = 100,
        retry_failed: bool = False,
        max_error_count: int = 3,
    ) -> List[Dict]:
        """Return news_url rows that have facts but need knowledge extraction."""

        try:
            logger.info(
                "Fetching URLs pending knowledge extraction",
                {
                    "limit": limit,
                    "retry_failed": retry_failed,
                    "max_error_count": max_error_count,
                },
            )

            query = (
                self.client.table("news_urls")
                .select("id")
                .filter("facts_extracted_at", "not.is", "null")
                .is_("knowledge_extracted_at", None)
                .order("updated_at", desc=True)
            )

            if limit:
                query = query.limit(limit)

            if not retry_failed:
                query = query.lte("knowledge_error_count", max_error_count)

            response = query.execute()
            data = getattr(response, "data", []) or []
            logger.info("Found %d URLs pending knowledge extraction", len(data))
            return data
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to fetch pending URLs: %s", exc, exc_info=True)
            return []

    def get_facts_for_url(self, news_url_id: str) -> List[Dict]:
        """Return fact rows for a given news_url_id."""

        try:
            response = (
                self.client.table("news_facts")
                .select("id,fact_text")
                .eq("news_url_id", news_url_id)
                .order("created_at", desc=False)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            logger.info("Fetched %d facts for news_url_id=%s", len(rows), news_url_id)
            return rows
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "Failed to fetch facts for news_url_id=%s: %s",
                news_url_id,
                exc,
                exc_info=True,
            )
            return []

    def get_existing_topic_fact_ids(self, fact_ids: Sequence[str]) -> List[str]:
        """Return fact IDs that already have topic annotations."""

        if not fact_ids:
            return []

        try:
            response = (
                self.client.table("news_fact_topics")
                .select("news_fact_id")
                .in_("news_fact_id", list(fact_ids))
                .execute()
            )
            return [row["news_fact_id"] for row in getattr(response, "data", []) or []]
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to check existing topics: %s", exc)
            return []

    def get_existing_entity_fact_ids(self, fact_ids: Sequence[str]) -> List[str]:
        """Return fact IDs that already have entity annotations."""

        if not fact_ids:
            return []

        try:
            response = (
                self.client.table("news_fact_entities")
                .select("news_fact_id")
                .in_("news_fact_id", list(fact_ids))
                .execute()
            )
            return [row["news_fact_id"] for row in getattr(response, "data", []) or []]
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to check existing entities: %s", exc)
            return []

    def get_progress_stats(self) -> Dict[str, int]:
        """Return aggregate counts of extracted facts/topics/entities."""

        try:
            facts_response = (
                self.client.table("news_facts")
                .select("id", count="exact")
                .execute()
            )
            topics_response = (
                self.client.table("news_fact_topics")
                .select("id", count="exact")
                .execute()
            )
            entities_response = (
                self.client.table("news_fact_entities")
                .select("id", count="exact")
                .execute()
            )
            return {
                "facts": facts_response.count or 0,
                "topics": topics_response.count or 0,
                "entities": entities_response.count or 0,
            }
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to compute progress stats: %s", exc)
            return {"facts": 0, "topics": 0, "entities": 0}
