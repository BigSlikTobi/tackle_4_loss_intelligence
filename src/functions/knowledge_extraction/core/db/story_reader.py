"""Compatibility reader bridging legacy story group interface to fact data."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .fact_reader import NewsFactReader

logger = logging.getLogger(__name__)


class StoryGroupReader:
    """Maintain backward compatibility for batch utilities expecting story groups."""

    def __init__(self) -> None:
        self._fact_reader = NewsFactReader()
        logger.info("Initialized StoryGroupReader compatibility wrapper")

    def get_unextracted_groups(
        self,
        limit: Optional[int] = 100,
        retry_failed: bool = False,
        max_error_count: int = 3,
    ) -> List[Dict]:
        """Return records resembling story groups using pending news URLs."""

        return self._fact_reader.get_urls_pending_extraction(
            limit=limit,
            retry_failed=retry_failed,
            max_error_count=max_error_count,
        )

    def get_group_summaries(self, story_group_id: str) -> List[Dict]:
        """Return fact records mapped as summary payloads for legacy callers."""

        facts = self._fact_reader.get_facts_for_url(story_group_id)
        summaries: List[Dict] = []
        for fact in facts:
            fact_text = fact.get("fact_text")
            if not isinstance(fact_text, str):
                continue
            summaries.append({"summary_text": fact_text})
        return summaries

    def get_progress_stats(self) -> Dict[str, int]:
        """Return simple statistics for compatibility with legacy progress views."""

        raw = self._fact_reader.get_progress_stats()
        total_groups = raw.get("facts", 0)
        return {
            "total_groups": total_groups,
            "extracted_groups": total_groups,
            "remaining_groups": 0,
            "failed_groups": 0,
            "partial_groups": 0,
            "processing_groups": 0,
            "total_topics": raw.get("topics", 0),
            "total_entities": raw.get("entities", 0),
            "avg_topics_per_group": 0,
            "avg_entities_per_group": 0,
        }
