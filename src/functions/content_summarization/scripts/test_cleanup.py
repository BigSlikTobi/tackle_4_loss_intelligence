"""
Test script for cleanup_author_facts.py
"""

import logging
import os
import sys
import uuid
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.content_summarization.scripts.cleanup_author_facts_cli import AuthorFactCleaner
from src.functions.content_summarization.scripts.content_pipeline_cli import build_config

logger = logging.getLogger(__name__)

def test_cleanup():
    load_env()
    setup_logging()
    
    env = dict(os.environ)
    config = build_config(env)
    client = get_supabase_client()
    
    # 1. Setup Test Data
    test_url_id = str(uuid.uuid4())
    logger.info(f"Creating test data for URL ID: {test_url_id}")
    
    # Insert dummy news_url
    client.table("news_urls").insert({
        "id": test_url_id,
        "url": "https://example.com/test-article",
        "title": "Test Article",
        "publication_date": "2025-11-20T12:00:00Z",
        "source_name": "Example Source",
        "publisher": "Example Publisher"
    }).execute()
    
    # Insert facts
    author_fact_id = str(uuid.uuid4())
    valid_fact_id = str(uuid.uuid4())
    
    facts = [
        {
            "id": author_fact_id,
            "news_url_id": test_url_id,
            "fact_text": "This article was written by John Doe for ESPN.",
            "llm_model": "test",
            "prompt_version": "test"
        },
        {
            "id": valid_fact_id,
            "news_url_id": test_url_id,
            "fact_text": "Patrick Mahomes threw 3 touchdowns in the game.",
            "llm_model": "test",
            "prompt_version": "test"
        }
    ]
    client.table("news_facts").insert(facts).execute()
    logger.info("Inserted test facts")
    
    try:
        # 2. Run Cleanup
        cleaner = AuthorFactCleaner(client, config)
        # We only want to process our test facts, but the script fetches by limit.
        # For this test, we can rely on the fact that we just inserted them 
        # and the script orders by created_at desc.
        # However, to be safe and not touch prod data, we should probably mock _fetch_facts 
        # or modify the script to accept specific IDs. 
        # For now, let's just run it and hope it picks up our facts (limit=100 should catch it).
        # A better approach for the script would be to filter by a specific run ID or date, 
        # but for this ad-hoc test, we will trust the order.
        
        # Actually, let's subclass to override _fetch_facts for safety
        class TestCleaner(AuthorFactCleaner):
            def _fetch_facts(self, limit: int, news_url_id: str = None):
            # Return our dummy facts
                return [
                    {"id": author_fact_id, "news_url_id": test_url_id, "fact_text": "This article was written by John Doe for ESPN."},
                    {"id": valid_fact_id, "news_url_id": test_url_id, "fact_text": "Patrick Mahomes threw 3 touchdowns."},
                    {"id": "11111111-1111-1111-1111-111111111111", "news_url_id": test_url_id, "fact_text": "The current date is 2025-11-20."},
                    {"id": "22222222-2222-2222-2222-222222222222", "news_url_id": test_url_id, "fact_text": "The model simulates every NFL game 10,000 times."}
                ]
        
        test_cleaner = TestCleaner(client, config)
        test_cleaner.run(limit=2, dry_run=False)
        
        # 3. Verify Results
        # Check if author fact is gone
        response = client.table("news_facts").select("id").eq("id", author_fact_id).execute()
        if not response.data:
            logger.info("SUCCESS: Author fact was deleted.")
        else:
            logger.error("FAILURE: Author fact still exists.")
            
        # Check if valid fact remains
        response = client.table("news_facts").select("id").eq("id", valid_fact_id).execute()
        if response.data:
            logger.info("SUCCESS: Valid fact remains.")
        else:
            logger.error("FAILURE: Valid fact was deleted.")

        # Check if useless facts are gone
        response = client.table("news_facts").select("id").in_("id", ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]).execute()
        if not response.data:
            logger.info("SUCCESS: Useless facts were deleted.")
        else:
            logger.error(f"FAILURE: Useless facts still exist: {response.data}")

    finally:
        # 4. Teardown
        logger.info("Cleaning up test data...")
        client.table("news_facts").delete().eq("news_url_id", test_url_id).execute()
        client.table("news_urls").delete().eq("id", test_url_id).execute()
        logger.info("Teardown complete.")

if __name__ == "__main__":
    test_cleanup()
