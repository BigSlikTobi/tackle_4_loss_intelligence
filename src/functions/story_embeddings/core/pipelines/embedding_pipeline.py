"""
Embedding generation pipeline.

Orchestrates the full workflow: fetch summaries -> generate embeddings -> write to DB.
"""

import logging
from datetime import datetime
from typing import Optional

from ..contracts import SummaryRecord, StoryEmbedding
from ..db import SummaryReader, EmbeddingWriter
from ..llm import OpenAIEmbeddingClient

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """
    Orchestrates the embedding generation workflow.

    Pipeline steps:
    1. Fetch summaries from context_summaries table (without embeddings)
    2. Generate embeddings using OpenAI API
    3. Write results to story_embeddings table

    Features:
    - Batch processing
    - Error handling with continue-on-error
    - Progress tracking
    - Dry-run support
    - Usage statistics
    """

    def __init__(
        self,
        openai_client: OpenAIEmbeddingClient,
        summary_reader: SummaryReader,
        embedding_writer: EmbeddingWriter,
        continue_on_error: bool = True,
    ):
        """
        Initialize the pipeline.

        Args:
            openai_client: Initialized OpenAI embedding client
            summary_reader: Summary reader instance
            embedding_writer: Embedding writer instance
            continue_on_error: If True, continue processing after errors
        """
        self.openai_client = openai_client
        self.summary_reader = summary_reader
        self.embedding_writer = embedding_writer
        self.continue_on_error = continue_on_error

        logger.info("Initialized EmbeddingPipeline")

    def process_summaries_without_embeddings(self, limit: Optional[int] = None) -> dict:
        """
        Process all summaries that don't have embeddings yet.

        Args:
            limit: Maximum number of summaries to process

        Returns:
            Dictionary with processing statistics:
                - total: Total summaries attempted
                - successful: Successfully embedded
                - failed: Failed to embed
                - skipped: Skipped (already have embeddings)
                - errors: List of error messages
                - usage: OpenAI API usage statistics
        """
        logger.info(f"Starting embedding generation (limit: {limit or 'none'})...")

        # Fetch summaries
        try:
            summaries = self.summary_reader.get_summaries_without_embeddings(limit=limit)
        except Exception as e:
            logger.error(f"Failed to fetch summaries: {e}", exc_info=True)
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [f"Failed to fetch summaries: {e}"],
                "usage": {},
            }

        if not summaries:
            logger.info("No summaries found without embeddings")
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [],
                "usage": self.openai_client.get_usage_stats(),
            }

        logger.info(f"Found {len(summaries)} summaries to process")

        # Process summaries
        return self.process_summary_batch(summaries)

    def process_summary_batch(self, summaries: list[SummaryRecord]) -> dict:
        """
        Process a batch of summaries.

        Args:
            summaries: List of SummaryRecord instances

        Returns:
            Processing statistics dictionary
        """
        stats = {
            "total": len(summaries),
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "embeddings": [],  # Store generated embeddings
        }

        embeddings = []

        for i, summary in enumerate(summaries, 1):
            logger.info(f"Processing summary {i}/{len(summaries)} (news_url_id: {summary.news_url_id})")

            try:
                # Check if already embedded (skip if exists)
                if self.embedding_writer.check_exists(summary.news_url_id):
                    logger.info(f"Skipping (already embedded): {summary.news_url_id}")
                    stats["skipped"] += 1
                    continue

                # Generate embedding
                result = self.openai_client.generate_embedding(summary.summary_text)

                # Create StoryEmbedding object
                embedding = StoryEmbedding(
                    news_url_id=summary.news_url_id,
                    embedding_vector=result["embedding"],
                    model_name=result["model"],
                    generated_at=datetime.utcnow(),
                    created_at=datetime.utcnow(),
                )

                embeddings.append(embedding)
                stats["successful"] += 1

                logger.info(
                    f"Successfully generated embedding {i}/{len(summaries)} "
                    f"(tokens: {result['tokens_used']}, time: {result['processing_time']:.2f}s)"
                )

            except Exception as e:
                error_msg = f"Failed to embed summary {summary.news_url_id}: {e}"
                logger.error(error_msg, exc_info=True)
                stats["failed"] += 1
                stats["errors"].append(error_msg)

                if not self.continue_on_error:
                    logger.error("Stopping pipeline due to error (continue_on_error=False)")
                    break

        # Write all embeddings in batch
        if embeddings:
            logger.info(f"Writing {len(embeddings)} embeddings to database...")
            write_stats = self.embedding_writer.write_embeddings(embeddings)

            # Update stats with write results
            if write_stats["failed"] > 0:
                stats["failed"] += write_stats["failed"]
                stats["successful"] -= write_stats["failed"]
                stats["errors"].extend(write_stats["errors"])

        # Get usage statistics
        usage_stats = self.openai_client.get_usage_stats()

        logger.info(
            f"Pipeline complete: {stats['successful']} successful, "
            f"{stats['failed']} failed, {stats['skipped']} skipped"
        )
        logger.info(
            f"API usage: {usage_stats['total_requests']} requests, "
            f"{usage_stats['total_tokens']} tokens, "
            f"${usage_stats['estimated_cost_usd']:.4f} estimated cost"
        )

        # Include embeddings and usage in return stats
        stats["embeddings"] = embeddings
        stats["usage"] = usage_stats

        return stats

    def get_progress_info(self) -> dict:
        """
        Get information about embedding progress.

        Returns:
            Dictionary with:
                - total_summaries: Total summaries in database
                - summaries_with_embeddings: Count with embeddings
                - summaries_without_embeddings: Count without embeddings
                - completion_percentage: Percentage complete
        """
        try:
            # Get counts
            without_count = self.summary_reader.count_summaries_without_embeddings()
            writer_stats = self.embedding_writer.get_stats()
            with_count = writer_stats["total_embeddings"]
            total = with_count + without_count

            # Calculate percentage
            completion_pct = (with_count / total * 100) if total > 0 else 0

            return {
                "total_summaries": total,
                "summaries_with_embeddings": with_count,
                "summaries_without_embeddings": without_count,
                "completion_percentage": round(completion_pct, 2),
            }

        except Exception as e:
            logger.error(f"Failed to get progress info: {e}")
            return {
                "total_summaries": 0,
                "summaries_with_embeddings": 0,
                "summaries_without_embeddings": 0,
                "completion_percentage": 0,
            }
