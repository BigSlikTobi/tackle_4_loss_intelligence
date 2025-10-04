"""
Pipeline for orchestrating knowledge extraction workflow.

Coordinates entity/topic extraction and database writes.
"""

import logging
import os
from typing import Dict, List, Optional

from ..db.story_reader import StoryGroupReader
from ..db.knowledge_writer import KnowledgeWriter
from ..extraction.entity_extractor import EntityExtractor, ExtractedEntity
from ..extraction.topic_extractor import TopicExtractor, ExtractedTopic
from ..resolution.entity_resolver import EntityResolver, ResolvedEntity

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """
    Orchestrates the knowledge extraction workflow.
    
    Steps:
    1. Load story groups (unextracted)
    2. Load summaries for each group
    3. Extract entities and topics from summaries
    4. Resolve entities to database IDs
    5. Write to database
    """
    
    def __init__(
        self,
        reader: Optional[StoryGroupReader] = None,
        writer: Optional[KnowledgeWriter] = None,
        entity_extractor: Optional[EntityExtractor] = None,
        topic_extractor: Optional[TopicExtractor] = None,
        entity_resolver: Optional[EntityResolver] = None,
        max_topics: Optional[int] = None,
        max_entities: Optional[int] = None,
        continue_on_error: bool = True,
    ):
        """
        Initialize the extraction pipeline.
        
        Args:
            reader: Story group reader (default: new instance)
            writer: Knowledge writer (default: new instance)
            entity_extractor: Entity extractor (default: new instance)
            topic_extractor: Topic extractor (default: new instance)
            entity_resolver: Entity resolver (default: new instance)
            max_topics: Max topics per group (default: from env or 10)
            max_entities: Max entities per group (default: from env or 20)
            continue_on_error: Whether to continue on errors
        """
        self.reader = reader or StoryGroupReader()
        self.writer = writer or KnowledgeWriter()
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.topic_extractor = topic_extractor or TopicExtractor()
        self.entity_resolver = entity_resolver or EntityResolver()
        
        self.max_topics = max_topics or int(os.getenv("MAX_TOPICS_PER_GROUP", "10"))
        self.max_entities = max_entities or int(os.getenv("MAX_ENTITIES_PER_GROUP", "20"))
        self.continue_on_error = continue_on_error
        
        logger.info(f"Initialized ExtractionPipeline "
                   f"(max_topics={self.max_topics}, max_entities={self.max_entities})")
    
    def run(
        self,
        limit: Optional[int] = None,
        dry_run: bool = False,
        retry_failed: bool = False,
        max_error_count: int = 3,
    ) -> Dict:
        """
        Run the extraction pipeline.
        
        Args:
            limit: Maximum number of groups to process (None for all)
            dry_run: If True, don't write to database
            retry_failed: If True, include failed extractions for retry
            max_error_count: Don't retry if error_count exceeds this
            
        Returns:
            Dict with results: groups_processed, topics_extracted, entities_extracted, errors
        """
        logger.info("=" * 80)
        logger.info("Starting Knowledge Extraction Pipeline")
        logger.info("=" * 80)
        
        results = {
            "groups_processed": 0,
            "topics_extracted": 0,
            "entities_extracted": 0,
            "groups_with_errors": 0,
            "errors": [],
        }
        
        try:
            # Load unextracted groups
            logger.info(f"Loading groups to process (limit: {limit or 'all'}, "
                       f"retry_failed: {retry_failed})...")
            groups = self.reader.get_unextracted_groups(
                limit=limit,
                retry_failed=retry_failed,
                max_error_count=max_error_count
            )
            
            if not groups:
                logger.info("No unextracted groups found")
                return results
            
            logger.info(f"Processing {len(groups)} story groups...")
            
            # Process each group
            for i, group in enumerate(groups, 1):
                group_id = group["id"]
                
                logger.info(f"\n[{i}/{len(groups)}] Processing group {group_id}")
                
                try:
                    # Extract knowledge for this group
                    group_results = self._process_group(group_id, dry_run)
                    
                    results["groups_processed"] += 1
                    results["topics_extracted"] += group_results["topics"]
                    results["entities_extracted"] += group_results["entities"]
                    
                except Exception as e:
                    error_msg = f"Error processing group {group_id}: {e}"
                    logger.error(error_msg, exc_info=True)
                    
                    results["groups_with_errors"] += 1
                    results["errors"].append(error_msg)
                    
                    if not self.continue_on_error:
                        raise
            
            # Log summary
            logger.info("\n" + "=" * 80)
            logger.info("Knowledge Extraction Complete")
            logger.info("=" * 80)
            logger.info(f"Groups processed: {results['groups_processed']}")
            logger.info(f"Topics extracted: {results['topics_extracted']}")
            logger.info(f"Entities extracted: {results['entities_extracted']}")
            logger.info(f"Groups with errors: {results['groups_with_errors']}")
            
            return results
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            results["errors"].append(str(e))
            return results
    
    def _process_group(self, group_id: str, dry_run: bool) -> Dict[str, int]:
        """
        Process a single story group.
        
        Args:
            group_id: UUID of the story group
            dry_run: If True, don't write to database
            
        Returns:
            Dict with counts of topics and entities extracted
        """
        # Load summaries for this group
        logger.debug(f"Loading summaries for group {group_id}")
        summaries = self.reader.get_group_summaries(group_id)
        
        if not summaries:
            logger.warning(f"No summaries found for group {group_id}")
            return {"topics": 0, "entities": 0}
        
        logger.info(f"Found {len(summaries)} summaries in group")
        
        # Combine all summary texts (for topic extraction from aggregate)
        combined_text = "\n\n".join([
            s.get("summary_text", "") for s in summaries if s.get("summary_text")
        ])
        
        if not combined_text.strip():
            logger.warning(f"No summary text found for group {group_id}")
            return {"topics": 0, "entities": 0}
        
        # Extract topics from combined text
        logger.debug("Extracting topics...")
        topics = self.topic_extractor.extract(
            combined_text,
            max_topics=self.max_topics
        )
        logger.info(f"Extracted {len(topics)} topics")
        
        # Extract entities from combined text
        logger.debug("Extracting entities...")
        extracted_entities = self.entity_extractor.extract(
            combined_text,
            max_entities=self.max_entities
        )
        logger.info(f"Extracted {len(extracted_entities)} entity mentions")
        
        # Resolve entities to database IDs
        logger.debug("Resolving entities to database IDs...")
        resolved_entities = self._resolve_entities(extracted_entities)
        logger.info(f"Resolved {len(resolved_entities)} entities to database IDs")
        
        # Write to database
        if topics or resolved_entities:
            write_results = self.writer.write_knowledge(
                story_group_id=group_id,
                topics=topics,
                entities=resolved_entities,
                dry_run=dry_run
            )
            
            logger.info(f"Wrote {write_results['topics']} topics and "
                       f"{write_results['entities']} entities")
            
            return write_results
        else:
            logger.warning(f"No knowledge extracted for group {group_id}")
            return {"topics": 0, "entities": 0}
    
    def _resolve_entities(
        self,
        extracted_entities: List[ExtractedEntity]
    ) -> List[ResolvedEntity]:
        """
        Resolve extracted entities to database IDs.
        
        Args:
            extracted_entities: List of ExtractedEntity instances
            
        Returns:
            List of ResolvedEntity instances
        """
        resolved = []
        
        for entity in extracted_entities:
            try:
                resolved_entity = None
                
                if entity.entity_type == "player":
                    resolved_entity = self.entity_resolver.resolve_player(
                        entity.mention_text,
                        context=entity.context
                    )
                elif entity.entity_type == "team":
                    resolved_entity = self.entity_resolver.resolve_team(
                        entity.mention_text,
                        context=entity.context
                    )
                elif entity.entity_type == "game":
                    resolved_entity = self.entity_resolver.resolve_game(
                        entity.mention_text,
                        context=entity.context
                    )
                
                if resolved_entity:
                    # Preserve is_primary from extraction
                    resolved_entity.is_primary = entity.is_primary
                    resolved.append(resolved_entity)
                else:
                    logger.debug(f"Could not resolve {entity.entity_type}: {entity.mention_text}")
                    
            except Exception as e:
                logger.warning(f"Error resolving entity {entity.mention_text}: {e}")
                continue
        
        return resolved
    
    def get_progress(self) -> Dict:
        """
        Get progress statistics.
        
        Returns:
            Dict with progress information
        """
        return self.reader.get_progress_stats()
