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

    def filter_existing_fact_ids(self, fact_ids: Sequence[str]) -> List[str]:
        """Return only fact IDs that exist in news_facts."""

        if not fact_ids:
            return []

        try:
            response = (
                self.client.table("news_facts")
                .select("id")
                .in_("id", list(fact_ids))
                .execute()
            )
            return [row["id"] for row in getattr(response, "data", []) or []]
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to check existing fact ids: %s", exc)
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

    def stream_facts(
        self,
        *,
        limit: Optional[int] = None,
        page_size: int = 1000,
        require_topics: bool = False,
        require_entities: bool = False,
        skip_on_error: bool = False,
        pending_urls_only: bool = True,
    ):
        """Yield fact rows with optional filtering for missing knowledge.

        Args:
            limit: Maximum number of facts to yield (None for all).
            page_size: Supabase page size (defaults to 1000 to respect pagination guidance).
            require_topics: When True, only yield facts missing topic rows.
            require_entities: When True, only yield facts missing entity rows.
            skip_on_error: When True, skip a page that repeatedly errors after minimal page size.
            pending_urls_only: When True, filter to URLs that have not completed knowledge extraction.
        """

        table_name = "news_facts"
        select_fields = ["id", "fact_text"]

        # Use optimized views that already filter to missing knowledge
        # BUT only if we don't need to filter by pending URLs (knowledge_extracted_at)
        using_view = False
        fact_id_field = "id"
        if require_entities and not require_topics and not pending_urls_only:
            table_name = "news_facts_without_entities"
            using_view = True
            fact_id_field = "id"
        elif require_topics and not require_entities and not pending_urls_only:
            table_name = "news_facts_without_topics"
            using_view = True
            fact_id_field = "id"
        else:
            if require_topics:
                select_fields.append("news_fact_topics!left(id)")
            if require_entities:
                select_fields.append("news_fact_entities!left(id)")

        if using_view:
            select_fields = [fact_id_field]

        apply_pending_filter = pending_urls_only and (require_topics or require_entities)
        if apply_pending_filter:
            select_fields.append("news_urls!inner(id)")
        select_clause = ",".join(select_fields)

        offset = 0
        yielded = 0
        current_page_size = page_size

        while True:
            remaining = None if limit is None else max(limit - yielded, 0)
            if remaining == 0:
                break
            page_limit = current_page_size if remaining is None else min(current_page_size, remaining)

            query = self.client.table(table_name).select(select_clause)

            # Views only expose id; order by id to keep pagination stable
            if using_view:
                query = query.order(fact_id_field, desc=False)
            else:
                query = query.order("created_at", desc=False)

            query = query.range(offset, offset + page_limit - 1)

            if require_topics and not using_view:
                query = query.is_("news_fact_topics.id", None)

            if require_entities and not using_view:
                query = query.is_("news_fact_entities.id", None)

            if apply_pending_filter:
                query = query.is_("news_urls.knowledge_extracted_at", None)

            try:
                response = query.execute()
            except Exception as exc:
                if page_limit > 50:
                    new_size = max(50, page_limit // 2)
                    logger.warning(
                        "Reducing page size after error at offset %s (from %s to %s): %s",
                        offset,
                        page_limit,
                        new_size,
                        self._format_error(exc),
                    )
                    current_page_size = new_size
                    continue
                if skip_on_error:
                    logger.error(
                        "Skipping facts page at offset %s after repeated errors: %s",
                        offset,
                        self._format_error(exc),
                    )
                    # Attempt a quick diagnostic fetch to identify offending rows
                    self._log_problematic_rows(offset, current_page_size)
                    # Best-effort per-row fallback to salvage good rows
                    if not using_view:
                        for row_offset in range(offset, offset + page_limit):
                            single = self._fetch_single_fact(
                                offset=row_offset,
                                require_topics=require_topics,
                                require_entities=require_entities,
                                pending_urls_only=apply_pending_filter,
                                table_name=table_name,
                                using_view=using_view,
                            )
                            if not single:
                                continue
                            if limit is not None and yielded >= limit:
                                return
                            yielded += 1
                            yield single
                    offset += page_limit
                    continue
                logger.error("Failed to stream facts at offset %s: %s", offset, self._format_error(exc))
                raise

            rows = getattr(response, "data", []) or []

            if not rows:
                break

            if using_view:
                fact_ids = [row.get(fact_id_field) for row in rows if row.get(fact_id_field)]
                if not fact_ids:
                    offset += len(rows)
                    if len(rows) < page_limit:
                        break
                    continue
                facts_response = (
                    self.client.table("news_facts")
                    .select("id,fact_text")
                    .in_("id", fact_ids)
                    .execute()
                )
                facts_rows = getattr(facts_response, "data", []) or []
                facts_map = {row["id"]: (row.get("fact_text") or "").strip() for row in facts_rows}
                ordered_rows = [{"id": fid, "fact_text": facts_map.get(fid, "")} for fid in fact_ids]
            else:
                ordered_rows = rows

            for row in ordered_rows:
                if limit is not None and yielded >= limit:
                    return

                topic_links = row.get("news_fact_topics") or []
                entity_links = row.get("news_fact_entities") or []

                if require_topics and topic_links:
                    continue

                if require_entities and entity_links:
                    continue

                fact_text = (row.get("fact_text") or "").strip()
                fact_id = row.get("id")

                if not fact_id or not fact_text:
                    continue

                yielded += 1
                yield {
                    "id": fact_id,
                    "fact_text": fact_text,
                }

            offset += len(rows)

            if len(rows) < page_limit:
                break

    def _fetch_single_fact(
        self,
        *,
        offset: int,
        require_topics: bool,
        require_entities: bool,
        pending_urls_only: bool,
        table_name: str = "news_facts",
        using_view: bool = False,
    ) -> Optional[Dict]:
        """Fetch a single fact by offset with minimal fields; return None if it fails."""

        if using_view:
            return None  # views only include id; skip per-row salvage for error cases
        try:
            response = (
                self.client.table(table_name)
                .select("id,fact_text,news_url_id")
                .order("created_at", desc=False)
                .range(offset, offset)
                .single()
                .execute()
            )
        except Exception as exc:  # pragma: no cover - best-effort recovery
            logger.error("Per-row fetch failed at offset %s: %s", offset, self._format_error(exc))
            return None

        row = getattr(response, "data", None) or {}
        fact_id = row.get("id")
        fact_text = (row.get("fact_text") or "").strip()
        news_url_id = row.get("news_url_id")
        if not fact_id or not fact_text:
            return None
        if pending_urls_only and news_url_id and not self._is_news_url_pending(news_url_id):
            return None
        if using_view:
            return {"id": fact_id, "fact_text": fact_text}

        topic_links: list = []
        entity_links: list = []

        # Only fetch link presence if needed
        if require_topics:
            try:
                topic_resp = (
                    self.client.table("news_fact_topics")
                    .select("id")
                    .eq("news_fact_id", fact_id)
                    .limit(1)
                    .execute()
                )
                topic_links = getattr(topic_resp, "data", []) or []
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning("Topic link fetch failed for %s: %s", fact_id, self._format_error(exc))
        if require_entities:
            try:
                entity_resp = (
                    self.client.table("news_fact_entities")
                    .select("id")
                    .eq("news_fact_id", fact_id)
                    .limit(1)
                    .execute()
                )
                entity_links = getattr(entity_resp, "data", []) or []
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning("Entity link fetch failed for %s: %s", fact_id, self._format_error(exc))

        if require_topics and topic_links:
            return None
        if require_entities and entity_links:
            return None

        return {"id": fact_id, "fact_text": fact_text}

    def _format_error(self, exc: Exception) -> str:
        """Return a detailed string for API errors."""
        parts = [str(exc)]
        for attr in ("message", "code", "details", "hint"):
            val = getattr(exc, attr, None)
            if val:
                parts.append(f"{attr}={val}")
        return "; ".join(parts)

    def _log_problematic_rows(self, offset: int, limit: int) -> None:
        """Attempt to identify rows causing serialization errors."""
        try:
            id_only = (
                self.client.table("news_facts")
                .select("id")
                .order("created_at", desc=False)
                .range(offset, offset + limit - 1)
                .execute()
            )
            ids = [row["id"] for row in getattr(id_only, "data", []) or []]
        except Exception as exc:  # pragma: no cover - best-effort logging
            logger.error("Diagnostic id fetch failed at offset %s: %s", offset, self._format_error(exc))
            return

        for fact_id in ids:
            try:
                self.client.table("news_facts").select("id,fact_text").eq("id", fact_id).single().execute()
            except Exception as exc:  # pragma: no cover - best-effort logging
                logger.error("Problematic fact id %s failed to serialize: %s", fact_id, self._format_error(exc))
                break

    def _is_news_url_pending(self, news_url_id: str) -> bool:
        """Return True when the parent news_url has not completed knowledge extraction."""
        try:
            response = (
                self.client.table("news_urls")
                .select("knowledge_extracted_at")
                .eq("id", news_url_id)
                .limit(1)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            if not rows:
                return False
            return rows[0].get("knowledge_extracted_at") is None
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to check knowledge status for %s: %s", news_url_id, self._format_error(exc))
            return True
