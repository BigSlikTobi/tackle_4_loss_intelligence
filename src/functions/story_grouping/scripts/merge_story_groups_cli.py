#!/usr/bin/env python3
"""
CLI to merge highly similar story groups based on centroid similarity.

This is intended as a post-processing step when multiple grouping runs created
near-duplicate groups. It:
1) Loads recent active groups (bounded by --days and --group-limit)
2) Finds centroid pairs above --threshold
3) Merges each connected component into a primary group
4) Moves memberships, de-duplicates by fact/news URL, and archives merged groups

Usage:
    python merge_story_groups_cli.py --threshold 0.93 --days 14 --group-limit 4000
    python merge_story_groups_cli.py --dry-run --verbose
"""

import argparse
import logging
import sys

# Bootstrap path
from _bootstrap import *  # noqa

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.story_grouping.core.db import GroupMemberWriter, GroupWriter
from src.functions.story_grouping.core.pipelines.group_merge import GroupMergeService

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge similar story groups by centroid similarity",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.92,
        help="Similarity threshold for merging groups (default: 0.92)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Lookback window for active groups (default: 14)",
    )
    parser.add_argument(
        "--group-limit",
        type=int,
        help="Optional cap on number of groups loaded for merge analysis",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=200,
        help="Maximum centroid pairs to consider (sorted by similarity)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview merge actions without writing to database",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )

    args = parser.parse_args()

    load_env()
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)

    if not 0.0 <= args.threshold <= 1.0:
        logger.error("Threshold must be between 0.0 and 1.0")
        sys.exit(1)
    group_writer = GroupWriter(dry_run=args.dry_run, days_lookback=args.days)
    member_writer = GroupMemberWriter(dry_run=args.dry_run)

    merger = GroupMergeService(
        group_writer=group_writer,
        member_writer=member_writer,
        similarity_threshold=args.threshold,
        max_pairs=args.max_pairs,
        group_limit=args.group_limit,
        dry_run=args.dry_run,
    )

    result = merger.merge()

    print("\n" + "=" * 60)
    print("GROUP MERGE SUMMARY")
    print("=" * 60)
    print(f"Groups analyzed:      {result.groups_considered}")
    print(f"Merge components:     {result.merge_components}")
    print(f"Groups archived:      {result.groups_archived}")
    print(f"Memberships moved:    {result.memberships_moved}")
    print(f"Memberships skipped:  {result.memberships_skipped}")
    print(f"Errors:               {result.errors}")
    print("=" * 60)
    if args.dry_run:
        print("\n[DRY RUN] No database changes were made.")
    print()

    if result.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
