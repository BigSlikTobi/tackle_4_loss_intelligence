"""Helpers for marking URLs knowledge-complete once both topics and entities exist."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence, Set

from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)


class KnowledgeCompletionTracker:
    """Promote URLs to knowledge-complete only when all facts have both sides."""

    def __init__(self, client=None) -> None:
        self.client = client or get_supabase_client()

    def mark_complete_for_fact_ids(
        self,
        fact_ids: Sequence[str],
        *,
        dry_run: bool = False,
    ) -> int:
        """Mark parent URLs complete when every fact has both topics and entities."""

        if not fact_ids:
            return 0

        url_ids = self._load_url_ids_for_facts(fact_ids)
        if not url_ids:
            return 0

        return self.mark_complete_for_url_ids(url_ids, dry_run=dry_run)

    def mark_complete_for_url_ids(
        self,
        url_ids: Iterable[str],
        *,
        dry_run: bool = False,
    ) -> int:
        """Mark URL rows complete when all of their facts have topics and entities."""

        candidate_ids = {url_id for url_id in url_ids if url_id}
        if not candidate_ids:
            return 0

        complete_ids = self._filter_complete_url_ids(candidate_ids)
        if not complete_ids:
            return 0

        if dry_run:
            logger.info(
                "[DRY RUN] Would set knowledge_extracted_at for %d URL(s)",
                len(complete_ids),
            )
            return len(complete_ids)

        timestamp = datetime.now(timezone.utc).isoformat()
        self.client.table("news_urls").update(
            {
                "knowledge_extracted_at": timestamp,
                "knowledge_error_count": 0,
            }
        ).in_("id", list(complete_ids)).execute()
        logger.info("Marked %d URL(s) knowledge-complete", len(complete_ids))
        return len(complete_ids)

    def _load_url_ids_for_facts(self, fact_ids: Sequence[str]) -> Set[str]:
        url_ids: Set[str] = set()
        for chunk in _chunked(fact_ids, size=500):
            response = (
                self.client.table("news_facts")
                .select("news_url_id")
                .in_("id", chunk)
                .execute()
            )
            for row in getattr(response, "data", []) or []:
                if row.get("news_url_id"):
                    url_ids.add(row["news_url_id"])
        return url_ids

    def _filter_complete_url_ids(self, url_ids: Set[str]) -> Set[str]:
        url_to_facts: dict[str, Set[str]] = {url_id: set() for url_id in url_ids}

        for chunk in _chunked(url_ids, size=500):
            response = (
                self.client.table("news_facts")
                .select("id,news_url_id")
                .in_("news_url_id", chunk)
                .execute()
            )
            for row in getattr(response, "data", []) or []:
                url_id = row.get("news_url_id")
                fact_id = row.get("id")
                if url_id and fact_id:
                    url_to_facts.setdefault(url_id, set()).add(fact_id)

        all_fact_ids = {
            fact_id
            for fact_ids in url_to_facts.values()
            for fact_id in fact_ids
        }
        if not all_fact_ids:
            return set()

        facts_with_topics = self._load_fact_id_set("news_fact_topics", all_fact_ids)
        facts_with_entities = self._load_fact_id_set("news_fact_entities", all_fact_ids)

        complete_ids: Set[str] = set()
        for url_id, fact_ids in url_to_facts.items():
            if not fact_ids:
                continue
            if all(
                fact_id in facts_with_topics and fact_id in facts_with_entities
                for fact_id in fact_ids
            ):
                complete_ids.add(url_id)

        incomplete = len(url_ids) - len(complete_ids)
        if incomplete:
            logger.info(
                "Skipping knowledge completion for %d URL(s) still missing topics or entities",
                incomplete,
            )

        return complete_ids

    def _load_fact_id_set(self, table_name: str, fact_ids: Set[str]) -> Set[str]:
        result: Set[str] = set()
        for chunk in _chunked(fact_ids, size=500):
            response = (
                self.client.table(table_name)
                .select("news_fact_id")
                .in_("news_fact_id", chunk)
                .execute()
            )
            for row in getattr(response, "data", []) or []:
                if row.get("news_fact_id"):
                    result.add(row["news_fact_id"])
        return result


def _chunked(values: Iterable[str], *, size: int) -> list[list[str]]:
    items = list(values)
    return [items[i : i + size] for i in range(0, len(items), size)]
