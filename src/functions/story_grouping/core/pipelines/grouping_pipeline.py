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
        batch_size: Optional[int] = None,
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
        if batch_size is None:
            batch_size = int(os.getenv("GROUPING_BATCH_SIZE", "200"))
        if batch_size <= 0:
            raise ValueError("Batch size must be a positive integer")
        self.batch_size = batch_size
        self.grouper = StoryGrouper(similarity_threshold=similarity_threshold)

        logger.info(
            f"Initialized GroupingPipeline with threshold={similarity_threshold} "
            f"and batch_size={self.batch_size}"
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
            logger.info(
                "Fetching story embeddings in batches of %s...",
                self.batch_size,
            )

            batches = self.embedding_reader.iter_grouping_embeddings(
                regroup=regroup,
                limit=limit,
                batch_size=self.batch_size,
            )

            total_batches = 0
            new_group_ids = set()
            updated_group_ids = set()

            for batch in batches:
                if not batch:
                    continue

                total_batches += 1
                logger.info(
                    "Processing batch %s with %s stories",
                    total_batches,
                    len(batch),
                )

                self.grouper.group_stories(batch)
                results["stories_processed"] += len(batch)

                memberships = []
                pending_groups = []

                for group in self.grouper.groups:
                    pending_members = group.drain_pending_members()

                    if not pending_members:
                        continue

                    created_this_batch = False

                    if group.group_id is None:
                        try:
                            group_id = self.group_writer.create_group(
                                centroid_embedding=group.centroid,
                                member_count=group.member_count,
                                status="active",
                            )

                            if not group_id:
                                raise ValueError("Group creation returned no ID")

                            group.group_id = group_id
                            new_group_ids.add(group_id)
                            created_this_batch = True

                        except Exception as e:
                            logger.error(f"Error creating group: {e}")
                            results["errors"] += 1
                            group.restore_pending_members(pending_members)
                            if not self.continue_on_error:
                                raise
                            continue

                    if group.group_id and not created_this_batch:
                        try:
                            self.group_writer.update_group(
                                group_id=group.group_id,
                                centroid_embedding=group.centroid,
                                member_count=group.member_count,
                            )

                            updated_group_ids.add(group.group_id)

                        except Exception as e:
                            logger.error(
                                f"Error updating group {group.group_id}: {e}"
                            )
                            results["errors"] += 1
                            group.restore_pending_members(pending_members)
                            if not self.continue_on_error:
                                raise
                            continue

                    memberships.extend(
                        {
                            "group_id": group.group_id,
                            "news_url_id": member["news_url_id"],
                            "news_fact_id": member.get("news_fact_id"),
                            "similarity_score": member.get("similarity", 1.0),
                        }
                        for member in pending_members
                        if group.group_id
                    )

                    pending_groups.append((group, pending_members))

                if memberships:
                    try:
                        count = self.member_writer.add_members_batch(memberships)
                        results["memberships_added"] += count

                    except Exception as e:
                        logger.error(f"Error adding memberships: {e}")
                        results["errors"] += 1
                        for group, members in pending_groups:
                            group.restore_pending_members(members)
                        if not self.continue_on_error:
                            raise
                    else:
                        for group, members in pending_groups:
                            group.mark_members_persisted(members)
                        pending_groups.clear()

            if results["stories_processed"] == 0:
                logger.info("No stories to process")
                return results

            results["groups_created"] = len(new_group_ids)
            results["groups_updated"] = len(updated_group_ids)

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
