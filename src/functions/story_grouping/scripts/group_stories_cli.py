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
    python group_stories_cli.py --preview-ids ID1 ID2 ...
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List

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
        "--batch-size",
        type=int,
        help="Batch size for grouping/writes (default: env GROUPING_BATCH_SIZE or 200)",
    )

    parser.add_argument(
        "--max-run-size",
        type=int,
        default=int(os.getenv("GROUPING_MAX_RUN_SIZE", "10000")),
        help=(
            "Safety cap for number of embeddings to process when not forced "
            "(default: env GROUPING_MAX_RUN_SIZE or 10000)"
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass safety cap and process all requested embeddings",
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
        help="Similarity threshold for grouping (0.0-1.0, default: 0.88)",
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

    parser.add_argument(
        "--preview-ids",
        nargs="+",
        help="Preview grouping for the provided news_url_id values",
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
        preview_ids: List[str] = []
        if args.preview_ids:
            for token in args.preview_ids:
                preview_ids.extend(
                    [value.strip() for value in token.split(",") if value.strip()]
                )

        writers_dry_run = args.dry_run or bool(preview_ids)

        embedding_reader = EmbeddingReader(
            days_lookback=args.days,
            table_name="news_urls_embeddings",
            schema_name="vector_embeddings",
            is_legacy_schema=False,
            vector_column="vector",
            grouping_key_column="id",
            resolve_uuid=True
        )
        group_writer = GroupWriter(
            dry_run=writers_dry_run, 
            days_lookback=args.days,
            schema_name="vector_embeddings"
        )
        member_writer = GroupMemberWriter(
            dry_run=writers_dry_run,
            schema_name="vector_embeddings"
        )

        pipeline = GroupingPipeline(
            embedding_reader=embedding_reader,
            group_writer=group_writer,
            member_writer=member_writer,
            similarity_threshold=args.threshold,
            continue_on_error=True,
            batch_size=args.batch_size,
        )
        effective_limit = args.limit

        if not preview_ids and not args.progress:
            try:
                embedding_stats = embedding_reader.get_embedding_stats()
                available = (
                    embedding_stats["embeddings_with_vectors"]
                    if args.regroup
                    else embedding_stats["ungrouped_count"]
                )
                planned = effective_limit if effective_limit is not None else available

                if planned > args.max_run_size and not args.force:
                    if effective_limit is None:
                        effective_limit = args.max_run_size
                        logger.warning(
                            "Capping run to %s embeddings to avoid overloading Supabase "
                            "(available: %s). Use --limit for a smaller slice or "
                            "--force to process everything.",
                            args.max_run_size,
                            available,
                        )
                    else:
                        logger.error(
                            "Requested limit %s exceeds safety cap %s. "
                            "Lower the limit or pass --force to override.",
                            planned,
                            args.max_run_size,
                        )
                        sys.exit(1)
                elif planned > args.max_run_size and args.force:
                    logger.warning(
                        "Force enabled: proceeding with %s embeddings (safety cap %s).",
                        planned,
                        args.max_run_size,
                    )
            except Exception as stats_error:
                logger.warning(
                    "Could not fetch embedding counts for safety guard: %s",
                    stats_error,
                )

        if preview_ids:
            logger.info("Running preview mode for %s news_url_ids", len(preview_ids))

            existing_groups = group_writer.get_active_groups()
            pipeline.grouper.clear_groups()
            pipeline.grouper.load_existing_groups(existing_groups)

            embeddings = embedding_reader.fetch_embeddings_by_news_url_ids(preview_ids)
            found_ids = {item["news_url_id"] for item in embeddings}
            missing_ids = [news_id for news_id in preview_ids if news_id not in found_ids]

            if not embeddings:
                logger.error("No embeddings found for requested IDs")
                if missing_ids:
                    print("\nMissing embeddings for:")
                    for missing in missing_ids:
                        print(f"  - {missing}")
                sys.exit(1)

            preview_rows = []
            new_group_labels: Dict[int, str] = {}
            new_group_counter = 0

            for story in embeddings:
                result = pipeline.grouper.assign_story(
                    story["news_url_id"], story["embedding_vector"]
                )

                group_obj = result.group
                if group_obj.group_id:
                    group_label = group_obj.group_id
                    group_status = "existing"
                else:
                    group_key = id(group_obj)
                    if group_key not in new_group_labels:
                        new_group_counter += 1
                        new_group_labels[group_key] = f"NEW-{new_group_counter}"
                    group_label = new_group_labels[group_key]
                    group_status = "new"

                row = {
                    "news_url_id": story["news_url_id"],
                    "group": group_label,
                    "status": group_status,
                    "similarity": result.similarity,
                    "previous_size": result.previous_member_count,
                    "current_size": group_obj.member_count,
                    "added": result.added_to_group,
                }
                preview_rows.append(row)

            print("\n" + "=" * 80)
            print("GROUPING PREVIEW RESULTS")
            print("=" * 80)
            print(
                f"Threshold: {pipeline.similarity_threshold:.2f} | IDs processed: {len(preview_rows)}"
            )
            print("-" * 80)
            header = (
                f"{'news_url_id':<36} {'group':<18} {'status':<9} "
                f"{'similarity':>11} {'prev_size':>10} {'new_size':>10} {'action':<8}"
            )
            print(header)
            print("-" * 80)

            for row in preview_rows:
                action = "added" if row["added"] else "skip"
                print(
                    f"{row['news_url_id']:<36} {row['group']:<18} {row['status']:<9} "
                    f"{row['similarity']:>11.4f} {row['previous_size']:>10} "
                    f"{row['current_size']:>10} {action:<8}"
                )

            if missing_ids:
                print("\nMissing embeddings for:")
                for missing in missing_ids:
                    print(f"  - {missing}")

            print("=" * 80 + "\n")

            sys.exit(0)

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
        logger.info(f"  Max run size:         {args.max_run_size}")
        if effective_limit:
            logger.info(f"  Limit:                {effective_limit}")
        if args.batch_size:
            logger.info(f"  Batch size:           {args.batch_size}")
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
            limit=effective_limit,
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
