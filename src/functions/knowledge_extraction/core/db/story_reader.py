"""
Database reader for story groups and summaries.

Reads story groups and their associated summaries for knowledge extraction.
"""

import logging
from typing import Dict, List, Optional

from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)


class StoryGroupReader:
    """
    Reader for fetching story groups and their summaries.
    
    Provides methods to retrieve story groups that need knowledge extraction.
    """
    
    def __init__(self):
        """Initialize the story group reader."""
        self.client = get_supabase_client()
        logger.info("Initialized StoryGroupReader")
    
    def get_unextracted_groups(
        self,
        limit: Optional[int] = 100,  # Default limit to prevent timeout
        retry_failed: bool = False,
        max_error_count: int = 3
    ) -> List[Dict]:
        """
        Get story groups that need knowledge extraction.
        
        Args:
            limit: Maximum number of groups to return (default: 100)
            retry_failed: If True, include failed extractions for retry
            max_error_count: Don't retry if error_count exceeds this
            
        Returns:
            List of story group records (with only 'id' field)
        """
        try:
            logger.info(f"Fetching story groups that need extraction (limit: {limit})...")
            
            # Get all group IDs that are already completed or should be skipped
            excluded_group_ids = set()
            page_size = 1000
            offset = 0
            
            # Fetch completed groups to exclude
            while True:
                response = (
                    self.client.table("story_group_extraction_status")
                    .select("story_group_id")
                    .eq("status", "completed")
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                
                for row in response.data:
                    excluded_group_ids.add(row["story_group_id"])
                
                if len(response.data) < page_size:
                    break
                
                offset += page_size
            
            logger.info(f"Found {len(excluded_group_ids)} completed groups to exclude")
            
            # Get groups with failed status (conditionally exclude)
            if not retry_failed:
                offset = 0
                while True:
                    query = (
                        self.client.table("story_group_extraction_status")
                        .select("story_group_id")
                        .eq("status", "failed")
                    )
                    
                    # Only exclude if error count exceeds threshold
                    if max_error_count:
                        query = query.gt("error_count", max_error_count)
                    
                    response = query.range(offset, offset + page_size - 1).execute()
                    
                    for row in response.data:
                        excluded_group_ids.add(row["story_group_id"])
                    
                    if len(response.data) < page_size:
                        break
                    
                    offset += page_size
                
                logger.info(f"Total {len(excluded_group_ids)} groups excluded (completed + over-failed)")
            
            # Now fetch unextracted groups efficiently
            # Only select 'id' column since that's all we need
            unextracted_groups = []
            fetch_limit = limit * 3 if limit else 1000  # Fetch extra to account for filtering
            offset = 0
            
            while len(unextracted_groups) < (limit or float('inf')):
                batch_size = min(page_size, fetch_limit - offset)
                if batch_size <= 0:
                    break
                
                response = (
                    self.client.table("story_groups")
                    .select("id")  # Only fetch id column
                    .eq("status", "active")
                    .order("created_at", desc=True)
                    .range(offset, offset + batch_size - 1)
                    .execute()
                )
                
                for group in response.data:
                    group_id = group["id"]
                    
                    # Include if not in excluded set
                    if group_id not in excluded_group_ids:
                        unextracted_groups.append(group)
                        
                        # Stop if we hit the limit
                        if limit and len(unextracted_groups) >= limit:
                            break
                
                if limit and len(unextracted_groups) >= limit:
                    break
                
                if len(response.data) < batch_size:
                    break
                
                offset += batch_size
            
            logger.info(f"Found {len(unextracted_groups)} groups needing extraction")
            return unextracted_groups[:limit] if limit else unextracted_groups
            
        except Exception as e:
            logger.error(f"Failed to fetch unextracted groups: {e}", exc_info=True)
            return []
    
    def get_group_summaries(self, story_group_id: str) -> List[Dict]:
        """
        Get all summaries for stories in a group.
        
        Args:
            story_group_id: UUID of the story group
            
        Returns:
            List of summary records
        """
        try:
            # Get all news_url_ids in this group
            members_response = (
                self.client.table("story_group_members")
                .select("news_url_id")
                .eq("group_id", story_group_id)
                .execute()
            )
            
            news_url_ids = [row["news_url_id"] for row in members_response.data]
            
            if not news_url_ids:
                logger.warning(f"No members found for group {story_group_id}")
                return []
            
            # Get summaries for those URLs (with pagination)
            summaries = []
            page_size = 1000
            
            # Process in batches to avoid query limits
            for i in range(0, len(news_url_ids), page_size):
                batch_ids = news_url_ids[i:i + page_size]
                
                response = (
                    self.client.table("context_summaries")
                    .select("*")
                    .in_("news_url_id", batch_ids)
                    .execute()
                )
                
                summaries.extend(response.data)
            
            logger.info(f"Fetched {len(summaries)} summaries for group {story_group_id}")
            return summaries
            
        except Exception as e:
            logger.error(f"Failed to fetch summaries for group {story_group_id}: {e}", 
                        exc_info=True)
            return []
    
    def get_group_with_summaries(self, story_group_id: str) -> Optional[Dict]:
        """
        Get a story group with all its summaries.
        
        Args:
            story_group_id: UUID of the story group
            
        Returns:
            Dict with 'group' and 'summaries' keys, or None if not found
        """
        try:
            # Get group
            group_response = (
                self.client.table("story_groups")
                .select("*")
                .eq("id", story_group_id)
                .execute()
            )
            
            if not group_response.data:
                logger.warning(f"Group not found: {story_group_id}")
                return None
            
            group = group_response.data[0]
            
            # Get summaries
            summaries = self.get_group_summaries(story_group_id)
            
            return {
                "group": group,
                "summaries": summaries,
            }
            
        except Exception as e:
            logger.error(f"Failed to fetch group with summaries: {e}", exc_info=True)
            return None
    
    def get_progress_stats(self) -> Dict:
        """
        Get statistics about knowledge extraction progress.
        
        Returns:
            Dict with counts of total groups, extracted groups, etc.
        """
        try:
            # Count total active groups
            total_response = (
                self.client.table("story_groups")
                .select("id", count="exact")
                .eq("status", "active")
                .execute()
            )
            total_groups = total_response.count
            
            # Get status breakdown from extraction_status table
            status_counts = {
                "completed": 0,
                "failed": 0,
                "processing": 0,
                "pending": 0,
                "partial": 0,
            }
            
            page_size = 1000
            offset = 0
            
            while True:
                response = (
                    self.client.table("story_group_extraction_status")
                    .select("status")
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                
                for row in response.data:
                    status = row.get("status", "pending")
                    status_counts[status] = status_counts.get(status, 0) + 1
                
                if len(response.data) < page_size:
                    break
                
                offset += page_size
            
            extracted_groups = status_counts["completed"]
            
            # Count total topics
            topics_response = (
                self.client.table("story_topics")
                .select("id", count="exact")
                .execute()
            )
            total_topics = topics_response.count or 0
            
            # Count total entities
            entities_response = (
                self.client.table("story_entities")
                .select("id", count="exact")
                .execute()
            )
            total_entities = entities_response.count or 0
            
            # Groups with status record
            total_with_status = sum(status_counts.values())
            
            return {
                "total_groups": total_groups,
                "extracted_groups": extracted_groups,
                "remaining_groups": total_groups - total_with_status,
                "failed_groups": status_counts["failed"],
                "processing_groups": status_counts["processing"],
                "partial_groups": status_counts["partial"],
                "total_topics": total_topics,
                "total_entities": total_entities,
                "avg_topics_per_group": (
                    round(total_topics / extracted_groups, 1) 
                    if extracted_groups > 0 else 0
                ),
                "avg_entities_per_group": (
                    round(total_entities / extracted_groups, 1) 
                    if extracted_groups > 0 else 0
                ),
            }
            
        except Exception as e:
            logger.error(f"Failed to get progress stats: {e}", exc_info=True)
            return {}
