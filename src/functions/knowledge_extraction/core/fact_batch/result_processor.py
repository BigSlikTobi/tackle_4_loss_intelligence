"""Process fact-level batch outputs and persist topics/entities."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from ..db.knowledge_writer import KnowledgeWriter
from ..db.fact_reader import NewsFactReader
from ..extraction.entity_extractor import ExtractedEntity
from ..extraction.topic_extractor import (
    ExtractedTopic,
    TOPIC_CATEGORY_LOOKUP,
    normalize_topic_category,
)
from ..resolution.entity_resolver import EntityResolver, ResolvedEntity
from .request_generator import KnowledgeTask

logger = logging.getLogger(__name__)


@dataclass
class FactBatchResult:
    """Summary of processing a fact batch output file."""

    facts_processed: int = 0
    topics_written: int = 0
    entities_written: int = 0
    facts_in_output: int = 0
    facts_skipped_missing: int = 0
    facts_skipped_existing: int = 0
    facts_skipped_no_data: int = 0
    urls_updated: int = 0
    errors: List[str] = None
    missing_fact_ids: List[str] = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []
        if self.missing_fact_ids is None:
            self.missing_fact_ids = []


class FactBatchResultProcessor:
    """Parse batch output lines and write fact knowledge to the database."""

    def __init__(
        self,
        *,
        writer: Optional[KnowledgeWriter] = None,
        resolver: Optional[EntityResolver] = None,
        reader: Optional[NewsFactReader] = None,
        continue_on_error: bool = True,
    ) -> None:
        self.writer = writer or KnowledgeWriter()
        self.resolver = resolver or EntityResolver()
        self.reader = reader or NewsFactReader()
        self.continue_on_error = continue_on_error
        logger.info("Initialized FactBatchResultProcessor")

    def process(
        self,
        output_file: Path,
        *,
        task: KnowledgeTask,
        dry_run: bool = False,
        skip_existing: bool = False,
    ) -> FactBatchResult:
        """Process a downloaded batch output file."""
        if not output_file.exists():
            raise FileNotFoundError(f"Output file not found: {output_file}")

        result = FactBatchResult()
        pending_topics: List[Dict] = []
        pending_entities: List[Dict] = []
        facts_with_writes: set[str] = set()
        processed_fact_ids: Set[str] = set()  # Track all fact IDs we processed

        with output_file.open("r") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    msg = f"Invalid JSON on line {line_number}: {exc}"
                    logger.error(msg)
                    result.errors.append(msg)
                    if not self.continue_on_error:
                        raise
                    continue

                custom_id = record.get("custom_id")
                error = record.get("error")
                response = record.get("response") or {}

                if error:
                    msg = f"Batch request {custom_id} failed: {error}"
                    logger.error(msg)
                    result.errors.append(msg)
                    if not self.continue_on_error:
                        raise RuntimeError(msg)
                    continue

                if response.get("status_code") != 200:
                    msg = f"Non-200 response for {custom_id}: {response}"
                    logger.error(msg)
                    result.errors.append(msg)
                    if not self.continue_on_error:
                        raise RuntimeError(msg)
                    continue

                body = response.get("body") or {}
                model = body.get("model") or "unknown"
                output_text = self._extract_output_text(body)
                if not output_text:
                    logger.warning("No output text for %s", custom_id)
                    continue

                parsed_rows = self._parse_payload(output_text, task, custom_id)
                if not parsed_rows:
                    logger.warning("No rows parsed for %s", custom_id)
                    continue

                fact_ids = [row.get("news_fact_id") for row in parsed_rows if row.get("news_fact_id")]
                if not fact_ids:
                    continue

                result.facts_in_output += len(fact_ids)
                
                # Track all fact IDs for URL timestamp updates
                processed_fact_ids.update(fact_ids)

                # Filter out fact_ids that don't exist to avoid FK errors
                existing_fact_ids = set(self.reader.filter_existing_fact_ids(fact_ids))
                missing_ids = set(fact_ids) - existing_fact_ids
                if missing_ids:
                    result.missing_fact_ids.extend(sorted(missing_ids))
                    result.facts_skipped_missing += len(missing_ids)
                if not existing_fact_ids:
                    logger.warning("No existing fact ids found in batch chunk for %s", custom_id)
                    continue

                if skip_existing:
                    if task == "topics":
                        existing_ids = set(self.reader.get_existing_topic_fact_ids(existing_fact_ids))
                    else:
                        existing_ids = set(self.reader.get_existing_entity_fact_ids(existing_fact_ids))
                    if existing_ids:
                        result.facts_skipped_existing += len(existing_ids)
                else:
                    existing_ids = set()

                for row in parsed_rows:
                    fact_id = row.get("news_fact_id")
                    if not fact_id:
                        logger.warning("Skipping row without news_fact_id in %s", custom_id)
                        continue
                    if fact_id not in existing_fact_ids:
                        # Already counted in facts_skipped_missing
                        continue
                    if fact_id in existing_ids:
                        logger.debug("Skipping existing %s row for fact %s", task, fact_id)
                        continue

                    if task == "topics":
                        topics = self._parse_topics(row)
                        if topics:
                            pending_topics.append(
                                {"news_fact_id": fact_id, "topics": topics, "llm_model": model}
                            )
                            facts_with_writes.add(fact_id)
                        else:
                            # Mark fact as processed with no topics found
                            pending_topics.append({
                                "news_fact_id": fact_id,
                                "topics": [ExtractedTopic(topic="NO_TOPICS_FOUND", confidence=1.0, rank=1)],
                                "llm_model": model
                            })
                            facts_with_writes.add(fact_id)
                            result.facts_skipped_no_data += 1
                    else:
                        entities = self._parse_entities(row)
                        resolved = self._resolve_entities(entities)
                        if resolved:
                            pending_entities.append(
                                {"news_fact_id": fact_id, "entities": resolved, "llm_model": model}
                            )
                            facts_with_writes.add(fact_id)
                        else:
                            # Mark fact as processed with no entities found
                            # This creates a marker record so the fact won't be reprocessed
                            no_entity_marker = ResolvedEntity(
                                entity_type="none",
                                entity_id="NO_ENTITIES_FOUND",
                                mention_text="[no entities extracted]",
                                matched_name="[no entities extracted]",
                                confidence=0.0,  # Zero confidence indicates marker
                            )
                            pending_entities.append({
                                "news_fact_id": fact_id,
                                "entities": [no_entity_marker],
                                "llm_model": model
                            })
                            facts_with_writes.add(fact_id)
                            result.facts_skipped_no_data += 1

        # Bulk writes
        if pending_topics:
            written = self.writer.write_fact_topics_bulk(
                pending_topics,
                dry_run=dry_run,
            )
            result.topics_written += written

        if pending_entities:
            written = self.writer.write_fact_entities_bulk(
                pending_entities,
                dry_run=dry_run,
            )
            result.entities_written += written

        result.facts_processed += len(facts_with_writes)

        # Update knowledge_extracted_at on URLs that had facts processed
        if processed_fact_ids and not dry_run:
            urls_updated = self._update_url_timestamps(processed_fact_ids, task)
            result.urls_updated = urls_updated
        elif dry_run and processed_fact_ids:
            logger.info("[DRY RUN] Would update knowledge_extracted_at on URLs for %d processed facts", len(processed_fact_ids))

        return result

    def _update_url_timestamps(self, fact_ids: Set[str], task: str) -> int:
        """Update knowledge_extracted_at on news_urls for processed facts.
        
        This marks the URL as having completed knowledge extraction so it
        won't be picked up again by future batch runs.
        """
        if not fact_ids:
            return 0
        
        try:
            from src.shared.db.connection import get_supabase_client
            client = get_supabase_client()
            
            # Get distinct news_url_ids for the processed facts
            # Process in chunks to avoid query size limits
            fact_id_list = list(fact_ids)
            url_ids: Set[str] = set()
            
            chunk_size = 500
            for i in range(0, len(fact_id_list), chunk_size):
                chunk = fact_id_list[i:i + chunk_size]
                response = (
                    client.table("news_facts")
                    .select("news_url_id")
                    .in_("id", chunk)
                    .execute()
                )
                rows = getattr(response, "data", []) or []
                for row in rows:
                    if row.get("news_url_id"):
                        url_ids.add(row["news_url_id"])
            
            if not url_ids:
                logger.warning("No news_url_ids found for %d processed facts", len(fact_ids))
                return 0
            
            # Update knowledge_extracted_at for each URL
            timestamp = datetime.now(timezone.utc).isoformat()
            updated_count = 0
            
            for url_id in url_ids:
                try:
                    client.table("news_urls").update({
                        "knowledge_extracted_at": timestamp,
                        "knowledge_error_count": 0,
                    }).eq("id", url_id).execute()
                    updated_count += 1
                except Exception as exc:
                    logger.warning("Failed to update knowledge_extracted_at for URL %s: %s", url_id, exc)
            
            logger.info(
                "Updated knowledge_extracted_at for %d URLs (%s task, %d facts)",
                updated_count,
                task,
                len(fact_ids),
            )
            return updated_count
            
        except Exception as exc:
            logger.error("Failed to update URL timestamps: %s", exc, exc_info=True)
            return 0

    def _extract_output_text(self, body: Dict) -> str:
        """Pull the text payload from chat completion style bodies."""
        choices = body.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        return part.get("text", "")
        # Fallbacks used by other payload shapes
        if "output_text" in body:
            return body.get("output_text") or ""
        if "output" in body and isinstance(body["output"], list):
            for output_item in body["output"]:
                if output_item.get("type") == "message":
                    for content_item in output_item.get("content", []) or []:
                        if content_item.get("type") == "output_text":
                            return content_item.get("text", "")
        return ""

    def _parse_payload(self, output_text: str, task: KnowledgeTask, custom_id: str) -> List[Dict]:
        """Parse the model response into a list of rows."""
        payload: Optional[Sequence] = None
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError:
            # Try to recover JSON array from within text
            start = output_text.find("[")
            end = output_text.rfind("]") + 1
            if start != -1 and end > start:
                try:
                    payload = json.loads(output_text[start:end])
                except json.JSONDecodeError:
                    logger.error("Failed to parse JSON array for %s", custom_id)
                    return []
            else:
                logger.error("No JSON array found for %s", custom_id)
                return []

        if not payload:
            return []

        if isinstance(payload, dict):
            # Some models may wrap results in a dict
            payload = payload.get("results") or payload.get("data") or []

        if not isinstance(payload, list):
            logger.warning("Unexpected payload type for %s: %s", custom_id, type(payload))
            return []

        rows: List[Dict] = []
        for item in payload:
            if not isinstance(item, dict):
                logger.debug("Skipping non-dict item in %s payload", custom_id)
                continue
            # Normalize possible single-field names
            if task == "topics" and "topic" in item and "topics" not in item:
                item["topics"] = [item["topic"]]
            rows.append(item)
        return rows

    def _parse_topics(self, row: Dict) -> List[ExtractedTopic]:
        topics_raw = row.get("topics") or []
        if isinstance(topics_raw, str):
            topics_raw = [topics_raw]

        topics: List[ExtractedTopic] = []
        for index, topic in enumerate(topics_raw, 1):
            if isinstance(topic, dict):
                topic_text = (topic.get("topic") or topic.get("text") or "").strip()
                confidence = topic.get("confidence")
                rank = topic.get("rank", index)
            else:
                topic_text = str(topic).strip()
                confidence = None
                rank = index

            if not topic_text:
                continue

            normalized_key = normalize_topic_category(topic_text)
            canonical_topic = TOPIC_CATEGORY_LOOKUP.get(normalized_key)
            if not canonical_topic:
                logger.debug("Skipping topic outside allowed categories: %s", topic_text)
                continue

            topics.append(ExtractedTopic(topic=canonical_topic, confidence=confidence, rank=rank))

        return topics

    def _parse_entities(self, row: Dict) -> List[ExtractedEntity]:
        entities_raw = row.get("entities") or []
        entities: List[ExtractedEntity] = []

        for entity in entities_raw:
            if not isinstance(entity, dict):
                continue

            entity_type = entity.get("entity_type") or entity.get("type") or ""
            mention_text = entity.get("mention_text") or entity.get("name") or ""
            if not entity_type or not mention_text:
                continue
            entity_type = entity_type.lower()
            if entity_type not in {"player", "team", "game"}:
                logger.debug("Skipping unsupported entity type: %s", entity_type)
                continue

            cleaned_mention = mention_text.strip()
            lower = cleaned_mention.lower()
            for prefix in ("player:", "players:", "team:", "teams:", "game:", "matchup:"):
                if lower.startswith(prefix):
                    cleaned_mention = cleaned_mention[len(prefix):].strip()
                    lower = cleaned_mention.lower()
                    break
            if not cleaned_mention:
                continue

            entities.append(
                ExtractedEntity(
                    entity_type=entity_type,
                    mention_text=cleaned_mention,
                    context=entity.get("context"),
                    confidence=entity.get("confidence"),
                    is_primary=entity.get("is_primary", False),
                    rank=entity.get("rank"),
                    position=entity.get("position"),
                    team_abbr=entity.get("team_abbr"),
                    team_name=entity.get("team_name"),
                )
            )

        return entities

    def _resolve_entities(self, extracted_entities: List[ExtractedEntity]) -> List[ResolvedEntity]:
        # Mentions to reject (not NFL-related or too generic)
        REJECTED_MENTIONS = {
            "nfl", "league", "football", "sports", "espn", "fox", "cbs", "nbc",
            "museum", "hall of fame", "super bowl",  # Generic terms
        }
        
        # Non-NFL team patterns (colleges, other sports leagues)
        NON_NFL_PATTERNS = [
            "tech", "college", "university", "state", "tigers", "blue jays",
            "yankees", "red sox", "dodgers", "cubs", "mets", "braves",  # MLB
            "lakers", "celtics", "warriors", "heat", "knicks", "bulls",  # NBA
            "bruins", "penguins", "blackhawks", "rangers", "maple leafs",  # NHL
            "barcelona", "madrid", "manchester", "liverpool", "arsenal",  # Soccer
            "motors", "racing", "nascar",  # Racing
            "notre dame", "alabama", "ohio state", "michigan", "clemson",  # College
            "georgia", "lsu", "texas", "oklahoma", "usc", "oregon",  # More college
            "syracuse", "boston college", "miami hurricanes", "florida state",
        ]
        
        resolved: List[ResolvedEntity] = []
        for entity in extracted_entities:
            mention_lower = entity.mention_text.lower().strip()
            
            # Skip rejected mentions
            if mention_lower in REJECTED_MENTIONS:
                logger.debug("Skipping rejected mention: %s", entity.mention_text)
                continue
            
            # Skip non-NFL patterns for team entities
            if entity.entity_type == "team":
                skip = False
                for pattern in NON_NFL_PATTERNS:
                    if pattern in mention_lower:
                        logger.debug("Skipping non-NFL team pattern '%s': %s", pattern, entity.mention_text)
                        skip = True
                        break
                if skip:
                    continue
            
            try:
                resolved_entity = None
                if entity.entity_type == "player":
                    resolved_entity = self.resolver.resolve_player(
                        entity.mention_text,
                        context=entity.context,
                        position=entity.position,
                        team_abbr=entity.team_abbr,
                        team_name=entity.team_name,
                    )
                    # If player not found in DB, create an unresolved entity
                    # This allows storing mentions of retired players, etc.
                    if not resolved_entity:
                        # Use normalized mention as pseudo-ID
                        pseudo_id = f"UNRESOLVED:{mention_lower.replace(' ', '_')}"
                        resolved_entity = ResolvedEntity(
                            entity_type="player",
                            entity_id=pseudo_id,
                            mention_text=entity.mention_text,
                            matched_name=entity.mention_text,  # No canonical match
                            confidence=0.0,  # Zero confidence = unresolved
                        )
                        logger.debug("Created unresolved player entity: %s -> %s", entity.mention_text, pseudo_id)
                        
                elif entity.entity_type == "team":
                    resolved_entity = self.resolver.resolve_team(
                        entity.mention_text,
                        context=entity.context,
                    )
                elif entity.entity_type == "game":
                    resolved_entity = self.resolver.resolve_game(
                        entity.mention_text,
                        context=entity.context,
                    )

                if resolved_entity:
                    resolved_entity.is_primary = entity.is_primary
                    resolved_entity.rank = entity.rank
                    if entity.entity_type == "player":
                        resolved_entity.position = entity.position
                        resolved_entity.team_abbr = entity.team_abbr
                        resolved_entity.team_name = entity.team_name
                    resolved.append(resolved_entity)
            except Exception as exc:
                logger.warning("Error resolving entity %s: %s", entity.mention_text, exc)
                if not self.continue_on_error:
                    raise

        return resolved
