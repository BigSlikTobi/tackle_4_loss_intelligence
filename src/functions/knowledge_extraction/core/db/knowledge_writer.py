"""Database writer for extracted knowledge (topics and entities).

Writes topics and resolved entities to the database.
"""

import datetime
import logging
from typing import Dict, List

from src.shared.db.connection import get_supabase_client
from ..extraction.topic_extractor import ExtractedTopic
from ..resolution.entity_resolver import ResolvedEntity

logger = logging.getLogger(__name__)


class KnowledgeWriter:
    """
    Writer for saving extracted topics and entities.
    
    Handles batch writes and conflict resolution.
    """
    
    def __init__(self):
        """Initialize the knowledge writer."""
        self.client = get_supabase_client()
        logger.info("Initialized KnowledgeWriter")
    
    def write_topics(
        self,
        story_group_id: str,
        topics: List[ExtractedTopic],
        dry_run: bool = False
    ) -> int:
        """
        Write topics for a story group.
        
        Args:
            story_group_id: UUID of the story group
            topics: List of ExtractedTopic instances
            dry_run: If True, don't actually write to database
            
        Returns:
            Number of topics written
        """
        if not topics:
            logger.debug(f"No topics to write for group {story_group_id}")
            return 0
        
        try:
            # Deduplicate topics by normalized text
            # Keep the one with highest confidence
            seen = {}
            for topic in topics:
                normalized_topic = topic.topic.lower().strip()
                
                if normalized_topic not in seen:
                    seen[normalized_topic] = topic
                else:
                    # Keep the one with higher confidence
                    existing = seen[normalized_topic]
                    if topic.confidence and existing.confidence:
                        if topic.confidence > existing.confidence:
                            seen[normalized_topic] = topic
                    elif topic.confidence:
                        seen[normalized_topic] = topic
            
            # Prepare records from deduplicated topics
            records = []
            for normalized_topic, topic in seen.items():
                record = {
                    "story_group_id": story_group_id,
                    "topic": normalized_topic,
                    "confidence": topic.confidence,
                }
                records.append(record)
            
            if len(seen) < len(topics):
                logger.info(
                    f"Deduplicated {len(topics)} topics to {len(seen)} "
                    f"for group {story_group_id}"
                )
            
            if dry_run:
                logger.info(f"[DRY RUN] Would write {len(records)} topics for group {story_group_id}")
                return len(records)
            
            # Use upsert to avoid duplicates
            response = (
                self.client.table("story_topics")
                .upsert(records, on_conflict="story_group_id,topic")
                .execute()
            )
            
            written_count = len(response.data) if response.data else 0
            logger.info(f"Wrote {written_count} topics for group {story_group_id}")
            return written_count
            
        except Exception as e:
            logger.error(f"Failed to write topics for group {story_group_id}: {e}", 
                        exc_info=True)
            return 0
    
    def write_entities(
        self,
        story_group_id: str,
        entities: List[ResolvedEntity],
        dry_run: bool = False
    ) -> int:
        """
        Write resolved entities for a story group.
        
        Args:
            story_group_id: UUID of the story group
            entities: List of ResolvedEntity instances
            dry_run: If True, don't actually write to database
            
        Returns:
            Number of entities written
        """
        if not entities:
            logger.debug(f"No entities to write for group {story_group_id}")
            return 0
        
        try:
            # Deduplicate entities by (entity_type, entity_id)
            # Keep the one with highest confidence or marked as primary
            seen = {}
            for entity in entities:
                key = (entity.entity_type, entity.entity_id)
                
                if key not in seen:
                    seen[key] = entity
                else:
                    # Keep the better one (primary first, then highest confidence)
                    existing = seen[key]
                    if entity.is_primary and not existing.is_primary:
                        seen[key] = entity
                    elif entity.is_primary == existing.is_primary:
                        # Both same primary status, use confidence
                        if entity.confidence and existing.confidence:
                            if entity.confidence > existing.confidence:
                                seen[key] = entity
                        elif entity.confidence:
                            seen[key] = entity
            
            # Prepare records from deduplicated entities
            records = []
            for entity in seen.values():
                record = {
                    "story_group_id": story_group_id,
                    "entity_type": entity.entity_type,
                    "entity_id": entity.entity_id,
                    "mention_text": entity.mention_text,
                    "confidence": entity.confidence,
                    "is_primary": entity.is_primary,
                }
                records.append(record)
            
            if len(seen) < len(entities):
                logger.info(
                    f"Deduplicated {len(entities)} entities to {len(seen)} "
                    f"for group {story_group_id}"
                )
            
            if dry_run:
                logger.info(f"[DRY RUN] Would write {len(records)} entities for group {story_group_id}")
                return len(records)
            
            # Use upsert to avoid duplicates
            response = (
                self.client.table("story_entities")
                .upsert(records, on_conflict="story_group_id,entity_type,entity_id")
                .execute()
            )
            
            written_count = len(response.data) if response.data else 0
            logger.info(f"Wrote {written_count} entities for group {story_group_id}")
            return written_count
            
        except Exception as e:
            logger.error(f"Failed to write entities for group {story_group_id}: {e}", 
                        exc_info=True)
            return 0
    
    def write_knowledge(
        self,
        story_group_id: str,
        topics: List[ExtractedTopic],
        entities: List[ResolvedEntity],
        dry_run: bool = False
    ) -> Dict[str, int]:
        """
        Write both topics and entities for a story group.
        Also updates extraction status tracking.
        
        Args:
            story_group_id: UUID of the story group
            topics: List of ExtractedTopic instances
            entities: List of ResolvedEntity instances
            dry_run: If True, don't actually write to database
            
        Returns:
            Dict with 'topics' and 'entities' counts
        """
        if not dry_run:
            # Mark as processing
            self._update_status(story_group_id, "processing", started_at=True)
        
        try:
            topics_written = self.write_topics(story_group_id, topics, dry_run)
            entities_written = self.write_entities(story_group_id, entities, dry_run)
            
            if not dry_run:
                # Determine final status
                if topics_written > 0 or entities_written > 0:
                    status = "completed"
                else:
                    status = "partial"
                
                # Mark as completed
                self._update_status(
                    story_group_id,
                    status,
                    topics_count=topics_written,
                    entities_count=entities_written,
                    completed_at=True
                )
            
            return {
                "topics": topics_written,
                "entities": entities_written,
            }
        
        except Exception as e:
            if not dry_run:
                # Mark as failed
                self._update_status(
                    story_group_id,
                    "failed",
                    error_message=str(e)
                )
            raise
    
    def clear_group_knowledge(
        self,
        story_group_id: str,
        dry_run: bool = False
    ) -> Dict[str, int]:
        """
        Clear all topics and entities for a story group.
        Also resets extraction status to pending.
        
        Useful for reprocessing a group.
        
        Args:
            story_group_id: UUID of the story group
            dry_run: If True, don't actually delete
            
        Returns:
            Dict with counts of deleted topics and entities
        """
        try:
            if dry_run:
                # Count what would be deleted
                topics_response = (
                    self.client.table("story_topics")
                    .select("id", count="exact")
                    .eq("story_group_id", story_group_id)
                    .execute()
                )
                
                entities_response = (
                    self.client.table("story_entities")
                    .select("id", count="exact")
                    .eq("story_group_id", story_group_id)
                    .execute()
                )
                
                logger.info(f"[DRY RUN] Would delete {topics_response.count} topics "
                           f"and {entities_response.count} entities for group {story_group_id}")
                
                return {
                    "topics": topics_response.count or 0,
                    "entities": entities_response.count or 0,
                }
            
            # Delete topics
            topics_response = (
                self.client.table("story_topics")
                .delete()
                .eq("story_group_id", story_group_id)
                .execute()
            )
            topics_deleted = len(topics_response.data) if topics_response.data else 0
            
            # Delete entities
            entities_response = (
                self.client.table("story_entities")
                .delete()
                .eq("story_group_id", story_group_id)
                .execute()
            )
            entities_deleted = len(entities_response.data) if entities_response.data else 0
            
            # Reset extraction status to pending
            self._update_status(story_group_id, "pending", topics_count=0, entities_count=0)
            
            logger.info(f"Cleared {topics_deleted} topics and {entities_deleted} entities "
                       f"for group {story_group_id}")
            
            return {
                "topics": topics_deleted,
                "entities": entities_deleted,
            }
            
        except Exception as e:
            logger.error(f"Failed to clear knowledge for group {story_group_id}: {e}", 
                        exc_info=True)
            return {"topics": 0, "entities": 0}
    
    def _update_status(
        self,
        story_group_id: str,
        status: str,
        topics_count: int = None,
        entities_count: int = None,
        error_message: str = None,
        started_at: bool = False,
        completed_at: bool = False
    ):
        """
        Update extraction status for a story group.
        
        Args:
            story_group_id: UUID of the story group
            status: Status value (pending, processing, completed, failed, partial)
            topics_count: Number of topics extracted
            entities_count: Number of entities extracted
            error_message: Error message if failed
            started_at: If True, set started_at timestamp
            completed_at: If True, set completed_at timestamp
        """
        try:
            record = {
                "story_group_id": story_group_id,
                "status": status,
                "last_attempt_at": datetime.datetime.utcnow().isoformat(),
            }
            
            if topics_count is not None:
                record["topics_extracted"] = topics_count
            
            if entities_count is not None:
                record["entities_extracted"] = entities_count
            
            if error_message:
                record["error_message"] = error_message[:1000]  # Limit error message length
                # Increment error count
                existing = (
                    self.client.table("story_group_extraction_status")
                    .select("error_count")
                    .eq("story_group_id", story_group_id)
                    .execute()
                )
                if existing.data:
                    record["error_count"] = (existing.data[0].get("error_count", 0) or 0) + 1
                else:
                    record["error_count"] = 1
            
            if started_at:
                record["started_at"] = datetime.datetime.utcnow().isoformat()
            
            if completed_at:
                record["completed_at"] = datetime.datetime.utcnow().isoformat()
            
            # Upsert status record
            self.client.table("story_group_extraction_status").upsert(
                record,
                on_conflict="story_group_id"
            ).execute()
            
            logger.debug(f"Updated extraction status for {story_group_id}: {status}")
            
        except Exception as e:
            logger.warning(f"Failed to update extraction status: {e}")
            # Don't fail the main operation if status update fails
