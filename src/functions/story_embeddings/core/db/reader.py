"""
Database reader for fetching summaries that need embeddings.

Reads from context_summaries table and identifies which summaries
don't have embeddings yet in the story_embeddings table.
"""

import logging
from typing import Optional



from src.shared.db.connection import get_supabase_client
from ..contracts import SummaryRecord

PAGE_SIZE = 1000  # Configurable constant for pagination
logger = logging.getLogger(__name__)


class SummaryReader:
    """
    Reader for fetching content summaries that need embeddings.

    Uses a strategy to identify summaries without embeddings:
    - Get all news_url_ids from story_embeddings
    - Filter context_summaries to exclude those IDs
    """

    def __init__(
        self,
        summaries_table: str = "context_summaries",
        embeddings_table: str = "story_embeddings",
    ):
        """
        Initialize the reader.

        Args:
            summaries_table: Name of the content summaries table
            embeddings_table: Name of the story embeddings table
        """
        self.summaries_table = summaries_table
        self.embeddings_table = embeddings_table
        self.client = get_supabase_client()
        logger.info(
            f"Initialized SummaryReader (summaries: {summaries_table}, embeddings: {embeddings_table})"
        )

    def get_summaries_without_embeddings(
        self, limit: Optional[int] = None
    ) -> list[SummaryRecord]:
        """
        Fetch summaries that don't have embeddings yet.

        Strategy:
        1. Get all news_url_ids from story_embeddings table
        2. Query context_summaries and filter out already-embedded IDs
        3. Return up to 'limit' summaries

        Args:
            limit: Maximum number of summaries to return

        Returns:
            List of SummaryRecord instances
        """
        try:
            # Step 1: Get all news_url_ids that already have embeddings
            embedded_ids = self._get_embedded_ids()
            logger.debug(f"Found {len(embedded_ids)} summaries with existing embeddings")

            # Step 2: Fetch summaries without embeddings
            summaries = self._fetch_unembedded_summaries(embedded_ids, limit)
            
            logger.info(f"Found {len(summaries)} summaries without embeddings")
            return summaries

        except Exception as e:
            logger.error(f"Failed to fetch summaries without embeddings: {e}", exc_info=True)
            raise

    def _get_embedded_ids(self) -> set[str]:
        """
        Get all news_url_ids that already have embeddings.

        Returns:
            Set of news_url_ids
        """
        embedded_ids = set()
        try:
            page_size = PAGE_SIZE
            offset = 0
            
            while True:
                response = (
                    self.client.table(self.embeddings_table)
                    .select("news_url_id")
                    .range(offset, offset + page_size - 1)
                    .execute()
                )

                if not response.data:
                    break

                embedded_ids.update(row["news_url_id"] for row in response.data)

                # If we got less than page_size, we've reached the end
                if len(response.data) < page_size:
                    break

                offset += page_size

        except Exception as e:
            # Table doesn't exist yet or is empty - all summaries need embeddings
            logger.debug(
                f"story_embeddings table not accessible (may not exist yet): {e}"
            )
            embedded_ids = set()

        return embedded_ids

    def _fetch_unembedded_summaries(
        self, embedded_ids: set[str], limit: Optional[int] = None
    ) -> list[SummaryRecord]:
        """
        Fetch summaries that are not in the embedded_ids set.

        Args:
            embedded_ids: Set of news_url_ids that already have embeddings
            limit: Maximum number to return

        Returns:
            List of SummaryRecord instances
        """
        summaries = []
        page_size = PAGE_SIZE
        offset = 0

        while True:
            query = (
                self.client.table(self.summaries_table)
                .select("news_url_id, summary_text, created_at")
                .order("created_at", desc=True)
                .range(offset, offset + page_size - 1)
            )

            response = query.execute()

            if not response.data:
                break

            # Filter out summaries that already have embeddings
            batch = [
                SummaryRecord.from_dict(row)
                for row in response.data
                if row["news_url_id"] not in embedded_ids
            ]

            summaries.extend(batch)

            # Check if we've reached the limit
            if limit and len(summaries) >= limit:
                summaries = summaries[:limit]
                break

            # If we got less than page_size, we've reached the end
            if len(response.data) < page_size:
                break

            offset += page_size

        return summaries

    def get_summary_by_news_url_id(self, news_url_id: str) -> Optional[SummaryRecord]:
        """
        Fetch a specific summary by news_url_id.

        Args:
            news_url_id: UUID of the news URL

        Returns:
            SummaryRecord instance or None if not found
        """
        try:
            response = (
                self.client.table(self.summaries_table)
                .select("news_url_id, summary_text, created_at")
                .eq("news_url_id", news_url_id)
                .execute()
            )

            if response.data:
                return SummaryRecord.from_dict(response.data[0])
            return None

        except Exception as e:
            logger.error(f"Failed to fetch summary for news_url_id {news_url_id}: {e}")
            raise

    def count_summaries_without_embeddings(self) -> int:
        """
        Count how many summaries don't have embeddings yet.

        Returns:
            Count of summaries without embeddings
        """
        try:
            # Get embedded IDs
            embedded_ids = self._get_embedded_ids()

            # Count total summaries
            total_summaries = 0
            page_size = PAGE_SIZE
            offset = 0

            while True:
                response = (
                    self.client.table(self.summaries_table)
                    .select("news_url_id")
                    .range(offset, offset + page_size - 1)
                    .execute()
                )

                if not response.data:
                    break

                total_summaries += len(response.data)

                if len(response.data) < page_size:
                    break

                offset += page_size

            # Calculate difference
            count = total_summaries - len(embedded_ids)
            logger.info(f"Total summaries without embeddings: {count}")
            return count

        except Exception as e:
            logger.error(f"Failed to count summaries without embeddings: {e}")
            raise
