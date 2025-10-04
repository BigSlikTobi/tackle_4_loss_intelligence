"""Story grouping logic using similarity-based clustering."""

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

from .similarity import (
    calculate_cosine_similarity,
    calculate_centroid,
    find_most_similar,
)

logger = logging.getLogger(__name__)


class StoryGroup:
    """Represents a group of similar stories."""

    def __init__(
        self,
        group_id: Optional[str] = None,
        centroid: Optional[List[float]] = None,
        member_embeddings: Optional[List[Dict]] = None,
    ):
        """
        Initialize a story group.
        
        Args:
            group_id: Existing group ID (None for new groups)
            centroid: Centroid embedding vector (None to calculate from members)
            member_embeddings: List of member dicts with keys: news_url_id, 
                              embedding_vector
        """
        self.group_id = group_id
        self.members: List[Dict] = member_embeddings or []
        self._centroid = centroid

    @property
    def centroid(self) -> Optional[List[float]]:
        """Get the group centroid, calculating if necessary."""
        if self._centroid is None and self.members:
            self._centroid = self._calculate_centroid()
        return self._centroid

    def _calculate_centroid(self) -> List[float]:
        """Calculate centroid from member embeddings."""
        if not self.members:
            raise ValueError("Cannot calculate centroid for empty group")
        
        embeddings = [m["embedding_vector"] for m in self.members]
        return calculate_centroid(embeddings)

    def add_member(self, news_url_id: str, embedding_vector: List[float]) -> float:
        """
        Add a member to the group.
        
        Args:
            news_url_id: ID of the news URL
            embedding_vector: Embedding vector for the story
            
        Returns:
            Similarity score with current centroid (1.0 for first member)
        """
        # Calculate similarity with current centroid
        if self.centroid is None:
            similarity = 1.0  # First member
        else:
            similarity = calculate_cosine_similarity(embedding_vector, self.centroid)
        
        # Add member
        self.members.append({
            "news_url_id": news_url_id,
            "embedding_vector": embedding_vector,
        })
        
        # Recalculate centroid
        self._centroid = self._calculate_centroid()
        
        return similarity

    @property
    def member_count(self) -> int:
        """Get the number of members in the group."""
        return len(self.members)

    def get_member_news_url_ids(self) -> List[str]:
        """Get list of news URL IDs for all members."""
        return [m["news_url_id"] for m in self.members]


class StoryGrouper:
    """Handles grouping of stories based on embedding similarity."""

    def __init__(self, similarity_threshold: float = 0.8):
        """
        Initialize the story grouper.
        
        Args:
            similarity_threshold: Minimum similarity for stories to be grouped
                                 together (0.0 to 1.0). Default: 0.8
        """
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("Similarity threshold must be between 0 and 1")
        
        self.similarity_threshold = similarity_threshold
        self.groups: List[StoryGroup] = []
        
        logger.info(
            f"Initialized StoryGrouper with threshold={similarity_threshold}"
        )

    def load_existing_groups(self, groups_data: List[Dict]) -> None:
        """
        Load existing groups from database.
        
        Args:
            groups_data: List of group dicts with keys: id, centroid_embedding
        """
        logger.info(f"Loading {len(groups_data)} existing groups...")
        
        self.groups = []
        for group_data in groups_data:
            group = StoryGroup(
                group_id=group_data["id"],
                centroid=group_data["centroid_embedding"],
                member_embeddings=[],  # We don't need to load members
            )
            self.groups.append(group)
        
        logger.info(f"Loaded {len(self.groups)} groups")

    def assign_story(
        self,
        news_url_id: str,
        embedding_vector: List[float],
    ) -> Tuple[StoryGroup, float]:
        """
        Assign a story to the most similar group or create a new group.
        
        Args:
            news_url_id: ID of the news URL
            embedding_vector: Embedding vector for the story
            
        Returns:
            Tuple of (group, similarity_score)
        """
        # If no groups exist, create the first one
        if not self.groups:
            group = StoryGroup()
            similarity = group.add_member(news_url_id, embedding_vector)
            self.groups.append(group)
            
            logger.debug(
                f"Created first group for story {news_url_id}"
            )
            return (group, similarity)
        
        # Find most similar existing group
        centroids = [g.centroid for g in self.groups if g.centroid is not None]
        
        if not centroids:
            # No valid centroids, create new group
            group = StoryGroup()
            similarity = group.add_member(news_url_id, embedding_vector)
            self.groups.append(group)
            return (group, similarity)
        
        best_idx, best_similarity = find_most_similar(
            embedding_vector,
            centroids,
            threshold=self.similarity_threshold,
        )
        
        # If similarity meets threshold, add to existing group
        if best_idx >= 0:
            group = self.groups[best_idx]
            similarity = group.add_member(news_url_id, embedding_vector)
            
            logger.debug(
                f"Added story {news_url_id} to existing group "
                f"(similarity: {similarity:.4f})"
            )
            return (group, similarity)
        
        # Otherwise, create new group
        group = StoryGroup()
        similarity = group.add_member(news_url_id, embedding_vector)
        self.groups.append(group)
        
        logger.debug(
            f"Created new group for story {news_url_id} "
            f"(max similarity: {best_similarity:.4f} below threshold)"
        )
        return (group, similarity)

    def group_stories(
        self,
        story_embeddings: List[Dict],
    ) -> List[StoryGroup]:
        """
        Group a list of stories based on their embeddings.
        
        Args:
            story_embeddings: List of dicts with keys: news_url_id, embedding_vector
            
        Returns:
            List of StoryGroup objects
        """
        logger.info(
            f"Grouping {len(story_embeddings)} stories with "
            f"{len(self.groups)} existing groups..."
        )
        
        grouped_count = 0
        new_groups_count = len(self.groups)
        
        for story in story_embeddings:
            news_url_id = story["news_url_id"]
            embedding_vector = story["embedding_vector"]
            
            # Validate embedding
            if not embedding_vector or not isinstance(embedding_vector, list):
                logger.warning(
                    f"Skipping story {news_url_id}: invalid embedding"
                )
                continue
            
            # Assign to group
            group, similarity = self.assign_story(news_url_id, embedding_vector)
            grouped_count += 1
            
            # Log progress every 100 stories
            if grouped_count % 100 == 0:
                logger.info(
                    f"Processed {grouped_count}/{len(story_embeddings)} stories, "
                    f"{len(self.groups)} total groups"
                )
        
        new_groups_added = len(self.groups) - new_groups_count
        
        logger.info(
            f"Grouping complete: {grouped_count} stories processed, "
            f"{new_groups_added} new groups created, "
            f"{len(self.groups)} total groups"
        )
        
        return self.groups

    def get_group_stats(self) -> Dict:
        """
        Get statistics about the current groups.
        
        Returns:
            Dict with keys: total_groups, total_stories, avg_group_size,
            min_group_size, max_group_size, singleton_groups
        """
        if not self.groups:
            return {
                "total_groups": 0,
                "total_stories": 0,
                "avg_group_size": 0.0,
                "min_group_size": 0,
                "max_group_size": 0,
                "singleton_groups": 0,
            }
        
        group_sizes = [g.member_count for g in self.groups]
        total_stories = sum(group_sizes)
        
        return {
            "total_groups": len(self.groups),
            "total_stories": total_stories,
            "avg_group_size": total_stories / len(self.groups),
            "min_group_size": min(group_sizes),
            "max_group_size": max(group_sizes),
            "singleton_groups": sum(1 for size in group_sizes if size == 1),
        }

    def clear_groups(self) -> None:
        """Clear all groups."""
        self.groups = []
        logger.info("Cleared all groups")
