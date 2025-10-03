"""
Database reader for news_urls table.

Provides functionality to read URLs that need summarization.
"""

import logging
from typing import Optional

from src.shared.db.connection import get_supabase_client
from ..contracts import NewsUrlRecord

logger = logging.getLogger(__name__)


class NewsUrlReader:
    """
    Reader for fetching news URLs from the news_urls table.

    Provides methods to query URLs that need summarization.
    """

    def __init__(self, table_name: str = "news_urls"):
        """
        Initialize the reader.

        Args:
            table_name: Name of the news URLs table
        """
        self.table_name = table_name
        self.client = get_supabase_client()
        logger.info(f"Initialized NewsUrlReader for table: {table_name}")

    def get_unsummarized_urls(self, limit: Optional[int] = None) -> list[NewsUrlRecord]:
        """
        Fetch URLs that don't have summaries yet.

        Args:
            limit: Maximum number of URLs to return

        Returns:
            List of NewsUrlRecord instances
        """
        try:
            # First, check if context_summaries table exists by trying to get summarized IDs
            # Need to paginate to get ALL summarized IDs (not just first 1000)
            summarized_ids = set()
            try:
                page_size = 1000
                offset = 0
                while True:
                    response = (
                        self.client.table("context_summaries")
                        .select("news_url_id")
                        .range(offset, offset + page_size - 1)
                        .execute()
                    )
                    
                    if not response.data:
                        break
                    
                    summarized_ids.update(row["news_url_id"] for row in response.data)
                    
                    # If we got less than page_size, we've reached the end
                    if len(response.data) < page_size:
                        break
                    
                    offset += page_size
                
                logger.debug(f"Found {len(summarized_ids)} already summarized URLs")
            except Exception as e:
                # Table doesn't exist yet or is empty - all URLs are unsummarized
                logger.debug(f"context_summaries table not accessible (may not exist yet): {e}")
                summarized_ids = set()

            # Fetch news URLs (also need to paginate if no limit specified)
            unsummarized = []
            page_size = 1000
            offset = 0
            
            while True:
                query = (
                    self.client.table(self.table_name)
                    .select("*")
                    .order("publication_date", desc=True)
                    .range(offset, offset + page_size - 1)
                )

                response = query.execute()
                
                if not response.data:
                    break
                
                # Filter out URLs that are already summarized
                batch_unsummarized = [
                    NewsUrlRecord.from_dict(row) 
                    for row in response.data 
                    if row["id"] not in summarized_ids
                ]
                
                unsummarized.extend(batch_unsummarized)
                
                # If we have enough unsummarized URLs, stop fetching
                if limit and len(unsummarized) >= limit:
                    unsummarized = unsummarized[:limit]
                    break
                
                # If we got less than page_size, we've reached the end
                if len(response.data) < page_size:
                    break
                
                offset += page_size

            logger.info(f"Fetched {len(unsummarized)} unsummarized URLs (filtered from {len(summarized_ids)} already summarized)")
            return unsummarized

        except Exception as e:
            logger.error(f"Failed to fetch unsummarized URLs: {e}", exc_info=True)
            raise

    def get_urls_by_ids(self, url_ids: list[str]) -> list[NewsUrlRecord]:
        """
        Fetch specific URLs by their IDs.

        Args:
            url_ids: List of UUID strings

        Returns:
            List of NewsUrlRecord instances
        """
        try:
            response = self.client.table(self.table_name).select("*").in_("id", url_ids).execute()

            records = [NewsUrlRecord.from_dict(row) for row in response.data]
            logger.info(f"Fetched {len(records)} URLs by IDs")
            return records

        except Exception as e:
            logger.error(f"Failed to fetch URLs by IDs: {e}", exc_info=True)
            raise

    def get_urls_by_publisher(
        self, publisher: str, limit: Optional[int] = None, unsummarized_only: bool = True
    ) -> list[NewsUrlRecord]:
        """
        Fetch URLs from a specific publisher.

        Args:
            publisher: Publisher name (e.g., "ESPN")
            limit: Maximum number of URLs to return
            unsummarized_only: If True, only return URLs without summaries

        Returns:
            List of NewsUrlRecord instances
        """
        try:
            # Get summarized IDs if filtering for unsummarized only (with pagination)
            summarized_ids = set()
            if unsummarized_only:
                try:
                    page_size = 1000
                    offset = 0
                    while True:
                        response = (
                            self.client.table("context_summaries")
                            .select("news_url_id")
                            .range(offset, offset + page_size - 1)
                            .execute()
                        )
                        
                        if not response.data:
                            break
                        
                        summarized_ids.update(row["news_url_id"] for row in response.data)
                        
                        if len(response.data) < page_size:
                            break
                        
                        offset += page_size
                    
                    logger.debug(f"Found {len(summarized_ids)} already summarized URLs")
                except Exception as e:
                    logger.debug(f"context_summaries table not accessible: {e}")

            # Query by publisher with pagination
            records = []
            page_size = 1000
            offset = 0
            
            while True:
                query = (
                    self.client.table(self.table_name)
                    .select("*")
                    .eq("publisher", publisher)
                    .order("publication_date", desc=True)
                    .range(offset, offset + page_size - 1)
                )

                response = query.execute()
                
                if not response.data:
                    break
                
                # Filter if needed
                batch_records = [NewsUrlRecord.from_dict(row) for row in response.data]
                if unsummarized_only and summarized_ids:
                    batch_records = [r for r in batch_records if r.id not in summarized_ids]
                
                records.extend(batch_records)
                
                # If we have enough records, stop fetching
                if limit and len(records) >= limit:
                    records = records[:limit]
                    break
                
                # If we got less than page_size, we've reached the end
                if len(response.data) < page_size:
                    break
                
                offset += page_size

            logger.info(f"Fetched {len(records)} URLs from publisher: {publisher}")
            return records

        except Exception as e:
            logger.error(f"Failed to fetch URLs by publisher: {e}", exc_info=True)
            raise
    def get_all_urls(self, limit: Optional[int] = None) -> list[NewsUrlRecord]:
        """
        Fetch all URLs from the table.

        Args:
            limit: Maximum number of URLs to return

        Returns:
            List of NewsUrlRecord instances
        """
        try:
            query = self.client.table(self.table_name).select("*").order("publication_date", desc=True)

            if limit:
                query = query.limit(limit)

            response = query.execute()

            records = [NewsUrlRecord.from_dict(row) for row in response.data]
            logger.info(f"Fetched {len(records)} URLs (total)")
            return records

        except Exception as e:
            logger.error(f"Failed to fetch all URLs: {e}", exc_info=True)
            raise
