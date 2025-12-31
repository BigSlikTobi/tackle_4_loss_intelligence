"""
Cloud Function entry point for story grouping.

This module provides handlers for:
1. Batch grouping stories (scheduled)
2. Handling a single story (on-demand/event-driven)
"""

import logging
import functions_framework
import uuid
from typing import Dict, Any, Optional

from src.functions.story_grouping.core.db import (
    EmbeddingReader,
    GroupWriter,
    GroupMemberWriter,
)
from src.functions.story_grouping.core.clustering import StoryGrouper

logger = logging.getLogger(__name__)


def handle_single_story(
    story_id: str,
    table_config: Optional[Dict[str, Any]] = None,
    group_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Handle grouping for a single story.

    Args:
        story_id: ID of the story to group (e.g. news_url_id or plain URL)
        table_config: Configuration for database tables. keys:
            - embedding_table: Table containing embeddings (default: facts_embeddings)
            - group_table: Table to write groups to (default: story_groups)
            - member_table: Table to write memberships to (default: story_group_members)
            - id_column: ID column in embedding table (default: id)
            - vector_column: Vector column in embedding table (default: embedding_vector)
            - grouping_key_column: Column to group by (default: news_url_id)
            - is_legacy_schema: Whether to use legacy join logic (default: True)
        group_config: Configuration for grouping logic. keys:
            - similarity_threshold: Threshold for grouping (default: 0.8)
            - days_lookback: Days to look back for context (default: 14)

    Returns:
        Dict with result containing:
            - group_id: ID of the assigned group
            - is_new_group: Whether a new group was created
            - similarity: Similarity score with group
    """
    table_config = table_config or {}
    group_config = group_config or {}
    
    # Extract config
    embedding_table = table_config.get("embedding_table", "facts_embeddings")
    group_table = table_config.get("group_table", "story_groups")
    member_table = table_config.get("member_table", "story_group_members")
    id_column = table_config.get("id_column", "id")
    vector_column = table_config.get("vector_column", "embedding_vector")
    grouping_key_column = table_config.get("grouping_key_column", "news_url_id")
    news_table = table_config.get("news_table", "news_urls")
    is_legacy_schema = table_config.get("is_legacy_schema", True)
    schema_name = table_config.get("schema_name", "public")
    
    similarity_threshold = group_config.get("similarity_threshold", 0.8)
    days_lookback = group_config.get("days_lookback", 14)
    
    logger.info(f"Handling single story: {story_id}")
    
    # Initialize components
    reader = EmbeddingReader(
        days_lookback=days_lookback,
        table_name=embedding_table,
        id_column=id_column,
        vector_column=vector_column,
        grouping_key_column=grouping_key_column,
        is_legacy_schema=is_legacy_schema,
        schema_name=schema_name
    )
    
    group_writer = GroupWriter(
        days_lookback=days_lookback,
        table_name=group_table,
        schema_name=schema_name
    )
    
    member_writer = GroupMemberWriter(
        table_name=member_table,
        schema_name=schema_name
    )
    
    grouper = StoryGrouper(similarity_threshold=similarity_threshold)
    
    try:
        # Step 1: Fetch the specific story embedding
        # Try fetching by grouping key first (default behavior)
        embeddings = reader.fetch_embeddings_by_keys([story_id])
        
        # If not found, try fetching by ID (e.g. if story_id is a UUID but grouping key is a URL)
        if not embeddings:
            logger.info(f"No embeddings found by key {story_id}, trying by ID...")
            single_embedding = reader.fetch_embedding_by_id(story_id)
            if single_embedding:
                embeddings = [single_embedding]
        
        if not embeddings:
            logger.warning(f"No embeddings found for story {story_id}")
            return {
                "success": False,
                "error": "No embeddings found",
                "story_id": story_id
            }
        
        # Step 2: Load active groups to compare against
        active_groups = group_writer.get_active_groups()
        grouper.load_existing_groups(active_groups)
        
        # Step 3: Run grouping for this story (and its facts)
        results = []
        for embedding in embeddings:
            # 3a. Resolve member identifier (UUID) if needed
            member_fk_value = embedding["news_url_id"]
            if grouping_key_column == "url":
                try:
                    url_lookup = (
                        reader.client.schema("public")
                        .table(news_table)
                        .select("id")
                        .eq("url", embedding["news_url_id"])
                        .execute()
                    )
                    
                    if url_lookup.data and len(url_lookup.data) > 0:
                        member_fk_value = url_lookup.data[0]["id"]
                    else:
                        logger.warning(
                            f"Could not find UUID for URL {embedding['news_url_id']} in public.{news_table}. "
                            "Using URL as key, which may fail if column is UUID."
                        )
                except Exception as look_err:
                     logger.error(f"Error looking up UUID: {look_err}")

            # 3b. Check if already grouped
            existing_memberships = member_writer.get_memberships_by_news_url_id(member_fk_value)
            if existing_memberships:
                # Already grouped! Return existing info.
                existing = existing_memberships[0]
                logger.info(f"Story {story_id} ({member_fk_value}) already in group {existing['group_id']}")
                results.append({
                    "group_id": existing["group_id"],
                    "is_new_group": False,
                    "similarity": existing.get("similarity_score", 1.0),
                    "status": "existing"
                })
                continue

            # 3c. Run grouping
            result = grouper.assign_story(
                news_url_id=embedding["news_url_id"],
                embedding_vector=embedding["embedding_vector"],
                news_fact_id=embedding.get("news_fact_id")
            )
            
            # Step 4: Persist results immediately
            group = result.group
            
            if result.created_new_group:
                # Create the group in DB first
                group_id = group_writer.create_group(
                    centroid_embedding=group.centroid,
                    member_count=group.member_count
                )
                if group_id:
                    group.group_id = group_id
            elif result.added_to_group and group.group_id:
                # Update existing group centroid/count
                group_writer.update_group(
                    group_id=group.group_id,
                    centroid_embedding=group.centroid,
                    member_count=group.member_count
                )
            
            # Add membership
            if group.group_id:
                member_writer.add_member(
                    group_id=group.group_id,
                    news_url_id=member_fk_value,
                    similarity_score=result.similarity,
                    news_fact_id=embedding.get("news_fact_id")
                )
            
            results.append({
                "group_id": group.group_id,
                "is_new_group": result.created_new_group,
                "similarity": result.similarity,
                "status": "processed"
            })
            
        return {
            "success": True,
            "story_id": story_id,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Error handling single story: {e}")
        return {
            "success": False,
            "error": str(e),
            "story_id": story_id
        }
    
@functions_framework.http
def group_stories(request):
    """
    Cloud Function entry point for story grouping.
    
    Accepts a JSON body with:
    - story_id: str (required)
    - table_config: dict (optional)
    - group_config: dict (optional)
    """
    try:
        request_json = request.get_json(silent=True)
        
        if not request_json:
            return {"error": "Invalid JSON provided"}, 400
            
        story_id = request_json.get("story_id") or request_json.get("url")
        
        if not story_id:
            return {"error": "Missing required field: story_id or url"}, 400
            
        table_config = request_json.get("table_config")
        group_config = request_json.get("group_config")
        
        # Determine if we are handling a single story or a batch (future)
        # For now, we only support single story via HTTP
        result = handle_single_story(
            story_id=story_id,
            table_config=table_config,
            group_config=group_config
        )
        
        if result.get("success"):
            return result, 200
        else:
            return result, 500
            
    except Exception as e:
        logger.exception("Error in group_stories cloud function")
        return {"error": str(e)}, 500
