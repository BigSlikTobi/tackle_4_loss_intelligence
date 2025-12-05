#!/usr/bin/env python3
"""Manually clean up stale batch jobs.

This script allows you to manually mark stale batches as failed when
they get stuck and block the pipeline.

Examples:
    # Check for stale CREATING batches (dry-run)
    python scripts/cleanup_stale_batches.py --dry-run
    
    # Mark CREATING batches stale after 30 minutes
    python scripts/cleanup_stale_batches.py --max-age 30
    
    # Force cleanup specific stage
    python scripts/cleanup_stale_batches.py --stage facts --max-age 20
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.shared.batch.tracking import BatchTracker, BatchStage

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Clean up stale batch creation jobs")
    parser.add_argument(
        "--max-age",
        type=int,
        default=30,
        help="Consider batches stale after this many minutes in CREATING status (default: 30)",
    )
    parser.add_argument(
        "--stage",
        type=str,
        choices=["facts", "knowledge", "summary"],
        help="Only check specific stage",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be marked stale without doing it",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()
    
    # Setup
    load_env()
    setup_logging(level="DEBUG" if args.verbose else "INFO")
    
    logger.info("=" * 60)
    logger.info("BATCH CLEANUP - Stale Creation Detection")
    logger.info("=" * 60)
    logger.info(f"Max age: {args.max_age} minutes")
    logger.info(f"Stage filter: {args.stage or 'all'}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 60)
    
    # Get stale batches
    tracker = BatchTracker()
    stage_filter = BatchStage[args.stage.upper()] if args.stage else None
    stale_batches = tracker.get_stale_creating_batches(
        max_age_minutes=args.max_age,
        stage=stage_filter,
    )
    
    if not stale_batches:
        logger.info("✅ No stale CREATING batches found")
        return
    
    logger.warning(f"Found {len(stale_batches)} stale CREATING batches:")
    print("\n" + "=" * 60)
    
    for batch in stale_batches:
        age_minutes = (
            (batch.created_at.timestamp() - batch.created_at.timestamp()) / 60
            if batch.created_at else 0
        )
        print(f"\n🔴 {batch.batch_id}")
        print(f"   Stage: {batch.stage.value}")
        print(f"   Status: {batch.status.value}")
        print(f"   Created: {batch.created_at}")
        print(f"   Model: {batch.model}")
        if batch.metadata:
            print(f"   Metadata: {batch.metadata}")
    
    print("\n" + "=" * 60)
    
    if args.dry_run:
        logger.info("DRY RUN - No changes made")
        logger.info(f"Would mark {len(stale_batches)} batches as failed")
        return
    
    # Confirm
    response = input(f"\nMark {len(stale_batches)} batches as failed? [y/N]: ")
    if response.lower() != 'y':
        logger.info("Cancelled by user")
        return
    
    # Mark stale
    for batch in stale_batches:
        logger.info(f"Marking {batch.batch_id} as failed...")
        tracker.mark_failed(
            batch.batch_id,
            error_message=f"Stuck in CREATING status for >{args.max_age} minutes (manual cleanup)",
            increment_retry=False,
        )
    
    logger.info(f"✅ Marked {len(stale_batches)} batches as failed")


if __name__ == "__main__":
    main()
