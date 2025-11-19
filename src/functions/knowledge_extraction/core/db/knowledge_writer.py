"""Database writer for fact-level topics and entities."""

from __future__ import annotations

import datetime
import logging
from typing import Dict, List, Sequence, Tuple

from src.shared.db.connection import get_supabase_client
from ..extraction.topic_extractor import ExtractedTopic
from ..resolution.entity_resolver import ResolvedEntity

logger = logging.getLogger(__name__)

FACT_TOPIC_PROMPT_VERSION = "fact-topic-v1"
FACT_ENTITY_PROMPT_VERSION = "fact-entity-v1"


def _canonicalize_topic(topic: str) -> str:
    """Return canonical topic key for downstream grouping."""

    if not topic:
        return "unknown"

    normalized = topic.lower().strip()
    if "injur" in normalized:
        return "injury"
    if any(keyword in normalized for keyword in ["trade", "roster move", "signing"]):
        return "trade"
    if "contract" in normalized or "cap" in normalized:
        return "contract"
    if any(keyword in normalized for keyword in ["game", "highlight", "matchup", "gameday", "week"]):
        return "gameday"
    if "rumor" in normalized:
        return "rumor"
    if "draft" in normalized or "prospect" in normalized:
        return "draft"
    if "fantasy" in normalized:
        return "fantasy"
    if "season" in normalized or "prediction" in normalized:
        return "season_outlook"
    if "offseason" in normalized or "training" in normalized:
        return "offseason"
    if "culture" in normalized or "leadership" in normalized:
        return "culture"
    if "profile" in normalized or "interview" in normalized:
        return "profile"
    if "defense" in normalized or "turnover" in normalized:
        return "defense"
    if "offense" in normalized or "quarterback" in normalized or "passing" in normalized:
        return "offense"
    if "league" in normalized:
        return "league"
    return normalized.replace(" ", "_")


