"""
Fix URL-encoded URLs in the database.

This script finds and fixes URLs that are stored with URL encoding
(e.g., %3A instead of :) in the news_urls table.
"""

import sys
from pathlib import Path

# Add project root to path
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from urllib.parse import unquote
from src.shared.utils.env import load_env
from src.shared.db.connection import get_supabase_client

PAGE_SIZE = 1000
UPSERT_BATCH_SIZE = 200

def main():
    """Find and fix URL-encoded URLs in the database."""
    load_env()
    supabase = get_supabase_client()
    
    print("Checking for URL-encoded URLs in news_urls table...")
    print("=" * 80)
    
    encoded_urls = []
    total_scanned = 0
    offset = 0

    while True:
        response = (
            supabase.table("news_urls")
            .select("id, url")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )

        rows = response.data or []
        if not rows:
            break

        total_scanned += len(rows)
        for row in rows:
            url = row.get("url") or ""
            if "%" in url:
                decoded_url = unquote(url)
                if decoded_url != url:
                    encoded_urls.append({"id": row["id"], "url": url, "decoded_url": decoded_url})

        if len(rows) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
    
    if not encoded_urls:
        print("\n✓ No URL-encoded URLs found. Database is clean!")
        return
    
    print(f"\nScanned {total_scanned} URLs.")
    print(f"Found {len(encoded_urls)} URL-encoded URLs:")
    print("-" * 80)
    
    for row in encoded_urls:
        print(f"\nID: {row['id']}")
        print(f"Encoded:  {row['url']}")
        print(f"Decoded:  {row['decoded_url']}")
    
    # Ask for confirmation
    print("\n" + "=" * 80)
    response = input(f"\nDo you want to fix these {len(encoded_urls)} URLs? (yes/no): ")
    
    if response.lower() not in ["yes", "y"]:
        print("Cancelled. No changes made.")
        return
    
    # Fix the URLs
    print("\nFixing URLs...")
    success_count = 0
    error_count = 0

    for start in range(0, len(encoded_urls), UPSERT_BATCH_SIZE):
        batch = encoded_urls[start:start + UPSERT_BATCH_SIZE]
        payload = [{"id": row["id"], "url": row["decoded_url"]} for row in batch]

        try:
            supabase.table("news_urls").upsert(payload, on_conflict="id").execute()
            for row in batch:
                print(f"✓ Fixed: {row['id']}")
            success_count += len(batch)
        except Exception as e:
            print(f"✗ Batch failed ({len(batch)} rows): {e}")
            error_count += len(batch)

    print("\n" + "=" * 80)
    print(f"Complete: {success_count} fixed, {error_count} failed")
    print(f"Total scanned: {total_scanned}, total updated: {success_count}")
    
    if success_count > 0:
        print("\n✓ URLs successfully decoded in database!")

if __name__ == "__main__":
    main()
