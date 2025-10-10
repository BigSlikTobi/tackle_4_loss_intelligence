"""
Fix member_count for all story_groups.

This script updates the member_count column in story_groups to match the actual
number of members in story_group_members table. It handles pagination properly
to process all groups.
"""

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client

logger = logging.getLogger(__name__)


def fix_member_counts(dry_run: bool = False) -> dict:
    """
    Fix member_count for all story_groups.
    
    Args:
        dry_run: If True, only report what would be updated
        
    Returns:
        Dict with statistics
    """
    client = get_supabase_client()
    
    logger.info("=" * 80)
    logger.info("Fixing member_count for all story_groups")
    logger.info("=" * 80)
    
    stats = {
        "total_groups": 0,
        "groups_updated": 0,
        "groups_correct": 0,
        "errors": 0,
    }
    
    # Fetch all groups with pagination
    page_size = 1000
    offset = 0
    
    while True:
        logger.info(f"Fetching groups at offset {offset}...")
        
        try:
            response = (
                client.table("story_groups")
                .select("id, member_count")
                .order("created_at")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            
            if not response.data:
                break
            
            batch_size = len(response.data)
            stats["total_groups"] += batch_size
            logger.info(f"Processing {batch_size} groups...")
            
            # Process each group
            for group in response.data:
                group_id = group["id"]
                stored_count = group["member_count"]
                
                # Get actual member count
                try:
                    members_response = (
                        client.table("story_group_members")
                        .select("id", count="exact")
                        .eq("group_id", group_id)
                        .execute()
                    )
                    actual_count = members_response.count or 0
                    
                    # Update if different
                    if stored_count != actual_count:
                        if dry_run:
                            logger.debug(
                                f"[DRY RUN] Would update group {group_id[:8]}... "
                                f"from {stored_count} to {actual_count}"
                            )
                        else:
                            client.table("story_groups").update({
                                "member_count": actual_count
                            }).eq("id", group_id).execute()
                            
                            logger.debug(
                                f"Updated group {group_id[:8]}... "
                                f"from {stored_count} to {actual_count}"
                            )
                        
                        stats["groups_updated"] += 1
                    else:
                        stats["groups_correct"] += 1
                        
                except Exception as e:
                    logger.error(f"Error processing group {group_id}: {e}")
                    stats["errors"] += 1
            
            logger.info(
                f"Batch complete: {stats['groups_updated']} updated, "
                f"{stats['groups_correct']} already correct"
            )
            
            # Check if we got a partial page (last page)
            if batch_size < page_size:
                break
            
            offset += page_size
            
        except Exception as e:
            logger.error(f"Error fetching groups at offset {offset}: {e}")
            stats["errors"] += 1
            break
    
    # Log summary
    logger.info("=" * 80)
    logger.info("Fix Complete")
    logger.info("=" * 80)
    logger.info(f"Total groups processed:  {stats['total_groups']}")
    logger.info(f"Groups updated:          {stats['groups_updated']}")
    logger.info(f"Groups already correct:  {stats['groups_correct']}")
    logger.info(f"Errors:                  {stats['errors']}")
    logger.info("=" * 80)
    
    return stats


def verify_fix() -> dict:
    """
    Verify that all member_counts are correct.
    
    Returns:
        Dict with verification results
    """
    client = get_supabase_client()
    
    logger.info("=" * 80)
    logger.info("Verifying member_counts")
    logger.info("=" * 80)
    
    # Use the group_summary view to check for mismatches
    mismatches = []
    page_size = 1000
    offset = 0
    
    while True:
        response = (
            client.from_("group_summary")
            .select("id, member_count, actual_member_count")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        
        if not response.data:
            break
        
        # Find mismatches in this batch
        batch_mismatches = [
            g for g in response.data
            if g["member_count"] != g["actual_member_count"]
        ]
        mismatches.extend(batch_mismatches)
        
        if len(response.data) < page_size:
            break
        
        offset += page_size
    
    # Get total counts
    total_response = client.table("story_groups").select("id", count="exact").execute()
    total_groups = total_response.count or 0
    
    zero_response = (
        client.table("story_groups")
        .select("id", count="exact")
        .eq("member_count", 0)
        .execute()
    )
    zero_count = zero_response.count or 0
    
    results = {
        "total_groups": total_groups,
        "groups_with_zero": zero_count,
        "mismatched_groups": len(mismatches),
    }
    
    logger.info(f"Total groups:          {results['total_groups']}")
    logger.info(f"Groups with zero:      {results['groups_with_zero']}")
    logger.info(f"Mismatched groups:     {results['mismatched_groups']}")
    
    if mismatches:
        logger.warning(f"\nFound {len(mismatches)} mismatched groups:")
        for g in mismatches[:10]:
            logger.warning(
                f"  - ID: {g['id'][:8]}..., "
                f"stored: {g['member_count']}, "
                f"actual: {g['actual_member_count']}"
            )
        if len(mismatches) > 10:
            logger.warning(f"  ... and {len(mismatches) - 10} more")
    else:
        logger.info("\n✅ All member_counts are correct!")
    
    logger.info("=" * 80)
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Fix member_count for story_groups")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be updated",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify, don't fix",
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
    
    try:
        if args.verify_only:
            verify_fix()
        else:
            fix_member_counts(dry_run=args.dry_run)
            logger.info("\nVerifying fix...")
            verify_fix()
            
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
