"""Fact-level knowledge extraction pipeline."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ..db.fact_reader import NewsFactReader
from ..db.knowledge_writer import KnowledgeWriter
from ..extraction.entity_extractor import EntityExtractor, ExtractedEntity
from ..extraction.topic_extractor import TopicExtractor
from ..resolution.entity_resolver import EntityResolver, ResolvedEntity

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """Extract topics and entities for stored facts and persist metrics."""

    def __init__(
        self,
        *,
        reader: Optional[NewsFactReader] = None,
        writer: Optional[KnowledgeWriter] = None,
        entity_extractor: Optional[EntityExtractor] = None,
        topic_extractor: Optional[TopicExtractor] = None,
        entity_resolver: Optional[EntityResolver] = None,
        max_topics: Optional[int] = None,
        max_entities: Optional[int] = None,
        continue_on_error: bool = True,
    ) -> None:
        self.reader = reader or NewsFactReader()
        self.writer = writer or KnowledgeWriter()
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.topic_extractor = topic_extractor or TopicExtractor()
        self.entity_resolver = entity_resolver or EntityResolver()
        self.max_topics = max_topics or 3
        self.max_entities = max_entities or 5
        self.continue_on_error = continue_on_error

    def run(
        self,
        *,
        limit: Optional[int] = None,
        dry_run: bool = False,
        retry_failed: bool = False,
        max_error_count: int = 3,
    ) -> Dict[str, int]:
        """Execute the pipeline."""

        logger.info("Starting fact-level knowledge extraction")
        urls = self.reader.get_urls_pending_extraction(
            limit=limit,
            retry_failed=retry_failed,
            max_error_count=max_error_count,
        )

        results = {
            "urls_processed": 0,
            "facts_processed": 0,
            "topics_written": 0,
            "entities_written": 0,
            "urls_with_errors": 0,
            "errors": [],
        }

        if not urls:
            logger.info("No URLs pending extraction")
            return results

        for position, row in enumerate(urls, start=1):
            news_url_id = row.get("id")
            if not news_url_id:
                logger.warning("Skipping malformed row without id: %s", row)
                continue

            logger.info("[%d/%d] Processing news_url_id=%s", position, len(urls), news_url_id)
            try:
                facts = self.reader.get_facts_for_url(str(news_url_id))
                if not facts:
                    logger.info("No facts found for news_url_id=%s", news_url_id)
                    continue

                fact_ids = [fact["id"] for fact in facts if fact.get("id")]
                existing_topics = set(self.reader.get_existing_topic_fact_ids(fact_ids))
                existing_entities = set(self.reader.get_existing_entity_fact_ids(fact_ids))

                for fact in facts:
                    fact_id = fact.get("id")
                    fact_text = (fact.get("fact_text") or "").strip()
                    if not fact_id or not fact_text:
                        continue

                    need_topics = fact_id not in existing_topics
                    need_entities = fact_id not in existing_entities

                    if not need_topics and not need_entities:
                        continue

                    logger.debug("Extracting knowledge for fact %s", fact_id)

                    topics_written = 0
                    entities_written = 0

                    if need_topics:
                        topics = self.topic_extractor.extract(
                            fact_text,
                            max_topics=self.max_topics,
                        )
                        topics_written = self.writer.write_fact_topics(
                            news_fact_id=fact_id,
                            topics=topics,
                            llm_model=self.topic_extractor.model,
                            dry_run=dry_run,
                        )

                    if need_entities:
                        extracted_entities = self.entity_extractor.extract(
                            fact_text,
                            max_entities=self.max_entities,
                        )
                        resolved_entities = self._resolve_entities(extracted_entities)
                        entities_written = self.writer.write_fact_entities(
                            news_fact_id=fact_id,
                            entities=resolved_entities,
                            llm_model=self.entity_extractor.model,
                            dry_run=dry_run,
                        )

                    results["facts_processed"] += 1
                    results["topics_written"] += topics_written
                    results["entities_written"] += entities_written

                if not dry_run:
                    self.writer.update_article_metrics(news_url_id=str(news_url_id))

                results["urls_processed"] += 1

            except Exception as exc:  # pragma: no cover - defensive logging
                error_message = f"news_url_id={news_url_id}: {exc}"
                results["urls_with_errors"] += 1
                results["errors"].append(error_message)
                self.writer.increment_error(
                    news_url_id=str(news_url_id),
                    error_message=str(exc),
                )
                logger.exception("Failed processing news_url_id=%s", news_url_id)
                if not self.continue_on_error:
                    raise

        logger.info("Knowledge extraction complete", results)
        return results

    def _resolve_entities(self, entities: List[ExtractedEntity]) -> List[ResolvedEntity]:
        """Resolve extracted entities to database identifiers."""

        resolved: List[ResolvedEntity] = []
        for entity in entities:
            try:
                resolved_entity: Optional[ResolvedEntity] = None
                if entity.entity_type == "player":
                    resolved_entity = self.entity_resolver.resolve_player(
                        entity.mention_text,
                        context=entity.context,
                        position=entity.position,
                        team_abbr=entity.team_abbr,
                        team_name=entity.team_name,
                    )
                elif entity.entity_type == "team":
                    resolved_entity = self.entity_resolver.resolve_team(
                        entity.mention_text,
                        context=entity.context,
                    )
                elif entity.entity_type == "game":
                    resolved_entity = self.entity_resolver.resolve_game(
                        entity.mention_text,
                        context=entity.context,
                    )

                if not resolved_entity:
                    continue

                resolved_entity.is_primary = entity.is_primary
                resolved_entity.rank = entity.rank
                if entity.entity_type == "player":
                    resolved_entity.position = entity.position
                    resolved_entity.team_abbr = entity.team_abbr
                    resolved_entity.team_name = entity.team_name

                resolved.append(resolved_entity)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Failed to resolve entity %s: %s", entity.mention_text, exc)
                continue

        return resolved

    def get_progress(self) -> Dict[str, int]:
        """Return simple progress stats for CLI usage."""

        return self.reader.get_progress_stats()
