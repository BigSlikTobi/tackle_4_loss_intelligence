"""Synchronous summary batch processor using shared infrastructure.

This processor handles SUMMARY generation only. For other stages, use:
- Content extraction: url_content_extraction/scripts/content_batch_processor.py
- Fact extraction: url_content_extraction/scripts/facts_batch_cli.py (Batch API)
- Knowledge extraction: knowledge_extraction/scripts/extract_knowledge_cli.py

For BATCH API processing (50% cost savings), use:
- summary_batch_cli.py --task all --limit 1000

This synchronous processor is for:
- Small batch corrections (10-100 articles)
- Testing and debugging
- When immediate feedback is needed

USAGE:
  # Process summaries for pending articles
  python summarize_batch_processor.py --limit 100

  # Resume from checkpoint
  python summarize_batch_processor.py --limit 500 --resume

  # Process specific difficulty level
  python summarize_batch_processor.py --difficulty easy --limit 200
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Bootstrap path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.shared.batch import (
    CheckpointManager,
    FailureTracker,
    ProgressTracker,
    MemoryMonitor,
    register_stage_failure,
    retry_on_network_error,
)

# Import summary-specific functions from content_pipeline_cli
from src.functions.content_summarization.scripts.content_pipeline_cli import (
    PipelineConfig,
    build_config,
    get_article_difficulty,
    handle_easy_article_summary,
    handle_hard_article_summary,
    summary_stage_completed,
)

logger = logging.getLogger(__name__)

STAGE = "summary"
EDGE_FUNCTION_NAME = "get-pending-news-urls"


def fetch_pending_urls(config: PipelineConfig, limit: int) -> List[Dict[str, Any]]:
    """Fetch pending URLs for summary stage from edge function."""
    
    endpoint = f"{config.edge_function_base_url.rstrip('/')}/{EDGE_FUNCTION_NAME}"
    params = {"stage": STAGE, "limit": str(limit)}
    
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_key:
        logger.error("SUPABASE_KEY not found in environment")
        return []
    
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
        urls = payload.get("urls", [])
        logger.info(f"Fetched {len(urls)} pending URLs for summary stage")
        return urls
    except Exception as e:
        logger.error(f"Failed to fetch pending URLs: {e}")
        return []


def mark_news_url_timestamp(client, news_url_id: str, column: str) -> None:
    """Mark a timestamp column on news_urls with current UTC time."""
    now_iso = datetime.now(timezone.utc).isoformat()
    client.table("news_urls").update({column: now_iso}).eq("id", news_url_id).execute()


def process_article_summary(
    item: Dict[str, Any],
    client,
    config: PipelineConfig,
    checkpoint: CheckpointManager,
    failure_tracker: FailureTracker,
) -> bool:
    """Process summary stage for a single article.
    
    Returns:
        True if successful
    """
    raw_url_id = item.get("id")
    article_url = item.get("url", "")
    
    if not raw_url_id:
        logger.warning("Skipping malformed URL payload", {"item": item})
        return False
    
    url_id = str(raw_url_id)
    
    try:
        # Check checkpoint
        if checkpoint.is_stage_complete(url_id, STAGE):
            logger.debug(f"Skipping completed article: {url_id}")
            return True
        
        # Get article difficulty (set by knowledge extraction)
        difficulty_record = retry_on_network_error(
            lambda: get_article_difficulty(client, url_id)
        )
        difficulty = difficulty_record.get("article_difficulty") if difficulty_record else None
        
        if not difficulty:
            logger.info(f"[{url_id}] Waiting for knowledge extraction (no difficulty set)")
            return False
        
        logger.info(f"[{url_id}] Generating {difficulty} article summary")
        
        # Generate summary based on difficulty
        if difficulty == "easy":
            handle_easy_article_summary(client, url_id, config)
        else:
            handle_hard_article_summary(client, url_id, config)
        
        # Verify completion
        if retry_on_network_error(lambda: summary_stage_completed(client, url_id)):
            mark_news_url_timestamp(client, url_id, "summary_created_at")
            checkpoint.mark_stage_complete(url_id, STAGE)
            logger.info(f"[{url_id}] Summary complete")
            return True
        
        logger.warning(f"[{url_id}] Summary stage incomplete after processing")
        return False
        
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to process summary for {url_id}: {e}")
        register_stage_failure(STAGE, url_id, article_url, str(e), failure_tracker, tb)
        return False


def run_summary_processor(args) -> None:
    """Main processor entry point."""
    
    load_env()
    setup_logging()
    
    logger.info("Starting summary batch processor", {
        "limit": args.limit,
        "workers": args.workers,
        "batch_size": args.batch_size,
        "resume": args.resume,
        "difficulty": args.difficulty,
    })
    
    # Build configuration
    env = dict(os.environ)
    config = build_config(env)
    
    # Initialize components
    client = get_supabase_client()
    checkpoint = CheckpointManager(args.checkpoint_file)
    failure_tracker = FailureTracker()
    memory_monitor = MemoryMonitor(max_percent=args.max_memory_percent)
    memory_monitor.start()
    
    try:
        # Validate checkpoint if resuming
        if args.resume and Path(args.checkpoint_file).exists():
            logger.info("Resuming from checkpoint...")
        
        total_processed = 0
        batch_number = 0
        
        while True:
            # Check limits
            if args.limit and total_processed >= args.limit:
                logger.info(f"Reached limit: {args.limit} articles processed")
                break
            
            batch_number += 1
            remaining = args.limit - total_processed if args.limit else args.batch_size
            current_batch = min(args.batch_size, remaining)
            
            # Fetch pending URLs
            urls = fetch_pending_urls(config, limit=current_batch)
            
            if not urls:
                logger.info("No more pending URLs for summary stage")
                break
            
            # Filter by difficulty if specified
            if args.difficulty:
                # Pre-filter by checking difficulty
                filtered_urls = []
                for item in urls:
                    url_id = str(item.get("id", ""))
                    if url_id:
                        diff_record = get_article_difficulty(client, url_id)
                        if diff_record.get("article_difficulty") == args.difficulty:
                            filtered_urls.append(item)
                urls = filtered_urls
                
                if not urls:
                    logger.info(f"No {args.difficulty} articles pending")
                    break
            
            # Filter already completed
            urls = [
                item for item in urls
                if not checkpoint.is_stage_complete(str(item.get("id", "")), STAGE)
                and not failure_tracker.is_skipped(STAGE, str(item.get("id", "")))
            ]
            
            if not urls:
                logger.info(f"Batch {batch_number}: All articles already processed")
                continue
            
            logger.info(f"Batch {batch_number}: Processing {len(urls)} articles")
            
            # Initialize progress tracker
            progress = ProgressTracker(len(urls), STAGE)
            
            # Process with thread pool
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(
                        process_article_summary,
                        item,
                        client,
                        config,
                        checkpoint,
                        failure_tracker,
                    ): item
                    for item in urls
                }
                
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        success = future.result(timeout=120)
                        progress.increment(success=success)
                        
                        # Periodic checkpoint flush
                        if progress.processed_count % 10 == 0:
                            checkpoint.flush()
                        
                        # Log progress
                        if progress.should_log(interval=10):
                            progress.log_progress(memory_monitor)
                            
                    except Exception as e:
                        logger.error(f"Future failed for {item.get('id')}: {e}")
                        progress.increment(success=False)
            
            # Update totals
            total_processed += len(urls)
            checkpoint.flush()
            
            logger.info(
                f"Batch {batch_number} complete: "
                f"{progress.processed_count - progress.error_count} succeeded, "
                f"{progress.error_count} failed"
            )
            
            # Small delay between batches
            if args.batch_delay > 0:
                time.sleep(args.batch_delay)
        
        # Final checkpoint
        checkpoint.flush()
        
        # Save failures
        failures_path = Path(".summary_failures.json")
        failure_tracker.save(failures_path)
        
        logger.info(f"Processing complete. Total: {total_processed}")
        logger.info(f"Failures saved to: {failures_path}")
        
    finally:
        memory_monitor.stop()
        logger.info("Summary processor shutdown complete")


def main() -> None:
    """CLI entry point."""
    
    parser = argparse.ArgumentParser(
        description="Synchronous summary batch processor. "
                    "For Batch API (50% cheaper), use summary_batch_cli.py instead."
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum total articles to process (default: unlimited)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent workers (default: 4)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Articles per batch (default: 50)",
    )
    parser.add_argument(
        "--batch-delay",
        type=int,
        default=2,
        help="Seconds between batches (default: 2)",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=".summary_checkpoint.json",
        help="Path to checkpoint file",
    )
    parser.add_argument(
        "--max-memory-percent",
        type=int,
        default=80,
        help="Max memory usage before scaling down (default: 80)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint",
    )
    parser.add_argument(
        "--difficulty",
        choices=["easy", "hard"],
        default=None,
        help="Process only articles of specific difficulty",
    )
    
    args = parser.parse_args()
    run_summary_processor(args)


if __name__ == "__main__":
    main()
