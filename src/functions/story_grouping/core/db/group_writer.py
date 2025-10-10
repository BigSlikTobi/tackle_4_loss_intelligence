"""Writers for story groups and group membership."""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
import uuid

from src.shared.db import get_supabase_client
from .embedding_reader import parse_vector

logger = logging.getLogger(__name__)


class GroupWriter:
    """Writes and updates story groups in the story_groups table."""

    def __init__(self, dry_run: bool = False, days_lookback: int = 14):
        """
        Initialize the group writer.
        
        Args:
            dry_run: If True, log operations without writing to database
            days_lookback: Number of days to look back for groups (default: 14)
        """
        self.client = get_supabase_client()
        self.dry_run = dry_run
        self.days_lookback = days_lookback
    
    def _get_cutoff_date(self) -> str:
        """
        Get the cutoff date for filtering groups.
        
        Returns:
            ISO format datetime string for the cutoff date
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_lookback)
        return cutoff.isoformat()

    def create_group(
        self,
        centroid_embedding: List[float],
        member_count: int,
        status: str = "active",
    ) -> Optional[str]:
        """
        Create a new story group.
        
        Args:
            centroid_embedding: The centroid vector for the group
            member_count: Number of members in the group
            status: Group status (default: "active")
            
        Returns:
            Group ID if created, None if dry_run
        """
        group_id = str(uuid.uuid4())
        
        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would create group {group_id} "
                f"with {member_count} members"
            )
            return group_id
        
        try:
            now = datetime.utcnow().isoformat()
            
            data = {
                "id": group_id,
                "centroid_embedding": centroid_embedding,
                "member_count": member_count,
                "status": status,
                "created_at": now,
                "updated_at": now,
            }
            
            response = self.client.table("story_groups").insert(data).execute()
            
            if response.data:
                logger.info(f"Created group {group_id} with {member_count} members")
                return group_id
            else:
                logger.error(f"Failed to create group: no data returned")
                return None
                
        except Exception as e:
            logger.error(f"Error creating group: {e}")
            raise

    def update_group(
        self,
        group_id: str,
        centroid_embedding: Optional[List[float]] = None,
        member_count: Optional[int] = None,
        status: Optional[str] = None,
    ) -> bool:
        """
        Update an existing story group.
        
        Args:
            group_id: ID of the group to update
            centroid_embedding: New centroid vector (optional)
            member_count: New member count (optional)
            status: New status (optional)
            
        Returns:
            True if updated successfully, False otherwise
        """
        if self.dry_run:
            updates = []
            if centroid_embedding is not None:
                updates.append("centroid")
            if member_count is not None:
                updates.append(f"member_count={member_count}")
            if status is not None:
                updates.append(f"status={status}")
            
            logger.info(
                f"[DRY RUN] Would update group {group_id}: {', '.join(updates)}"
            )
            return True
        
        try:
            data = {"updated_at": datetime.utcnow().isoformat()}
            
            if centroid_embedding is not None:
                data["centroid_embedding"] = centroid_embedding
            if member_count is not None:
                data["member_count"] = member_count
            if status is not None:
                data["status"] = status
            
            response = (
                self.client.table("story_groups")
                .update(data)
                .eq("id", group_id)
                .execute()
            )
            
            if response.data:
                logger.debug(f"Updated group {group_id}")
                return True
            else:
                logger.warning(f"No group found with ID {group_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating group {group_id}: {e}")
            raise

    def get_all_groups(self) -> List[Dict]:
        """
        Fetch all story groups.
        
        Returns:
            List of group dicts with keys: id, centroid_embedding, 
            member_count, status, created_at, updated_at
        """
        logger.info("Fetching all story groups...")
        
        try:
            groups = []
            page_size = 1000
            offset = 0
            
            # Fetch all groups with pagination
            while True:
                response = (
                    self.client.table("story_groups")
                    .select("*")
                    .order("created_at", desc=False)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                
                if not response.data:
                    break
                
                groups.extend(response.data)
                
                if len(response.data) < page_size:
                    break
                    
                offset += page_size
            
            # Parse centroid embeddings
            for group in groups:
                group["centroid_embedding"] = parse_vector(group["centroid_embedding"])
            
            logger.info(f"Fetched {len(groups)} groups")
            
            return groups
            
        except Exception as e:
            logger.error(f"Error fetching groups: {e}")
            raise

    def get_active_groups(self) -> List[Dict]:
        """
        Fetch active story groups from the last N days (configured via days_lookback).
        
        Returns:
            List of active group dicts
        """
        logger.info("Fetching active story groups...")
        
        try:
            cutoff_date = self._get_cutoff_date()
            logger.info(f"Filtering groups created after {cutoff_date} ({self.days_lookback} days)")
            
            groups = []
            page_size = 1000
            offset = 0
            
            # Fetch recent active groups with pagination
            while True:
                response = (
                    self.client.table("story_groups")
                    .select("*")
                    .eq("status", "active")
                    .gte("created_at", cutoff_date)
                    .order("created_at", desc=False)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                
                if not response.data:
                    break
                
                groups.extend(response.data)
                
                if len(response.data) < page_size:
                    break
                    
                offset += page_size
            
            # Parse centroid embeddings
            for group in groups:
                group["centroid_embedding"] = parse_vector(group["centroid_embedding"])
            
            logger.info(f"Fetched {len(groups)} active groups")
            
            return groups
            
        except Exception as e:
            logger.error(f"Error fetching active groups: {e}")
            raise

    def get_group_stats(self) -> Dict:
        """
        Get statistics about story groups.
        
        Returns:
            Dict with keys: total_groups, active_groups, total_members, 
            avg_group_size
        """
        logger.info("Fetching group statistics...")
        
        try:
            # Total groups
            total_response = self.client.table("story_groups").select(
                "id", count="exact"
            ).execute()
            total_count = total_response.count or 0
            
            # Active groups
            active_response = (
                self.client.table("story_groups")
                .select("id", count="exact")
                .eq("status", "active")
                .execute()
            )
            active_count = active_response.count or 0
            
            # Member count sum
            member_response = (
                self.client.table("story_groups")
                .select("member_count")
                .execute()
            )
            total_members = sum(
                g.get("member_count", 0) for g in member_response.data
            )
            
            avg_size = total_members / total_count if total_count > 0 else 0
            
            stats = {
                "total_groups": total_count,
                "active_groups": active_count,
                "total_members": total_members,
                "avg_group_size": round(avg_size, 2),
            }
            
            logger.info(f"Group stats: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error fetching group statistics: {e}")
            raise

    def clear_all_groups(self) -> int:
        """
        Delete all story groups (for regrouping).
        
        Returns:
            Number of groups deleted
        """
        if self.dry_run:
            # Get count
            response = self.client.table("story_groups").select(
                "id", count="exact"
            ).execute()
            count = response.count or 0
            logger.info(f"[DRY RUN] Would delete {count} groups")
            return count
        
        try:
            logger.warning("Deleting all story groups...")
            
            # Get count before deletion
            count_response = self.client.table("story_groups").select(
                "id", count="exact"
            ).execute()
            count = count_response.count or 0
            
            # Delete all
            self.client.table("story_groups").delete().neq("id", "").execute()
            
            logger.info(f"Deleted {count} groups")
            return count
            
        except Exception as e:
            logger.error(f"Error clearing groups: {e}")
            raise


class GroupMemberWriter:
    """Writes story group memberships to the story_group_member table."""

    def __init__(self, dry_run: bool = False):
        """
        Initialize the group member writer.
        
        Args:
            dry_run: If True, log operations without writing to database
        """
        self.client = get_supabase_client()
        self.dry_run = dry_run

    def add_member(
        self,
        group_id: str,
        news_url_id: str,
        similarity_score: float,
    ) -> Optional[str]:
        """
        Add a story to a group.
        
        Args:
            group_id: ID of the group
            news_url_id: ID of the news URL
            similarity_score: Similarity score with group centroid
            
        Returns:
            Membership ID if created, None if dry_run
        """
        member_id = str(uuid.uuid4())
        
        if self.dry_run:
            logger.debug(
                f"[DRY RUN] Would add story {news_url_id} to group {group_id} "
                f"(similarity: {similarity_score:.4f})"
            )
            return member_id
        
        try:
            data = {
                "id": member_id,
                "group_id": group_id,
                "news_url_id": news_url_id,
                "similarity_score": similarity_score,
                "added_at": datetime.utcnow().isoformat(),
            }
            
            response = self.client.table("story_group_members").insert(data).execute()
            
            if response.data:
                logger.debug(
                    f"Added story {news_url_id} to group {group_id} "
                    f"(similarity: {similarity_score:.4f})"
                )
                return member_id
            else:
                logger.error(f"Failed to add member: no data returned")
                return None
                
        except Exception as e:
            logger.error(f"Error adding member: {e}")
            raise

    def add_members_batch(
        self,
        memberships: List[Dict[str, any]],
    ) -> int:
        """
        Add multiple stories to groups in a batch.
        
        Args:
            memberships: List of dicts with keys: group_id, news_url_id, 
                        similarity_score
            
        Returns:
            Number of memberships created
        """
        if not memberships:
            return 0
        
        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would add {len(memberships)} story memberships"
            )
            return len(memberships)
        
        try:
            now = datetime.utcnow().isoformat()
            
            data = [
                {
                    "id": str(uuid.uuid4()),
                    "group_id": m["group_id"],
                    "news_url_id": m["news_url_id"],
                    "similarity_score": m["similarity_score"],
                    "added_at": now,
                }
                for m in memberships
            ]
            
            response = self.client.table("story_group_members").insert(data).execute()
            
            count = len(response.data) if response.data else 0
            logger.info(f"Added {count} story memberships")
            
            return count
            
        except Exception as e:
            logger.error(f"Error adding members batch: {e}")
            raise

    def get_group_members(self, group_id: str) -> List[Dict]:
        """
        Get all members of a group.
        
        Args:
            group_id: ID of the group
            
        Returns:
            List of member dicts
        """
        try:
            response = (
                self.client.table("story_group_members")
                .select("*")
                .eq("group_id", group_id)
                .execute()
            )
            
            return response.data
            
        except Exception as e:
            logger.error(f"Error fetching group members: {e}")
            raise

    def clear_all_memberships(self) -> int:
        """
        Delete all group memberships (for regrouping).
        
        Returns:
            Number of memberships deleted
        """
        if self.dry_run:
            response = self.client.table("story_group_members").select(
                "id", count="exact"
            ).execute()
            count = response.count or 0
            logger.info(f"[DRY RUN] Would delete {count} memberships")
            return count
        
        try:
            logger.warning("Deleting all group memberships...")
            
            # Get count before deletion
            count_response = self.client.table("story_group_members").select(
                "id", count="exact"
            ).execute()
            count = count_response.count or 0
            
            # Delete all
            self.client.table("story_group_members").delete().neq("id", "").execute()
            
            logger.info(f"Deleted {count} memberships")
            return count
            
        except Exception as e:
            logger.error(f"Error clearing memberships: {e}")
            raise
