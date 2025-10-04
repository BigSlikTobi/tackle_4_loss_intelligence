"""Reader for story embeddings from the database."""

import logging
import json
from typing import Dict, List, Optional
from datetime import datetime

from src.shared.db import get_supabase_client

logger = logging.getLogger(__name__)


def parse_vector(vector_data) -> Optional[List[float]]:
    """
    Parse vector data from database format to Python list.
    
    Args:
        vector_data: Vector in various formats (string, list, etc.)
        
    Returns:
        List of floats, or None if invalid
    """
    if vector_data is None:
        return None
    
    # If already a list, return it
    if isinstance(vector_data, list):
        return vector_data
    
    # If string, try to parse
    if isinstance(vector_data, str):
        # PostgreSQL vector format: "[1.0, 2.0, 3.0]"
        try:
            # Remove brackets and split by comma
            if vector_data.startswith('[') and vector_data.endswith(']'):
                vector_str = vector_data[1:-1]
                return [float(x.strip()) for x in vector_str.split(',')]
            else:
                # Try JSON parsing
                return json.loads(vector_data)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse vector: {e}")
            return None
    
    return None


class EmbeddingReader:
    """Reads story embeddings from the story_embeddings table."""

    def __init__(self):
        """Initialize the embedding reader."""
        self.client = get_supabase_client()

    def fetch_ungrouped_embeddings(
        self, 
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch embeddings for stories not yet assigned to a group.
        
        Args:
            limit: Optional maximum number of embeddings to fetch
            
        Returns:
            List of dicts with keys: id, news_url_id, embedding_vector, created_at
        """
        logger.info("Fetching ungrouped story embeddings...")
        
        try:
            # Use RPC function or a more efficient query pattern
            # Fetch all embeddings first, then filter in Python
            # This avoids the URL length issue with large NOT IN clauses
            
            # First, get all grouped news_url_ids (with pagination)
            grouped_ids = set()
            page_size = 1000
            offset = 0
            
            while True:
                grouped_response = self.client.table("story_group_members").select(
                    "news_url_id"
                ).range(offset, offset + page_size - 1).execute()
                
                if not grouped_response.data:
                    break
                    
                grouped_ids.update(item["news_url_id"] for item in grouped_response.data)
                
                if len(grouped_response.data) < page_size:
                    break
                    
                offset += page_size
            
            logger.info(f"Found {len(grouped_ids)} already grouped stories")
            
            # Then fetch embeddings with pagination and filter
            all_embeddings = []
            offset = 0
            
            while True:
                query = self.client.table("story_embeddings").select(
                    "id, news_url_id, embedding_vector, created_at"
                ).not_.is_("embedding_vector", "null").order(
                    "created_at", desc=False
                ).range(offset, offset + page_size - 1)
                
                response = query.execute()
                
                if not response.data:
                    break
                
                all_embeddings.extend(response.data)
                
                if len(response.data) < page_size:
                    break
                    
                offset += page_size
            
            logger.info(f"Fetched {len(all_embeddings)} total embeddings from database")
            
            # Filter out already grouped embeddings
            embeddings = [
                emb for emb in all_embeddings
                if emb["news_url_id"] not in grouped_ids
            ]
            
            # Parse vector format for each embedding
            for emb in embeddings:
                emb["embedding_vector"] = parse_vector(emb["embedding_vector"])
            
            # Filter out embeddings with invalid vectors
            embeddings = [
                emb for emb in embeddings
                if emb["embedding_vector"] is not None
            ]
            
            # Apply limit after filtering
            if limit and len(embeddings) > limit:
                embeddings = embeddings[:limit]
            
            logger.info(f"Fetched {len(embeddings)} ungrouped embeddings")
            
            return embeddings
            
        except Exception as e:
            logger.error(f"Error fetching ungrouped embeddings: {e}")
            raise

    def fetch_all_embeddings(
        self, 
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch all story embeddings regardless of grouping status.
        
        Args:
            limit: Optional maximum number of embeddings to fetch
            
        Returns:
            List of dicts with keys: id, news_url_id, embedding_vector, created_at
        """
        logger.info("Fetching all story embeddings...")
        
        try:
            embeddings = []
            page_size = 1000
            offset = 0
            
            # Fetch all embeddings with pagination
            while True:
                query = self.client.table("story_embeddings").select(
                    "id, news_url_id, embedding_vector, created_at"
                ).not_.is_("embedding_vector", "null").order(
                    "created_at", desc=False
                ).range(offset, offset + page_size - 1)
                
                response = query.execute()
                
                if not response.data:
                    break
                
                embeddings.extend(response.data)
                
                # Stop if we've hit the limit
                if limit and len(embeddings) >= limit:
                    embeddings = embeddings[:limit]
                    break
                
                # Stop if we got less than a full page
                if len(response.data) < page_size:
                    break
                    
                offset += page_size
            
            logger.info(f"Fetched {len(embeddings)} total embeddings from database")
            
            # Parse vector format for each embedding
            for emb in embeddings:
                emb["embedding_vector"] = parse_vector(emb["embedding_vector"])
            
            # Filter out embeddings with invalid vectors
            embeddings = [
                emb for emb in embeddings
                if emb["embedding_vector"] is not None
            ]
            
            logger.info(f"Fetched {len(embeddings)} total embeddings")
            
            return embeddings
            
        except Exception as e:
            logger.error(f"Error fetching all embeddings: {e}")
            raise

    def get_embeddings_by_news_url_ids(
        self, 
        news_url_ids: List[str]
    ) -> List[Dict]:
        """
        Fetch embeddings for specific news URLs.
        
        Args:
            news_url_ids: List of news URL IDs to fetch
            
        Returns:
            List of dicts with keys: id, news_url_id, embedding_vector, created_at
        """
        if not news_url_ids:
            return []
        
        logger.debug(f"Fetching embeddings for {len(news_url_ids)} news URLs")
        
        try:
            response = self.client.table("story_embeddings").select(
                "id, news_url_id, embedding_vector, created_at"
            ).in_("news_url_id", news_url_ids).execute()
            
            embeddings = response.data
            
            # Parse vector format for each embedding
            for emb in embeddings:
                emb["embedding_vector"] = parse_vector(emb["embedding_vector"])
            
            return embeddings
            
        except Exception as e:
            logger.error(f"Error fetching embeddings by news URL IDs: {e}")
            raise

    def get_embedding_stats(self) -> Dict:
        """
        Get statistics about story embeddings.
        
        Returns:
            Dict with keys: total_embeddings, embeddings_with_vectors, 
            grouped_count, ungrouped_count
        """
        logger.info("Fetching embedding statistics...")
        
        try:
            # Total embeddings
            total_response = self.client.table("story_embeddings").select(
                "id", count="exact"
            ).execute()
            total_count = total_response.count or 0
            
            # Embeddings with vectors
            vector_response = self.client.table("story_embeddings").select(
                "id", count="exact"
            ).not_.is_("embedding_vector", "null").execute()
            vector_count = vector_response.count or 0
            
            # Grouped embeddings
            grouped_response = self.client.table("story_group_members").select(
                "news_url_id", count="exact"
            ).execute()
            grouped_count = grouped_response.count or 0
            
            ungrouped_count = vector_count - grouped_count
            
            stats = {
                "total_embeddings": total_count,
                "embeddings_with_vectors": vector_count,
                "grouped_count": grouped_count,
                "ungrouped_count": max(0, ungrouped_count),
            }
            
            logger.info(f"Embedding stats: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error fetching embedding statistics: {e}")
            raise
