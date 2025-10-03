"""
Content summarization pipeline.

Orchestrates the full workflow: fetch URLs -> summarize -> write results.
"""

import logging
from datetime import datetime
from typing import Optional

from ..contracts import ContentSummary, NewsUrlRecord
from ..db import NewsUrlReader, SummaryWriter
from ..llm import GeminiClient

logger = logging.getLogger(__name__)


class SummarizationPipeline:
    """
    Orchestrates the content summarization workflow.

    Pipeline steps:
    1. Fetch URLs from news_urls table
    2. Generate summaries using Gemini API
    3. Write results to context_summaries table

    Features:
    - Batch processing
    - Error handling with continue-on-error
    - Progress tracking
    - Dry-run support
    """

    def __init__(
        self,
        gemini_client: GeminiClient,
        url_reader: NewsUrlReader,
        summary_writer: SummaryWriter,
        continue_on_error: bool = True,
    ):
        """
        Initialize the pipeline.

        Args:
            gemini_client: Initialized Gemini client
            url_reader: URL reader instance
            summary_writer: Summary writer instance
            continue_on_error: If True, continue processing after errors
        """
        self.gemini_client = gemini_client
        self.url_reader = url_reader
        self.summary_writer = summary_writer
        self.continue_on_error = continue_on_error

        logger.info("Initialized SummarizationPipeline")

    def process_unsummarized_urls(self, limit: Optional[int] = None) -> dict:
        """
        Process all URLs that don't have summaries yet.

        Args:
            limit: Maximum number of URLs to process

        Returns:
            Dictionary with processing statistics:
                - total: Total URLs attempted
                - successful: Successfully summarized
                - failed: Failed to summarize
                - skipped: Skipped (already exist)
                - errors: List of error messages
        """
        logger.info(f"Starting unsummarized URL processing (limit: {limit or 'none'})...")

        # Fetch URLs
        try:
            urls = self.url_reader.get_unsummarized_urls(limit=limit)
        except Exception as e:
            logger.error(f"Failed to fetch URLs: {e}", exc_info=True)
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [f"Failed to fetch URLs: {e}"],
            }

        if not urls:
            logger.info("No unsummarized URLs found")
            return {"total": 0, "successful": 0, "failed": 0, "skipped": 0, "errors": []}

        logger.info(f"Found {len(urls)} URLs to process")

        # Process URLs
        return self.process_url_batch(urls)

    def process_url_batch(self, urls: list[NewsUrlRecord]) -> dict:
        """
        Process a batch of URLs.

        Args:
            urls: List of NewsUrlRecord instances

        Returns:
            Processing statistics dictionary
        """
        stats = {
            "total": len(urls),
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "summaries": [],  # Store generated summaries
        }

        summaries = []

        for i, url_record in enumerate(urls, 1):
            logger.info(f"Processing URL {i}/{len(urls)}: {url_record.url}")

            try:
                # Check if already summarized (skip if exists)
                if self.summary_writer.check_exists(url_record.id):
                    logger.info(f"Skipping URL (already summarized): {url_record.url}")
                    stats["skipped"] += 1
                    continue

                # Generate summary
                result = self.gemini_client.summarize_url(
                    url=url_record.url,
                    title=url_record.title,
                )

                # Create ContentSummary object
                summary = ContentSummary(
                    news_url_id=url_record.id,
                    summary=result["summary"],
                    key_points=result["key_points"],
                    players_mentioned=result["players_mentioned"],
                    teams_mentioned=result["teams_mentioned"],
                    game_references=result["game_references"],
                    article_type=result["article_type"],
                    sentiment=result["sentiment"],
                    content_quality=result["content_quality"],
                    injury_updates=result["injury_updates"],
                    model_used=result["metadata"]["model_used"],
                    tokens_used=result["metadata"]["tokens_used"],
                    processing_time_seconds=result["metadata"]["processing_time_seconds"],
                    url_retrieval_status=result["metadata"]["url_retrieval_status"],
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )

                summaries.append(summary)
                stats["successful"] += 1

                logger.info(
                    f"Successfully summarized URL {i}/{len(urls)} "
                    f"(tokens: {summary.tokens_used}, time: {summary.processing_time_seconds:.2f}s)"
                )

            except Exception as e:
                error_msg = f"Failed to summarize {url_record.url}: {e}"
                logger.error(error_msg, exc_info=True)
                stats["failed"] += 1
                stats["errors"].append(error_msg)

                if not self.continue_on_error:
                    logger.error("Stopping pipeline due to error (continue_on_error=False)")
                    break

        # Write all summaries in batch
        if summaries:
            logger.info(f"Writing {len(summaries)} summaries to database...")
            write_stats = self.summary_writer.write_summaries(summaries)

            # Update stats with write results
            if write_stats["failed"] > 0:
                stats["failed"] += write_stats["failed"]
                stats["successful"] -= write_stats["failed"]
                stats["errors"].extend(write_stats["errors"])

        logger.info(
            f"Pipeline complete: {stats['successful']} successful, "
            f"{stats['failed']} failed, {stats['skipped']} skipped"
        )

        # Include summaries in return stats
        stats["summaries"] = summaries

        return stats

    def process_by_publisher(self, publisher: str, limit: Optional[int] = None) -> dict:
        """
        Process URLs from a specific publisher.

        Args:
            publisher: Publisher name (e.g., "ESPN")
            limit: Maximum number of URLs to process

        Returns:
            Processing statistics dictionary
        """
        logger.info(f"Processing URLs from publisher: {publisher} (limit: {limit or 'none'})...")

        try:
            urls = self.url_reader.get_urls_by_publisher(
                publisher=publisher,
                limit=limit,
                unsummarized_only=True,
            )
        except Exception as e:
            logger.error(f"Failed to fetch URLs for publisher {publisher}: {e}", exc_info=True)
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [f"Failed to fetch URLs: {e}"],
            }

        if not urls:
            logger.info(f"No unsummarized URLs found for publisher: {publisher}")
            return {"total": 0, "successful": 0, "failed": 0, "skipped": 0, "errors": []}

        return self.process_url_batch(urls)

    def process_by_ids(self, url_ids: list[str]) -> dict:
        """
        Process specific URLs by their IDs.

        Args:
            url_ids: List of news_url UUID strings

        Returns:
            Processing statistics dictionary
        """
        logger.info(f"Processing {len(url_ids)} URLs by ID...")

        try:
            urls = self.url_reader.get_urls_by_ids(url_ids)
        except Exception as e:
            logger.error(f"Failed to fetch URLs by IDs: {e}", exc_info=True)
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [f"Failed to fetch URLs: {e}"],
            }

        if not urls:
            logger.warning("No URLs found for provided IDs")
            return {"total": 0, "successful": 0, "failed": 0, "skipped": 0, "errors": []}

        return self.process_url_batch(urls)
