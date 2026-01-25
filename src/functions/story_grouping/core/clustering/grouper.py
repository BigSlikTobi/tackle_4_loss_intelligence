"""Story grouping logic using similarity-based clustering."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np

from .similarity import calculate_cosine_similarity, find_most_similar

logger = logging.getLogger(__name__)


@dataclass
class AssignmentResult:
    """Result of assigning a story to a group."""

    group: "StoryGroup"
    similarity: float
    created_new_group: bool
    added_to_group: bool
    previous_member_count: int


class StoryGroup:
    """Represents a group of similar stories."""

    def __init__(
        self,
        group_id: Optional[str] = None,
        centroid: Optional[List[float]] = None,
        member_embeddings: Optional[List[Dict]] = None,
        existing_member_count: int = 0,
    ):
        """
        Initialize a story group.
        
        Args:
            group_id: Existing group ID (None for new groups)
            centroid: Centroid embedding vector (None to calculate from members)
            member_embeddings: List of member dicts with keys: news_url_id, 
                              embedding_vector
            existing_member_count: Number of members already in database for 
                                  existing groups (used when loading groups without members)
        """
        self.group_id = group_id
        self.members: List[Dict] = member_embeddings or []
        self._centroid = centroid
        self._existing_member_count = existing_member_count
        self._pending_members: List[Dict] = member_embeddings.copy() if member_embeddings else []
        self._base_centroid = centroid
        self._vector_dimension: Optional[int] = (
            len(centroid) if centroid is not None else None
        )

    @property
    def centroid(self) -> Optional[List[float]]:
        """Get the group centroid, calculating if necessary."""
        if self._centroid is None and self.members:
            self._centroid = self._calculate_centroid()
        return self._centroid

    def _calculate_centroid(self) -> List[float]:
        """Calculate centroid from member embeddings."""
        vectors: List[np.ndarray] = []
        weights: List[float] = []

        if self._base_centroid is not None and self._existing_member_count > 0:
            vectors.append(np.array(self._base_centroid, dtype=np.float32))
            weights.append(float(self._existing_member_count))

        member_vectors = [m["embedding_vector"] for m in self.members]

        if not member_vectors and not vectors:
            raise ValueError("Cannot calculate centroid for empty group")

        for embedding in member_vectors:
            vectors.append(np.array(embedding, dtype=np.float32))
            weights.append(1.0)

        weighted_sum = np.zeros_like(vectors[0], dtype=np.float32)
        total_weight = 0.0

        for vector, weight in zip(vectors, weights):
            if self._vector_dimension is None:
                self._vector_dimension = len(vector)
            elif len(vector) != self._vector_dimension:
                raise ValueError("Embedding dimensions must match for centroid calculation")

            weighted_sum += vector * weight
            total_weight += weight

        centroid = weighted_sum / total_weight

        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm

        return centroid.tolist()

    def add_member(
        self,
        news_url_id: str,
        embedding_vector: List[float],
        news_fact_id: Optional[str] = None,
    ) -> float:
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
        
        if self._vector_dimension is None:
            self._vector_dimension = len(embedding_vector)
        elif len(embedding_vector) != self._vector_dimension:
            raise ValueError("Embedding dimensions must match existing centroid")

        # Add member
        member = {
            "news_url_id": news_url_id,
            "news_fact_id": news_fact_id,
            "embedding_vector": embedding_vector,
            "similarity": similarity,
        }
        self.members.append(member)
        self._pending_members.append(member)
        
        # Recalculate centroid using weighted average of existing + new members
        self._centroid = self._calculate_centroid()

        return similarity

    def mark_members_persisted(self, members: List[Dict]) -> None:
        """Mark members as persisted to the database."""
        if not members:
            return

        persisted_ids = {member["news_url_id"] for member in members}
        removed = [m for m in self.members if m["news_url_id"] in persisted_ids]

        if not removed:
            return

        self._existing_member_count += len(removed)
        self.members = [m for m in self.members if m["news_url_id"] not in persisted_ids]
        self._pending_members = [
            m for m in self._pending_members if m["news_url_id"] not in persisted_ids
        ]
        self._base_centroid = self.centroid

    @property
    def member_count(self) -> int:
        """
        Get the total number of members in the group.
        
        For existing groups loaded from database, this returns the sum of:
        - existing_member_count: members already in the database
        - len(self.members): new members added in this session
        
        For new groups, this just returns len(self.members).
        """
        return self._existing_member_count + len(self.members)

    @property
    def existing_member_count(self) -> int:
        """Return the number of members persisted before the current run."""
        return self._existing_member_count

    def get_member_news_url_ids(self) -> List[str]:
        """Get list of news URL IDs for all members."""
        return [m["news_url_id"] for m in self.members]

    def drain_pending_members(self) -> List[Dict]:
        """Return and clear members added since the last drain."""
        pending = self._pending_members
        self._pending_members = []
        return pending

    def restore_pending_members(self, members: List[Dict]) -> None:
        """Restore pending members when a write fails."""
        if not members:
            return
        self._pending_members = members + self._pending_members


class StoryGrouper:
    """Handles grouping of stories based on embedding similarity."""

    def __init__(self, similarity_threshold: float = 0.88):
        """
        Initialize the story grouper.
        
        Args:
            similarity_threshold: Minimum similarity for stories to be grouped
                                 together (0.0 to 1.0). Default: 0.55
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
            groups_data: List of group dicts with keys: id, centroid_embedding,
                        member_count
        """
        logger.info(f"Loading {len(groups_data)} existing groups...")
        
        self.groups = []
        for group_data in groups_data:
            group = StoryGroup(
                group_id=group_data["id"],
                centroid=group_data["centroid_embedding"],
                member_embeddings=[],  # Don't load existing members (only new ones)
                existing_member_count=group_data.get("member_count", 0),
            )
            self.groups.append(group)
        
        logger.info(f"Loaded {len(self.groups)} groups")


    def assign_story(
        self,
        news_url_id: str,
        embedding_vector: List[float],
        news_fact_id: Optional[str] = None,
    ) -> AssignmentResult:
        """Assign a story to the most similar group or create a new group."""

        # If no groups exist, create the first one
        if not self.groups:
            group = StoryGroup()
            similarity = group.add_member(news_url_id, embedding_vector, news_fact_id)
            self.groups.append(group)

            logger.debug("Created first group for story %s", news_url_id)
            return AssignmentResult(
                group=group,
                similarity=similarity,
                created_new_group=True,
                added_to_group=True,
                previous_member_count=0,
            )

        # Find most similar existing group while keeping original indices
        candidate_groups = [
            (idx, group.centroid)
            for idx, group in enumerate(self.groups)
            if group.centroid is not None
        ]

        if not candidate_groups:
            group = StoryGroup()
            similarity = group.add_member(news_url_id, embedding_vector)
            self.groups.append(group)
            return AssignmentResult(
                group=group,
                similarity=similarity,
                created_new_group=True,
                added_to_group=True,
                previous_member_count=0,
            )

        centroid_vectors = [centroid for _, centroid in candidate_groups]
        best_idx, best_similarity = find_most_similar(
            embedding_vector,
            centroid_vectors,
            threshold=self.similarity_threshold,
        )

        if best_idx >= 0:
            group_index = candidate_groups[best_idx][0]
            group = self.groups[group_index]

            if news_fact_id and any(
                m.get("news_fact_id") == news_fact_id for m in group.members
            ):
                logger.debug(
                    "Fact %s already pending in group %s, skipping duplicate",
                    news_fact_id,
                    group.group_id,
                )
                return AssignmentResult(
                    group=group,
                    similarity=1.0,
                    created_new_group=False,
                    added_to_group=False,
                    previous_member_count=group.member_count,
                )

            # Allow multiple facts from the same article; only skip duplicates
            # when the incoming story has no fact id and the URL is already pending.
            if news_fact_id is None and news_url_id in group.get_member_news_url_ids():
                logger.debug(
                    "Story %s already pending in group %s, skipping duplicate",
                    news_url_id,
                    group.group_id,
                )
                return AssignmentResult(
                    group=group,
                    similarity=1.0,
                    created_new_group=False,
                    added_to_group=False,
                    previous_member_count=group.member_count,
                )

            previous_member_count = group.member_count
            similarity = group.add_member(
                news_url_id, embedding_vector, news_fact_id
            )

            logger.debug(
                "Added story %s to existing group %s (similarity: %.4f)",
                news_url_id,
                group.group_id,
                similarity,
            )
            return AssignmentResult(
                group=group,
                similarity=similarity,
                created_new_group=False,
                added_to_group=True,
                previous_member_count=previous_member_count,
            )

        # Otherwise, create new group
        group = StoryGroup()
        similarity = group.add_member(news_url_id, embedding_vector, news_fact_id)
        self.groups.append(group)

        logger.debug(
            "Created new group for story %s (max similarity: %.4f below threshold)",
            news_url_id,
            best_similarity,
        )
        return AssignmentResult(
            group=group,
            similarity=similarity,
            created_new_group=True,
            added_to_group=True,
            previous_member_count=0,
        )

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
            news_fact_id = story.get("news_fact_id")
            
            # Validate embedding
            if not embedding_vector or not isinstance(embedding_vector, list):
                logger.warning(
                    f"Skipping story {news_url_id}: invalid embedding"
                )
                continue
            
            # Assign to group
            self.assign_story(news_url_id, embedding_vector, news_fact_id)
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
