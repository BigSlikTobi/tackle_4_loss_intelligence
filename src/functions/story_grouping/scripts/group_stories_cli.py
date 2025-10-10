#!/usr/bin/env python3
"""
CLI script for grouping similar stories based on embeddings.

Groups stories by analyzing embedding vectors and clustering similar content
together. Supports both creating new groups and adding stories to existing groups.

Usage:
    python group_stories_cli.py [--dry-run] [--limit N] [--verbose]
    python group_stories_cli.py --regroup          # Regroup all stories
    python group_stories_cli.py --progress         # Show progress statistics
    python group_stories_cli.py --threshold 0.90   # Use custom threshold
"""

import argparse
import logging
import sys
from datetime import datetime

# Bootstrap path
from _bootstrap import *  # noqa

from src.shared.utils.logging import setup_logging
from src.shared.utils.env import load_env
from src.functions.story_grouping.core.db import (
    EmbeddingReader,
    GroupWriter,
    GroupMemberWriter,
)
from src.functions.story_grouping.core.pipelines import GroupingPipeline

logger = logging.getLogger(__name__)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Group similar stories based on embeddings",
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
        help="Maximum number of stories to process",
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
        "--threshold",
        type=float,
        help="Similarity threshold for grouping (0.0-1.0, default: 0.85)",
    )
    
    parser.add_argument(
        "--regroup",
        action="store_true",
        help="Clear existing groups and regroup all stories",
    )
    
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Number of days to look back for stories and groups (default: 14)",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)

    # Load environment variables
    load_env()

    logger.info("=" * 80)
    logger.info("Story Grouping")
    logger.info("=" * 80)
    
    # Validate threshold if provided
    if args.threshold is not None:
        if not 0.0 <= args.threshold <= 1.0:
            logger.error("Threshold must be between 0.0 and 1.0")
            sys.exit(1)

    try:
        # Initialize components with date filtering
        embedding_reader = EmbeddingReader(days_lookback=args.days)
        group_writer = GroupWriter(dry_run=args.dry_run, days_lookback=args.days)
        member_writer = GroupMemberWriter(dry_run=args.dry_run)
        
        pipeline = GroupingPipeline(
            embedding_reader=embedding_reader,
            group_writer=group_writer,
            member_writer=member_writer,
            similarity_threshold=args.threshold,
            continue_on_error=True,
        )

        # Handle progress mode
        if args.progress:
            logger.info("Fetching progress information...")
            progress = pipeline.get_progress_info()
            
            print("\n" + "=" * 60)
            print("GROUPING PROGRESS")
            print("=" * 60)
            print(f"Total stories:        {progress['total_stories']:,}")
            print(f"Grouped stories:      {progress['grouped_stories']:,}")
            print(f"Ungrouped stories:    {progress['ungrouped_stories']:,}")
            print(f"Total groups:         {progress['total_groups']:,}")
            print(f"Active groups:        {progress['active_groups']:,}")
            print(f"Avg group size:       {progress['avg_group_size']:.2f}")
            print("=" * 60)
            
            # Calculate completion percentage
            if progress['total_stories'] > 0:
                pct_complete = (
                    progress['grouped_stories'] / progress['total_stories'] * 100
                )
                print(f"Completion:           {pct_complete:.1f}%")
            
            print("=" * 60 + "\n")
            
            sys.exit(0)
        
        # Validate configuration
        logger.info("Validating configuration...")
        pipeline.validate_configuration()
        
        # Show configuration
        logger.info("")
        logger.info("Configuration:")
        logger.info(f"  Similarity threshold: {pipeline.similarity_threshold}")
        logger.info(f"  Dry run:              {args.dry_run}")
        logger.info(f"  Regroup mode:         {args.regroup}")
        if args.limit:
            logger.info(f"  Limit:                {args.limit}")
        logger.info("")
        
        # Warning for regroup mode
        if args.regroup:
            logger.warning("=" * 80)
            logger.warning("REGROUP MODE: This will clear ALL existing groups!")
            logger.warning("=" * 80)
            
            if not args.dry_run:
                response = input("\nAre you sure? Type 'yes' to continue: ")
                if response.lower() != "yes":
                    logger.info("Cancelled by user")
                    sys.exit(0)
        
        # Run pipeline
        start_time = datetime.now()
        
        results = pipeline.run(
            limit=args.limit,
            regroup=args.regroup,
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # Display summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Stories processed:     {results['stories_processed']:,}")
        print(f"Groups created:        {results['groups_created']:,}")
        print(f"Groups updated:        {results['groups_updated']:,}")
        print(f"Memberships added:     {results['memberships_added']:,}")
        print(f"Errors:                {results['errors']:,}")
        print(f"Elapsed time:          {elapsed:.1f}s")
        print("=" * 60)
        
        if args.dry_run:
            print("\n[DRY RUN] No changes were made to the database.")
        
        print()
        
        # Exit with error code if there were errors
        if results['errors'] > 0:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
