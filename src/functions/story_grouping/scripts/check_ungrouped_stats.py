#!/usr/bin/env python3
"""Quick script to check ungrouped embedding statistics."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timedelta, timezone
from src.shared.utils.env import load_env
from src.shared.db import get_supabase_client

# Load environment variables
load_env()

def check_ungrouped_stats():
    """Check statistics about ungrouped embeddings."""
    client = get_supabase_client()
    
    # Get cutoff date (14 days ago)
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    
    print("=" * 80)
    print("UNGROUPED EMBEDDINGS STATISTICS")
    print("=" * 80)
    print(f"Date range: Last 14 days (since {cutoff_date})")
    print()
    
    # 1. Total embeddings with vectors in last 14 days
    print("1. Counting total embeddings with vectors (last 14 days)...")
    total_response = client.table("story_embeddings").select(
        "id", count="exact"
    ).not_.is_("embedding_vector", "null").gte(
        "created_at", cutoff_date
    ).limit(1).execute()
    total_count = total_response.count or 0
    print(f"   Total embeddings with vectors: {total_count}")
    print()
    
    # 2. Total grouped stories (all time)
    print("2. Counting grouped stories (all time)...")
    grouped_response = client.table("story_group_members").select(
        "news_url_id", count="exact"
    ).limit(1).execute()
    grouped_count = grouped_response.count or 0
    print(f"   Total grouped stories: {grouped_count}")
    print()
    
    # 3. Get sample of news_url_ids from embeddings
    print("3. Fetching sample news_url_ids from embeddings...")
    sample_embeddings = client.table("story_embeddings").select(
        "news_url_id, created_at"
    ).not_.is_("embedding_vector", "null").gte(
        "created_at", cutoff_date
    ).order("created_at", desc=True).limit(10).execute()
    
    sample_ids = [e["news_url_id"] for e in sample_embeddings.data]
    print(f"   Sample news_url_ids (newest 10): {len(sample_ids)} found")
    
    if sample_ids:
        # Check if these are grouped
        print()
        print("4. Checking if sample IDs are grouped...")
        for i, news_url_id in enumerate(sample_ids[:5], 1):
            check = client.table("story_group_members").select(
                "id"
            ).eq("news_url_id", news_url_id).limit(1).execute()
            
            status = "GROUPED" if check.data else "UNGROUPED"
            created_at = sample_embeddings.data[i-1]["created_at"]
            print(f"   [{i}] {news_url_id[:36]}... - {status} (created: {created_at})")
    
    print()
    
    # 5. Try to find ANY ungrouped by checking newest stories
    print("5. Looking for ungrouped stories in newest 100 embeddings...")
    recent = client.table("story_embeddings").select(
        "news_url_id"
    ).not_.is_("embedding_vector", "null").gte(
        "created_at", cutoff_date
    ).order("created_at", desc=True).limit(100).execute()
    
    ungrouped_found = []
    for emb in recent.data:
        check = client.table("story_group_members").select(
            "id"
        ).eq("news_url_id", emb["news_url_id"]).limit(1).execute()
        
        if not check.data:
            ungrouped_found.append(emb["news_url_id"])
    
    print(f"   Found {len(ungrouped_found)} ungrouped in newest 100")
    if ungrouped_found:
        print(f"   Example ungrouped IDs: {ungrouped_found[:3]}")
    print()
    
    # 6. Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total embeddings (14 days):  {total_count}")
    print(f"Total grouped (all time):    {grouped_count}")
    print(f"Ungrouped in newest 100:     {len(ungrouped_found)}")
    
    if len(ungrouped_found) == 0:
        print()
        print("✓ All recent embeddings appear to be grouped!")
        print("  This explains why the grouping pipeline found 0 stories to process.")
    else:
        print()
        print("⚠ Found ungrouped embeddings!")
        print("  The pipeline should be picking these up.")
    print("=" * 80)

if __name__ == "__main__":
    try:
        check_ungrouped_stats()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
