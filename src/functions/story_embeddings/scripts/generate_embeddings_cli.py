#!/usr/bin/env python3
"""
CLI script for generating story embeddings.

Generates vector embeddings for content summaries using OpenAI's
text-embedding-3-small model.

Usage:
    python generate_embeddings_cli.py [--dry-run] [--limit N] [--verbose]
    python generate_embeddings_cli.py --progress  # Show progress statistics
"""

import argparse
import logging
import sys
from datetime import datetime

# Bootstrap path
from _bootstrap import *  # noqa

from src.shared.utils.logging import setup_logging
from src.shared.utils.env import load_env
from src.functions.story_embeddings.core.db import SummaryReader, EmbeddingWriter
from src.functions.story_embeddings.core.llm import OpenAIEmbeddingClient
from src.functions.story_embeddings.core.pipelines import EmbeddingPipeline

logger = logging.getLogger(__name__)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate embeddings for story summaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of summaries to process",
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (DEBUG level)",
    )
    
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress statistics and exit",
    )
    
    parser.add_argument(
        "--model",
        type=str,
        default="text-embedding-3-small",
        help="OpenAI embedding model to use (default: text-embedding-3-small)",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)

    # Load environment variables
    load_env()

    logger.info("=" * 80)
    logger.info("Story Embeddings Generator")
    logger.info("=" * 80)

    try:
        # Initialize components
        openai_client = OpenAIEmbeddingClient(model=args.model)
        summary_reader = SummaryReader()
        embedding_writer = EmbeddingWriter(dry_run=args.dry_run)
        
        pipeline = EmbeddingPipeline(
            openai_client=openai_client,
            summary_reader=summary_reader,
            embedding_writer=embedding_writer,
            continue_on_error=True,
        )

        # Handle progress mode
        if args.progress:
            logger.info("Fetching progress information...")
            progress = pipeline.get_progress_info()
            
            print("\n" + "=" * 60)
            print("EMBEDDING PROGRESS")
            print("=" * 60)
            print(f"Total Summaries:                {progress['total_summaries']}")
            print(f"With Embeddings:                {progress['summaries_with_embeddings']}")
            print(f"Without Embeddings:             {progress['summaries_without_embeddings']}")
            print(f"Completion:                     {progress['completion_percentage']}%")
            print("=" * 60 + "\n")
            
            return 0

        # Dry-run notice
        if args.dry_run:
            logger.warning("DRY-RUN MODE: No changes will be made to the database")

        # Show configuration
        logger.info(f"Model:         {args.model}")
        logger.info(f"Limit:         {args.limit or 'none'}")
        logger.info(f"Dry Run:       {args.dry_run}")
        logger.info("")

        # Run pipeline
        start_time = datetime.now()
        logger.info(f"Starting embedding generation at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        stats = pipeline.process_summaries_without_embeddings(limit=args.limit)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Print summary
        print("\n" + "=" * 80)
        print("EMBEDDING GENERATION SUMMARY")
        print("=" * 80)
        print(f"Total Processed:          {stats['total']}")
        print(f"Successful:               {stats['successful']}")
        print(f"Failed:                   {stats['failed']}")
        print(f"Skipped:                  {stats['skipped']}")
        print(f"Duration:                 {duration:.2f}s")
        
        if stats.get('usage'):
            usage = stats['usage']
            print(f"\nOpenAI API Usage:")
            print(f"  Total Requests:         {usage['total_requests']}")
            print(f"  Total Tokens:           {usage['total_tokens']}")
            print(f"  Estimated Cost:         ${usage['estimated_cost_usd']:.4f}")
        
        if stats['errors']:
            print(f"\nErrors ({len(stats['errors'])}):")
            for i, error in enumerate(stats['errors'][:5], 1):
                print(f"  {i}. {error}")
            if len(stats['errors']) > 5:
                print(f"  ... and {len(stats['errors']) - 5} more")
        
        print("=" * 80 + "\n")

        # Return appropriate exit code
        if stats['failed'] > 0:
            logger.warning(f"Completed with {stats['failed']} failures")
            return 1
        else:
            logger.info("Embedding generation completed successfully")
            return 0

    except KeyboardInterrupt:
        logger.warning("\nOperation cancelled by user")
        return 130
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
