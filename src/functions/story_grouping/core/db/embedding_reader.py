"""Reader for story embeddings from the database."""

import logging
import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone

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

    def __init__(self, days_lookback: int = 14):
        """
        Initialize the embedding reader.
        
        Args:
            days_lookback: Number of days to look back for stories (default: 14)
        """
        self.client = get_supabase_client()
        self.days_lookback = days_lookback
    
    def _get_cutoff_date(self) -> str:
        """
        Get the cutoff date for filtering stories.
        
        Returns:
            ISO format datetime string for the cutoff date
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_lookback)
        return cutoff.isoformat()


    def fetch_ungrouped_embeddings(
        self,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch embeddings for stories not yet assigned to a group.
        
        Uses an efficient LEFT JOIN approach at the database level to avoid
        fetching all embeddings and filtering in Python.
        
        Args:
            limit: Optional maximum number of embeddings to fetch
            
        Returns:
            List of dicts with keys: id, news_url_id, embedding_vector, created_at
        """
        logger.info("Fetching ungrouped story embeddings...")
        
        try:
            # Use a more efficient approach with LEFT JOIN
            # Instead of NOT IN which is slow for large datasets
            embeddings: List[Dict] = []

            for batch in self._iter_ungrouped_embedding_batches(
                limit=limit,
                batch_size=1000,
            ):
                embeddings.extend(batch)

            logger.info(f"Fetched {len(embeddings)} ungrouped embeddings")

            return embeddings
            
        except Exception as e:
            logger.error(f"Error fetching ungrouped embeddings: {e}")
            raise

    def fetch_embeddings_by_news_url_ids(
        self, news_url_ids: List[str]
    ) -> List[Dict]:
        """Fetch embeddings for a specific list of news_url IDs."""

        if not news_url_ids:
            return []

        logger.info(
            "Fetching embeddings for %s requested news_url_ids", len(news_url_ids)
        )

        unique_ids: List[str] = []
        seen = set()
        for news_id in news_url_ids:
            if news_id and news_id not in seen:
                seen.add(news_id)
                unique_ids.append(news_id)

        if not unique_ids:
            return []

        chunk_size = 200
        embeddings: Dict[str, Dict] = {}

        for start in range(0, len(unique_ids), chunk_size):
            chunk = unique_ids[start : start + chunk_size]
            try:
                response = (
                    self.client.table("story_embeddings")
                    .select("id, news_url_id, embedding_vector, created_at")
                    .in_("news_url_id", chunk)
                    .execute()
                )

                for item in response.data or []:
                    vector = parse_vector(item.get("embedding_vector"))
                    if vector is not None:
                        item["embedding_vector"] = vector
                        embeddings[item["news_url_id"]] = item
                    else:
                        logger.warning(
                            "Embedding vector missing for news_url_id=%s",
                            item.get("news_url_id"),
                        )

            except Exception as exc:
                logger.error(
                    "Error fetching embeddings for IDs %s-%s: %s",
                    start,
                    start + len(chunk) - 1,
                    exc,
                )
                raise

        ordered_results = [
            embeddings[news_id]
            for news_id in news_url_ids
            if news_id in embeddings
        ]

        logger.info(
            "Fetched %s/%s embeddings for requested IDs",
            len(ordered_results),
            len(unique_ids),
        )

        return ordered_results
    
    def _iter_ungrouped_fallback_batches(
        self,
        limit: Optional[int],
        batch_size: int,
    ):
        """
        Fallback method that fetches grouped IDs first, then filters embeddings.
        Used when database-level filtering isn't available.
        
        Optimized to:
        - Reduce initial scan time by limiting batches checked
        - Remove ORDER BY to speed up queries
        - Use smaller fetch batches to avoid timeouts
        
        Args:
            limit: Optional maximum number of embeddings to fetch
            
        Yields:
            Lists of dicts with keys: id, news_url_id, embedding_vector, created_at
        """
        logger.info("Using fallback method to fetch ungrouped embeddings...")
        
        try:
            cutoff_date = self._get_cutoff_date()
            logger.info(f"Filtering stories created after {cutoff_date} ({self.days_lookback} days)")
            
            # First, get all grouped news_url_ids in smaller batches
            # Optimize: fetch only IDs, no other columns
            grouped_ids = set()
            page_size = 1000
            offset = 0
            max_grouped_batches = 15  # Safety limit for grouped IDs
            grouped_batches_fetched = 0
            
            while grouped_batches_fetched < max_grouped_batches:
                try:
                    grouped_response = self.client.table("story_group_members").select(
                        "news_url_id"
                    ).range(offset, offset + page_size - 1).execute()
                    
                    if not grouped_response.data:
                        break
                        
                    grouped_ids.update(item["news_url_id"] for item in grouped_response.data)
                    grouped_batches_fetched += 1
                    
                    if len(grouped_response.data) < page_size:
                        break
                        
                    offset += page_size
                    
                except Exception as grouped_error:
                    if "timeout" in str(grouped_error).lower():
                        logger.warning(
                            f"Timeout fetching grouped IDs at offset {offset}, "
                            f"using {len(grouped_ids)} IDs collected so far"
                        )
                        break
                    raise
            
            logger.info(f"Found {len(grouped_ids)} already grouped stories")
            
            # Then fetch embeddings in batches, filtering as we go
            # OPTIMIZATION: Use smaller batches and no ORDER BY
            yielded = 0
            offset = 0
            fetch_batch_size = 500  # Reduced from 1000
            
            # Calculate reasonable max batches based on limit
            # With DESC order and indexes, we can check more batches safely
            if limit and limit <= 100:
                max_batches_to_check = 10  # Increased - DESC order finds ungrouped faster
            elif limit and limit <= 500:
                max_batches_to_check = 20
            else:
                max_batches_to_check = 30  # Increased to scan more data

            batches_checked = 0

            while batches_checked < max_batches_to_check:
                try:
                    # OPTIMIZATION: Use DESC order to get newest stories first
                    # These are most likely to be ungrouped
                    # With the new idx_story_embeddings_with_vectors index, this should be fast
                    query = self.client.table("story_embeddings").select(
                        "id, news_url_id, embedding_vector, created_at"
                    ).not_.is_("embedding_vector", "null").gte(
                        "created_at", cutoff_date
                    ).order("created_at", desc=True).range(offset, offset + fetch_batch_size - 1)

                    logger.info(
                        f"Fetching embeddings batch at offset {offset} "
                        f"(batch {batches_checked + 1}/{max_batches_to_check})..."
                    )
                    response = query.execute()

                    if not response.data:
                        logger.info("No more data, stopping")
                        break

                    # Filter this batch for ungrouped stories
                    batch_ungrouped = [
                        emb for emb in response.data
                        if emb["news_url_id"] not in grouped_ids
                    ]
                    logger.info(
                        f"Found {len(batch_ungrouped)} ungrouped in batch "
                        f"(out of {len(response.data)} total)"
                    )

                    parsed_batch = []
                    for emb in batch_ungrouped:
                        emb["embedding_vector"] = parse_vector(emb["embedding_vector"])
                        if emb["embedding_vector"] is not None:
                            parsed_batch.append(emb)

                    batch_index = 0
                    while batch_index < len(parsed_batch):
                        if limit is not None and yielded >= limit:
                            logger.info(f"Reached limit of {limit} ungrouped embeddings")
                            return

                        remaining = (
                            limit - yielded if limit is not None else batch_size
                        )
                        current_size = min(batch_size, remaining)
                        chunk = parsed_batch[batch_index: batch_index + current_size]

                        if not chunk:
                            break

                        yield chunk
                        yielded += len(chunk)
                        batch_index += current_size

                    # Stop if we have enough ungrouped embeddings
                    if limit is not None and yielded >= limit:
                        logger.info(f"Reached limit of {limit} ungrouped embeddings")
                        return

                    # Stop if we got less than a full page
                    if len(response.data) < fetch_batch_size:
                        logger.info("Partial page received, stopping")
                        break

                    batches_checked += 1
                    offset += fetch_batch_size

                except Exception as batch_error:
                    logger.error(f"Error fetching batch at offset {offset}: {batch_error}")
                    # If we hit a timeout, return what we have so far
                    if "timeout" in str(batch_error).lower():
                        logger.warning(
                            f"Timeout at offset {offset}, returning {yielded} ungrouped embeddings"
                        )
                        return
                    raise

            if batches_checked >= max_batches_to_check:
                logger.warning(
                    f"Checked {max_batches_to_check} batches, "
                    f"yielded {yielded} ungrouped embeddings"
                )

            logger.info(
                f"Completed: yielded {yielded} ungrouped embeddings with valid vectors"
            )

            return

        except Exception as e:
            logger.error(f"Error fetching ungrouped embeddings: {e}")
            raise

    def fetch_all_embeddings(
        self, 
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch all story embeddings regardless of grouping status.
        Only fetches embeddings from the last N days (configured via days_lookback).
        
        Args:
            limit: Optional maximum number of embeddings to fetch
            
        Returns:
            List of dicts with keys: id, news_url_id, embedding_vector, created_at
        """
        logger.info("Fetching all story embeddings...")
        
        try:
            cutoff_date = self._get_cutoff_date()
            logger.info(f"Filtering stories created after {cutoff_date} ({self.days_lookback} days)")
            
            embeddings: List[Dict] = []

            for batch in self._iter_all_embedding_batches(
                limit=limit,
                batch_size=1000,
            ):
                embeddings.extend(batch)

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

    def iter_grouping_embeddings(
        self,
        regroup: bool,
        limit: Optional[int] = None,
        batch_size: int = 200,
    ):
        """Yield story embeddings in batches for grouping workflows."""

        if batch_size <= 0:
            raise ValueError("Batch size must be a positive integer")

        if regroup:
            yield from self._iter_all_embedding_batches(
                limit=limit,
                batch_size=batch_size,
            )
        else:
            yield from self._iter_ungrouped_embedding_batches(
                limit=limit,
                batch_size=batch_size,
            )

    def _iter_ungrouped_embedding_batches(
        self,
        limit: Optional[int],
        batch_size: int,
    ):
        logger.info("Streaming ungrouped story embeddings from database...")

        page_size = max(batch_size, 1000)
        offset = 0
        yielded = 0
        cutoff_date = self._get_cutoff_date()

        while True:
            try:
                logger.info(
                    f"Fetching ungrouped embeddings at offset {offset} (page size {page_size})..."
                )
                # Use the proper database function instead of exec_sql
                response = self.client.rpc(
                    'get_ungrouped_embeddings',
                    {
                        'p_limit': page_size,
                        'p_offset': offset,
                        'p_cutoff_date': cutoff_date
                    }
                ).execute()

                if not response.data:
                    break

                parsed_batch = []
                for emb in response.data:
                    emb["embedding_vector"] = parse_vector(emb["embedding_vector"])
                    if emb["embedding_vector"] is not None:
                        parsed_batch.append(emb)

                batch_index = 0
                while batch_index < len(parsed_batch):
                    if limit is not None and yielded >= limit:
                        return

                    remaining = limit - yielded if limit is not None else batch_size
                    current_size = min(batch_size, remaining)
                    chunk = parsed_batch[batch_index: batch_index + current_size]

                    if not chunk:
                        break

                    yield chunk
                    yielded += len(chunk)
                    batch_index += current_size

                if limit is not None and yielded >= limit:
                    return

                if len(response.data) < page_size:
                    break

                offset += page_size

            except Exception as batch_error:
                logger.error(
                    f"Error fetching batch at offset {offset}: {batch_error}"
                )
                if "get_ungrouped_embeddings" in str(batch_error).lower() or "pgrst" in str(batch_error).lower():
                    logger.warning(
                        "Database function not available, falling back to fetch-all-and-filter approach"
                    )
                    yield from self._iter_ungrouped_fallback_batches(
                        limit=limit,
                        batch_size=batch_size,
                    )
                    return
                raise

        logger.info(f"Yielded {yielded} ungrouped embeddings")

    def _iter_all_embedding_batches(
        self,
        limit: Optional[int],
        batch_size: int,
    ):
        logger.info("Streaming all story embeddings from database...")

        cutoff_date = self._get_cutoff_date()
        page_size = max(batch_size, 1000)
        offset = 0
        yielded = 0

        while True:
            query = self.client.table("story_embeddings").select(
                "id, news_url_id, embedding_vector, created_at"
            ).not_.is_("embedding_vector", "null").gte(
                "created_at", cutoff_date
            ).order(
                "created_at", desc=False
            ).range(offset, offset + page_size - 1)

            response = query.execute()

            if not response.data:
                break

            parsed_batch = []
            for emb in response.data:
                emb["embedding_vector"] = parse_vector(emb["embedding_vector"])
                if emb["embedding_vector"] is not None:
                    parsed_batch.append(emb)

            batch_index = 0
            while batch_index < len(parsed_batch):
                if limit is not None and yielded >= limit:
                    return

                remaining = limit - yielded if limit is not None else batch_size
                current_size = min(batch_size, remaining)
                chunk = parsed_batch[batch_index: batch_index + current_size]

                if not chunk:
                    break

                yield chunk
                yielded += len(chunk)
                batch_index += current_size

            if limit is not None and yielded >= limit:
                return

            if len(response.data) < page_size:
                break

            offset += page_size

        logger.info(f"Yielded {yielded} total embeddings")
