"""Pipeline for orchestrating story grouping workflow."""

import logging
from typing import Dict, List, Optional
import os

from ..db import EmbeddingReader, GroupWriter, GroupMemberWriter
from ..clustering import StoryGrouper

logger = logging.getLogger(__name__)


class GroupingPipeline:
    """Orchestrates the story grouping workflow."""

    def __init__(
        self,
        embedding_reader: EmbeddingReader,
        group_writer: GroupWriter,
        member_writer: GroupMemberWriter,
        similarity_threshold: Optional[float] = None,
        continue_on_error: bool = True,
    ):
        """
        Initialize the grouping pipeline.
        
        Args:
            embedding_reader: Reader for story embeddings
            group_writer: Writer for story groups
            member_writer: Writer for group memberships
            similarity_threshold: Similarity threshold for grouping (default: from env or 0.85)
            continue_on_error: Whether to continue processing on errors
        """
        self.embedding_reader = embedding_reader
        self.group_writer = group_writer
        self.member_writer = member_writer
        self.continue_on_error = continue_on_error
        
        # Get threshold from parameter, env, or default
        if similarity_threshold is None:
            similarity_threshold = float(
                os.getenv("SIMILARITY_THRESHOLD", "0.8")
            )
        
        self.similarity_threshold = similarity_threshold
        self.grouper = StoryGrouper(similarity_threshold=similarity_threshold)
        
        logger.info(
            f"Initialized GroupingPipeline with threshold={similarity_threshold}"
        )

    def run(
        self,
        limit: Optional[int] = None,
        regroup: bool = False,
    ) -> Dict:
        """
        Run the grouping pipeline.
        
        Args:
            limit: Maximum number of stories to process (None for all)
            regroup: If True, clear existing groups and regroup all stories
            
        Returns:
            Dict with keys: stories_processed, groups_created, groups_updated,
            memberships_added, errors
        """
        logger.info("=" * 80)
        logger.info("Starting Story Grouping Pipeline")
        logger.info("=" * 80)
        
        results = {
            "stories_processed": 0,
            "groups_created": 0,
            "groups_updated": 0,
            "memberships_added": 0,
            "errors": 0,
        }
        
        try:
            # Step 1: Handle regrouping if requested
            if regroup:
                logger.info("Regrouping mode: clearing existing groups...")
                self.member_writer.clear_all_memberships()
                self.group_writer.clear_all_groups()
                self.grouper.clear_groups()
            
            # Step 2: Load existing groups
            if not regroup:
                logger.info("Loading existing groups...")
                existing_groups = self.group_writer.get_active_groups()
                self.grouper.load_existing_groups(existing_groups)
                logger.info(f"Loaded {len(existing_groups)} existing groups")
            
            # Step 3: Fetch embeddings to process
            logger.info("Fetching story embeddings...")
            if regroup:
                embeddings = self.embedding_reader.fetch_all_embeddings(limit=limit)
            else:
                embeddings = self.embedding_reader.fetch_ungrouped_embeddings(
                    limit=limit
                )
            
            if not embeddings:
                logger.info("No stories to process")
                return results
            
            logger.info(f"Processing {len(embeddings)} stories")
            
            # Step 4: Group stories
            logger.info("Grouping stories...")
            initial_group_count = len(self.grouper.groups)
            
            groups = self.grouper.group_stories(embeddings)
            
            new_groups = [g for g in groups if g.group_id is None]
            updated_groups = [g for g in groups if g.group_id is not None]
            
            results["stories_processed"] = len(embeddings)
            results["groups_created"] = len(new_groups)
            results["groups_updated"] = len(updated_groups)
            
            # Step 5: Write results to database
            logger.info("Writing results to database...")
            
            # Create new groups
            for group in new_groups:
                try:
                    group_id = self.group_writer.create_group(
                        centroid_embedding=group.centroid,
                        member_count=group.member_count,
                        status="active",
                    )
                    
                    # Set the group ID for membership writes
                    group.group_id = group_id
                    
                except Exception as e:
                    logger.error(f"Error creating group: {e}")
                    results["errors"] += 1
                    if not self.continue_on_error:
                        raise
            
            # Update existing groups
            for group in updated_groups:
                try:
                    self.group_writer.update_group(
                        group_id=group.group_id,
                        centroid_embedding=group.centroid,
                        member_count=group.member_count,
                    )
                    
                except Exception as e:
                    logger.error(f"Error updating group {group.group_id}: {e}")
                    results["errors"] += 1
                    if not self.continue_on_error:
                        raise
            
            # Add memberships in batches
            logger.info("Writing group memberships...")
            memberships = []
            
            for group in groups:
                if not group.group_id:
                    logger.warning(f"Skipping group without ID")
                    continue
                
                for member in group.members:
                    memberships.append({
                        "group_id": group.group_id,
                        "news_url_id": member["news_url_id"],
                        "similarity_score": 1.0,  # Will be calculated by add_member
                    })
            
            if memberships:
                try:
                    count = self.member_writer.add_members_batch(memberships)
                    results["memberships_added"] = count
                    
                except Exception as e:
                    logger.error(f"Error adding memberships: {e}")
                    results["errors"] += 1
                    if not self.continue_on_error:
                        raise
            
            # Step 6: Log summary
            logger.info("=" * 80)
            logger.info("Grouping Pipeline Complete")
            logger.info("=" * 80)
            logger.info(f"Stories processed:     {results['stories_processed']}")
            logger.info(f"Groups created:        {results['groups_created']}")
            logger.info(f"Groups updated:        {results['groups_updated']}")
            logger.info(f"Memberships added:     {results['memberships_added']}")
            logger.info(f"Errors:                {results['errors']}")
            logger.info("=" * 80)
            
            # Log group statistics
            stats = self.grouper.get_group_stats()
            logger.info("Group Statistics:")
            logger.info(f"  Total groups:        {stats['total_groups']}")
            logger.info(f"  Total stories:       {stats['total_stories']}")
            logger.info(f"  Avg group size:      {stats['avg_group_size']:.2f}")
            logger.info(f"  Min group size:      {stats['min_group_size']}")
            logger.info(f"  Max group size:      {stats['max_group_size']}")
            logger.info(f"  Singleton groups:    {stats['singleton_groups']}")
            logger.info("=" * 80)
            
            return results
            
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            results["errors"] += 1
            raise

    def get_progress_info(self) -> Dict:
        """
        Get progress information about story grouping.
        
        Returns:
            Dict with keys: total_stories, grouped_stories, ungrouped_stories,
            total_groups, active_groups, avg_group_size
        """
        logger.info("Fetching progress information...")
        
        try:
            # Get embedding stats
            embedding_stats = self.embedding_reader.get_embedding_stats()
            
            # Get group stats
            group_stats = self.group_writer.get_group_stats()
            
            # Combine stats
            progress = {
                "total_stories": embedding_stats["embeddings_with_vectors"],
                "grouped_stories": embedding_stats["grouped_count"],
                "ungrouped_stories": embedding_stats["ungrouped_count"],
                "total_groups": group_stats["total_groups"],
                "active_groups": group_stats["active_groups"],
                "avg_group_size": group_stats["avg_group_size"],
            }
            
            return progress
            
        except Exception as e:
            logger.error(f"Error fetching progress info: {e}")
            raise

    def validate_configuration(self) -> bool:
        """
        Validate pipeline configuration and dependencies.
        
        Returns:
            True if configuration is valid
            
        Raises:
            ValueError: If configuration is invalid
        """
        logger.info("Validating pipeline configuration...")
        
        # Check similarity threshold
        if not 0.0 <= self.similarity_threshold <= 1.0:
            raise ValueError(
                f"Similarity threshold must be between 0 and 1, "
                f"got {self.similarity_threshold}"
            )
        
        # Check database connectivity by fetching a small sample
        try:
            self.embedding_reader.fetch_ungrouped_embeddings(limit=1)
            logger.info("✓ Database connection OK")
        except Exception as e:
            raise ValueError(f"Database connection failed: {e}")
        
        logger.info("✓ Configuration valid")
        return True
