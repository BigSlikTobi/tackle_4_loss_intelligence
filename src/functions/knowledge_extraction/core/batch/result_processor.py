"""
Process batch API results and write to database.

Handles parsing of batch output files and writing extracted knowledge.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from ..db.knowledge_writer import KnowledgeWriter
from ..extraction.entity_extractor import ExtractedEntity
from ..extraction.topic_extractor import (
    ExtractedTopic,
    TOPIC_CATEGORY_LOOKUP,
    normalize_topic_category,
)
from ..resolution.entity_resolver import EntityResolver, ResolvedEntity

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result of processing a batch output file."""
    
    groups_processed: int = 0
    topics_extracted: int = 0
    entities_extracted: int = 0
    groups_with_errors: int = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class BatchResultProcessor:
    """
    Processes batch API output files and writes to database.
    
    Handles:
    - Parsing batch output .jsonl files
    - Extracting topics and entities from responses
    - Resolving entities to database IDs
    - Writing to database with error handling
    """
    
    def __init__(
        self,
        writer: Optional[KnowledgeWriter] = None,
        entity_resolver: Optional[EntityResolver] = None,
        continue_on_error: bool = True,
    ):
        """
        Initialize the batch result processor.
        
        Args:
            writer: Knowledge writer (default: new instance)
            entity_resolver: Entity resolver (default: new instance)
            continue_on_error: Whether to continue on errors
        """
        self.writer = writer or KnowledgeWriter()
        self.entity_resolver = entity_resolver or EntityResolver()
        self.continue_on_error = continue_on_error
        
        logger.info("Initialized BatchResultProcessor")
    
    def process(
        self,
        output_file: Path,
        dry_run: bool = False,
    ) -> BatchResult:
        """
        Process a batch output file and write results to database.
        
        Args:
            output_file: Path to batch output .jsonl file
            dry_run: If True, don't write to database
            
        Returns:
            BatchResult with processing statistics
        """
        logger.info("=" * 80)
        logger.info(f"Processing Batch Results: {output_file}")
        logger.info("=" * 80)
        
        if not output_file.exists():
            raise FileNotFoundError(f"Output file not found: {output_file}")
        
        result = BatchResult()
        
        # Group results by story group ID
        # We have 2 requests per group: topic_{group_id} and entity_{group_id}
        group_results = {}
        
        # Read all results from file
        logger.info("Reading batch output file...")
        with open(output_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    batch_response = json.loads(line)
                    
                    custom_id = batch_response.get("custom_id")
                    response = batch_response.get("response")
                    error = batch_response.get("error")
                    
                    if error:
                        error_msg = f"Batch request {custom_id} failed: {error}"
                        logger.error(error_msg)
                        result.errors.append(error_msg)
                        result.groups_with_errors += 1
                        continue
                    
                    if not response or response.get("status_code") != 200:
                        error_msg = f"Invalid response for {custom_id}: {response}"
                        logger.error(error_msg)
                        result.errors.append(error_msg)
                        continue
                    
                    # Parse custom_id to get type and group_id
                    # Format: "topic_{group_id}" or "entity_{group_id}"
                    parts = custom_id.split("_", 1)
                    if len(parts) != 2:
                        logger.warning(f"Invalid custom_id format: {custom_id}")
                        continue
                    
                    request_type, group_id = parts
                    
                    # Initialize group results if needed
                    if group_id not in group_results:
                        group_results[group_id] = {
                            "topics": None,
                            "entities": None,
                            "errors": []
                        }
                    
                    # Extract response body
                    body = response.get("body", {})
                    
                    # For Responses API, the text is in output[1].content[0].text
                    # Structure: body.output -> array of [reasoning, message]
                    # message.content -> array of content items with text
                    output_text = None
                    
                    if "output" in body and isinstance(body["output"], list):
                        # Find the message output (not reasoning)
                        for output_item in body["output"]:
                            if output_item.get("type") == "message":
                                content = output_item.get("content", [])
                                if content and isinstance(content, list):
                                    for content_item in content:
                                        if content_item.get("type") == "output_text":
                                            output_text = content_item.get("text", "")
                                            break
                                if output_text:
                                    break
                    
                    # Fallback to direct output_text field (for other API formats)
                    if not output_text:
                        output_text = body.get("output_text", "")
                    
                    if not output_text:
                        logger.warning(f"No output text for {custom_id}")
                        continue
                    
                    # Parse the response based on type
                    if request_type == "topic":
                        topics = self._parse_topic_response(output_text, custom_id)
                        group_results[group_id]["topics"] = topics
                    elif request_type == "entity":
                        entities = self._parse_entity_response(output_text, custom_id)
                        group_results[group_id]["entities"] = entities
                    else:
                        logger.warning(f"Unknown request type: {request_type}")
                    
                except json.JSONDecodeError as e:
                    error_msg = f"Invalid JSON at line {line_num}: {e}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Error processing line {line_num}: {e}"
                    logger.error(error_msg, exc_info=True)
                    result.errors.append(error_msg)
        
        # Process each group's results
        logger.info(f"\nProcessing {len(group_results)} groups...")
        
        for i, (group_id, group_data) in enumerate(group_results.items(), 1):
            logger.info(f"\n[{i}/{len(group_results)}] Processing group {group_id}")
            
            try:
                topics = group_data.get("topics") or []
                extracted_entities = group_data.get("entities") or []
                
                # Resolve entities to database IDs
                logger.debug(f"Resolving {len(extracted_entities)} entities...")
                resolved_entities = self._resolve_entities(extracted_entities)
                logger.info(f"Resolved {len(resolved_entities)} entities")
                
                # Write to database
                if topics or resolved_entities:
                    write_results = self.writer.write_knowledge(
                        story_group_id=group_id,
                        topics=topics,
                        entities=resolved_entities,
                        dry_run=dry_run
                    )
                    
                    result.groups_processed += 1
                    result.topics_extracted += write_results["topics"]
                    result.entities_extracted += write_results["entities"]
                    
                    logger.info(
                        f"Wrote {write_results['topics']} topics and "
                        f"{write_results['entities']} entities"
                    )
                else:
                    logger.warning(f"No knowledge extracted for group {group_id}")
                    result.groups_with_errors += 1
                
            except Exception as e:
                error_msg = f"Error processing group {group_id}: {e}"
                logger.error(error_msg, exc_info=True)
                result.groups_with_errors += 1
                result.errors.append(error_msg)
                
                if not self.continue_on_error:
                    raise
        
        # Log summary
        logger.info("\n" + "=" * 80)
        logger.info("Batch Processing Complete")
        logger.info("=" * 80)
        logger.info(f"Groups processed: {result.groups_processed}")
        logger.info(f"Topics extracted: {result.topics_extracted}")
        logger.info(f"Entities extracted: {result.entities_extracted}")
        logger.info(f"Groups with errors: {result.groups_with_errors}")
        
        return result
    
    def _parse_topic_response(self, output_text: str, custom_id: str) -> List[ExtractedTopic]:
        """Parse topic extraction response from LLM."""
        try:
            # Try to extract JSON from response
            # LLM might include explanatory text before/after JSON
            start_idx = output_text.find("{")
            end_idx = output_text.rfind("}") + 1
            
            if start_idx == -1 or end_idx == 0:
                logger.warning(f"No JSON found in topic response for {custom_id}")
                return []
            
            json_str = output_text[start_idx:end_idx]
            data = json.loads(json_str)
            
            topics = []
            for topic_data in data.get("topics", []):
                raw_topic = topic_data.get("topic", "")
                topic_text = raw_topic.strip()
                
                if not topic_text:
                    logger.warning("Skipping empty topic entry in batch response")
                    continue
                
                normalized_key = normalize_topic_category(topic_text)
                canonical_topic = TOPIC_CATEGORY_LOOKUP.get(normalized_key)
                
                if not canonical_topic:
                    logger.warning(
                        "Skipping topic outside allowed categories in batch response: %s",
                        topic_text,
                    )
                    continue
                
                topic = ExtractedTopic(
                    topic=canonical_topic,
                    confidence=topic_data.get("confidence"),
                    rank=topic_data.get("rank"),
                )
                topics.append(topic)
            
            return topics
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse topic JSON for {custom_id}: {e}")
            logger.debug(f"Response text: {output_text[:500]}")
            return []
        except Exception as e:
            logger.error(f"Error parsing topic response for {custom_id}: {e}")
            return []
    
    def _parse_entity_response(self, output_text: str, custom_id: str) -> List[ExtractedEntity]:
        """Parse entity extraction response from LLM."""
        try:
            # Try to extract JSON from response
            # Check for both object format and array format
            start_obj = output_text.find("{")
            start_arr = output_text.find("[")
            
            # Determine which comes first
            if start_obj == -1 and start_arr == -1:
                logger.warning(f"No JSON found in entity response for {custom_id}")
                return []
            
            # Try array format first if it appears before object
            if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
                end_idx = output_text.rfind("]") + 1
                if end_idx > 0:
                    json_str = output_text[start_arr:end_idx]
                    data = json.loads(json_str)
                    # If it's already an array, use it directly
                    if isinstance(data, list):
                        entity_list = data
                    else:
                        entity_list = data.get("entities", [])
                else:
                    logger.warning(f"Invalid array JSON in entity response for {custom_id}")
                    return []
            else:
                # Try object format
                end_idx = output_text.rfind("}") + 1
                if end_idx > 0:
                    json_str = output_text[start_obj:end_idx]
                    data = json.loads(json_str)
                    # Handle both {"entities": [...]} and direct array
                    if isinstance(data, list):
                        entity_list = data
                    else:
                        entity_list = data.get("entities", [])
                else:
                    logger.warning(f"Invalid object JSON in entity response for {custom_id}")
                    return []
            
            entities = []
            for entity_data in entity_list:
                # Handle both "entity_type" and "type" fields
                entity_type = entity_data.get("entity_type") or entity_data.get("type", "")
                entity = ExtractedEntity(
                    entity_type=entity_type.lower(),
                    mention_text=entity_data.get("mention_text", "").strip(),
                    context=entity_data.get("context"),
                    confidence=entity_data.get("confidence"),
                    is_primary=entity_data.get("is_primary", False),
                    rank=entity_data.get("rank"),
                    # Player disambiguation fields
                    position=entity_data.get("position"),
                    team_abbr=entity_data.get("team_abbr"),
                    team_name=entity_data.get("team_name"),
                )
                if entity.entity_type and entity.mention_text:  # Only add valid entities
                    entities.append(entity)
            
            return entities
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse entity JSON for {custom_id}: {e}")
            logger.debug(f"Response text: {output_text[:500]}")
            return []
        except Exception as e:
            logger.error(f"Error parsing entity response for {custom_id}: {e}")
            return []
    
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
                        context=entity.context,
                        position=entity.position,
                        team_abbr=entity.team_abbr,
                        team_name=entity.team_name
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
                    # Preserve fields from extraction
                    resolved_entity.is_primary = entity.is_primary
                    resolved_entity.rank = entity.rank
                    
                    # Preserve player disambiguation fields
                    if entity.entity_type == "player":
                        resolved_entity.position = entity.position
                        resolved_entity.team_abbr = entity.team_abbr
                        resolved_entity.team_name = entity.team_name
                    
                    resolved.append(resolved_entity)
                else:
                    logger.debug(f"Could not resolve {entity.entity_type}: {entity.mention_text}")
                    
            except Exception as e:
                logger.warning(f"Error resolving entity {entity.mention_text}: {e}")
                continue
        
        return resolved
