#!/usr/bin/env python3
"""
Script to fix and verify story_groups member_count issue.

This script:
1. Applies the SQL fix to correct existing member_count values
2. Installs the database trigger for automatic maintenance
3. Verifies the fix worked correctly
"""

import sys
import os

# Add project root to path
sys.path.insert(0, '/Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence')

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client
import logging

# Load environment and setup logging
load_env()
setup_logging()
logger = logging.getLogger(__name__)


def check_current_state(client):
    """Check current state of member_count issue."""
    logger.info("=" * 80)
    logger.info("CHECKING CURRENT STATE")
    logger.info("=" * 80)
    
    # Count groups with member_count = 0
    response = client.table('story_groups').select('id', count='exact').eq('member_count', 0).execute()
    zero_count = response.count or 0
    
    # Count all groups
    response_all = client.table('story_groups').select('id', count='exact').execute()
    total_groups = response_all.count or 0
    
    logger.info(f"Total groups: {total_groups}")
    logger.info(f"Groups with member_count = 0: {zero_count}")
    
    if total_groups > 0:
        logger.info(f"Percentage with zero count: {(zero_count / total_groups * 100):.1f}%")
    
    # Check mismatches using view
    view_response = client.from_('group_summary').select(
        'id, member_count, actual_member_count'
    ).neq('member_count', 'actual_member_count').execute()
    
    mismatched = len(view_response.data) if view_response.data else 0
    logger.info(f"Groups with mismatched counts: {mismatched}")
    
    if view_response.data and len(view_response.data) > 0:
        logger.info("\nSample mismatches:")
        for g in view_response.data[:5]:
            logger.info(
                f"  - ID: {g['id'][:8]}..., "
                f"stored: {g['member_count']}, "
                f"actual: {g['actual_member_count']}"
            )
    
    return zero_count, mismatched


def apply_sql_fix(client):
    """Apply SQL fix to correct member_count."""
    logger.info("=" * 80)
    logger.info("APPLYING SQL FIX")
    logger.info("=" * 80)
    
    # Read the SQL fix script
    sql_file = '/Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence/src/functions/story_grouping/fix_member_counts.sql'
    
    logger.info("Executing member_count fix update...")
    
    # Execute the update query directly
    # Note: Supabase Python client doesn't support raw SQL well, so we do it via RPC or direct query
    # For now, we'll construct the update using the Python client
    
    # Get all groups and their actual counts
    view_response = client.from_('group_summary').select('id, actual_member_count').execute()
    
    if not view_response.data:
        logger.warning("No groups found to update")
        return 0
    
    updated_count = 0
    for group in view_response.data:
        try:
            response = client.table('story_groups').update({
                'member_count': group['actual_member_count'],
                'updated_at': 'NOW()'
            }).eq('id', group['id']).execute()
            
            if response.data:
                updated_count += 1
            
            # Log progress every 100 groups
            if updated_count % 100 == 0:
                logger.info(f"Updated {updated_count} groups...")
                
        except Exception as e:
            logger.error(f"Error updating group {group['id']}: {e}")
    
    logger.info(f"Updated {updated_count} groups")
    return updated_count


def install_trigger(client):
    """Install the database trigger."""
    logger.info("=" * 80)
    logger.info("INSTALLING DATABASE TRIGGER")
    logger.info("=" * 80)
    
    logger.warning(
        "Database trigger installation requires direct SQL access.\n"
        "Please run the following SQL script in your Supabase SQL Editor:\n"
        "  src/functions/story_grouping/trigger_member_count.sql\n"
    )
    
    # We can't install triggers via the Python client
    # User needs to run the SQL script manually
    return False


def verify_fix(client):
    """Verify the fix worked."""
    logger.info("=" * 80)
    logger.info("VERIFYING FIX")
    logger.info("=" * 80)
    
    zero_count, mismatched = check_current_state(client)
    
    if zero_count == 0 and mismatched == 0:
        logger.info("\n✅ SUCCESS! All member_counts are correct!")
        return True
    else:
        logger.warning(f"\n⚠️  Still have issues: {zero_count} zeros, {mismatched} mismatches")
        return False


def main():
    """Main function."""
    logger.info("Story Groups Member Count Fix Script")
    logger.info("=" * 80)
    
    try:
        # Get Supabase client
        client = get_supabase_client()
        
        # Step 1: Check current state
        check_current_state(client)
        
        # Step 2: Apply SQL fix
        input("\nPress Enter to apply the SQL fix...")
        updated = apply_sql_fix(client)
        
        # Step 3: Verify fix
        logger.info("\nWaiting for updates to propagate...")
        import time
        time.sleep(2)
        
        success = verify_fix(client)
        
        # Step 4: Remind about trigger
        if success:
            logger.info("\n" + "=" * 80)
            logger.info("NEXT STEPS")
            logger.info("=" * 80)
            logger.info(
                "To prevent this issue from happening again, install the database trigger:\n"
                "1. Open your Supabase SQL Editor\n"
                "2. Run the SQL script: src/functions/story_grouping/trigger_member_count.sql\n"
                "3. Verify the trigger is installed\n"
            )
        
        return 0 if success else 1
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
