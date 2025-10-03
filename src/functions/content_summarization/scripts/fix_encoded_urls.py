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

def main():
    """Find and fix URL-encoded URLs in the database."""
    load_env()
    supabase = get_supabase_client()
    
    print("Checking for URL-encoded URLs in news_urls table...")
    print("=" * 80)
    
    # Fetch all URLs
    response = supabase.table("news_urls").select("id, url").execute()
    
    encoded_urls = []
    for row in response.data:
        if "%" in row["url"]:
            encoded_urls.append(row)
    
    if not encoded_urls:
        print("\n✓ No URL-encoded URLs found. Database is clean!")
        return
    
    print(f"\nFound {len(encoded_urls)} URL-encoded URLs:")
    print("-" * 80)
    
    for row in encoded_urls:
        print(f"\nID: {row['id']}")
        print(f"Encoded:  {row['url']}")
        print(f"Decoded:  {unquote(row['url'])}")
    
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
    
    for row in encoded_urls:
        try:
            decoded_url = unquote(row["url"])
            
            supabase.table("news_urls").update({
                "url": decoded_url
            }).eq("id", row["id"]).execute()
            
            print(f"✓ Fixed: {row['id']}")
            success_count += 1
        except Exception as e:
            print(f"✗ Failed {row['id']}: {e}")
            error_count += 1
    
    print("\n" + "=" * 80)
    print(f"Complete: {success_count} fixed, {error_count} failed")
    
    if success_count > 0:
        print("\n✓ URLs successfully decoded in database!")

if __name__ == "__main__":
    main()