class KnowledgeWriter:
    """Persist fact-level knowledge extraction outputs."""

    def __init__(self) -> None:
        self.client = get_supabase_client()
        logger.info("Initialized KnowledgeWriter")

    def write_fact_topics(
        self,
        *,
        news_fact_id: str,
        topics: Sequence[ExtractedTopic],
        llm_model: str,
        dry_run: bool = False,
    ) -> int:
        """Insert or upsert topic annotations for a fact."""

        if not topics:
            return 0

        dedup: Dict[str, ExtractedTopic] = {}
        for topic in topics:
            key = (topic.topic or "").strip().lower()
            if not key:
                continue
            existing = dedup.get(key)
            if not existing:
                dedup[key] = topic
                continue
            # Keep highest confidence / lowest rank
            existing_conf = existing.confidence or 0.0
            new_conf = topic.confidence or 0.0
            if new_conf > existing_conf:
                dedup[key] = topic
            elif new_conf == existing_conf:
                if (topic.rank or 99) < (existing.rank or 99):
                    dedup[key] = topic

        records: List[Dict] = []
        for key, topic in dedup.items():
            records.append(
                {
                    "news_fact_id": news_fact_id,
                    "topic": key,
                    "canonical_topic": _canonicalize_topic(key),
                    "confidence": topic.confidence,
                    "rank": topic.rank,
                    "is_primary": (topic.rank or 0) <= 1,
                    "llm_model": llm_model,
                    "prompt_version": FACT_TOPIC_PROMPT_VERSION,
                }
            )

        if not records:
            return 0

        if dry_run:
            logger.info(
                "[DRY RUN] Would insert %d fact topics for fact %s", len(records), news_fact_id
            )
            return len(records)

        response = (
            self.client.table("news_fact_topics")
            .upsert(records, on_conflict="news_fact_id,topic")
            .execute()
        )
        return len(getattr(response, "data", []) or records)

    def write_fact_entities(
        self,
        *,
        news_fact_id: str,
        entities: Sequence[ResolvedEntity],
        llm_model: str,
        dry_run: bool = False,
    ) -> int:
        """Insert resolved entities for a fact."""

        if not entities:
            return 0

        dedup: Dict[Tuple[str, str], ResolvedEntity] = {}
        for entity in entities:
            key = (entity.entity_type, entity.entity_id or entity.mention_text)
            existing = dedup.get(key)
            if not existing:
                dedup[key] = entity
                continue
            existing_conf = existing.confidence or 0.0
            new_conf = entity.confidence or 0.0
            if (entity.is_primary and not existing.is_primary) or (
                existing.is_primary == entity.is_primary and new_conf >= existing_conf
            ):
                dedup[key] = entity

        records: List[Dict] = []
        for entity in dedup.values():
            records.append(
                {
                    "news_fact_id": news_fact_id,
                    "entity_type": entity.entity_type,
                    "entity_id": entity.entity_id,
                    "mention_text": entity.mention_text,
                    "matched_name": entity.matched_name,
                    "confidence": entity.confidence,
                    "is_primary": entity.is_primary,
                    "rank": entity.rank,
                    "position": entity.position,
                    "team_abbr": entity.team_abbr,
                    "team_name": entity.team_name,
                    "llm_model": llm_model,
                    "prompt_version": FACT_ENTITY_PROMPT_VERSION,
                }
            )

        if not records:
            return 0

        if dry_run:
            logger.info(
                "[DRY RUN] Would insert %d fact entities for fact %s", len(records), news_fact_id
            )
            return len(records)

        response = self.client.table("news_fact_entities").insert(records).execute()
        return len(getattr(response, "data", []) or records)

    def update_article_metrics(
        self,
        *,
        news_url_id: str,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """Compute and persist article-level metrics for downstream flows."""

        facts_response = (
            self.client.table("news_facts")
            .select("id")
            .eq("news_url_id", news_url_id)
            .execute()
        )
        fact_rows = getattr(facts_response, "data", []) or []
        fact_ids = [row["id"] for row in fact_rows]
        num_facts = len(fact_ids)

        distinct_topics = 0
        distinct_teams = 0

        if fact_ids:
            topics_response = (
                self.client.table("news_fact_topics")
                .select("canonical_topic")
                .in_("news_fact_id", fact_ids)
                .execute()
            )
            topic_rows = getattr(topics_response, "data", []) or []
            distinct_topics = len({row["canonical_topic"] for row in topic_rows if row.get("canonical_topic")})

            entities_response = (
                self.client.table("news_fact_entities")
                .select("entity_type,entity_id,team_abbr")
                .in_("news_fact_id", fact_ids)
                .execute()
            )
            team_codes = set()
            for row in getattr(entities_response, "data", []) or []:
                if row.get("entity_type") == "team" and row.get("entity_id"):
                    team_codes.add(row["entity_id"])
                elif row.get("team_abbr"):
                    team_codes.add(row["team_abbr"])
            distinct_teams = len(team_codes)

        difficulty = (
            "easy"
            if num_facts <= 50 and distinct_teams <= 3 and distinct_topics <= 3
            else "hard"
        )

        updates = {
            "facts_count": num_facts,
            "article_difficulty": difficulty,
            "knowledge_extracted_at": datetime.datetime.utcnow().isoformat(),
            "knowledge_error_count": 0,
        }

        if dry_run:
            logger.info(
                "[DRY RUN] Would update article metrics", {"news_url_id": news_url_id, **updates}
            )
            return updates

        self.client.table("news_urls").update(updates).eq("id", news_url_id).execute()
        return updates

    def increment_error(self, *, news_url_id: str, error_message: str) -> None:
        """Increment error counter for repeated failures."""

        logger.error("Knowledge extraction failed for %s: %s", news_url_id, error_message)
        response = (
            self.client.table("news_urls")
            .select("knowledge_error_count")
            .eq("id", news_url_id)
            .limit(1)
            .execute()
        )
        current = 0
        rows = getattr(response, "data", []) or []
        if rows:
            current = rows[0].get("knowledge_error_count") or 0
        self.client.table("news_urls").update({"knowledge_error_count": current + 1}).eq("id", news_url_id).execute()
