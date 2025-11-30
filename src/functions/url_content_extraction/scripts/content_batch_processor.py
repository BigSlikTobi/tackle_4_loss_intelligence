#!/usr/bin/env python3
"""Batch processor for content extraction from URLs.

Fetches article content from URLs using the extraction framework and marks
content_extracted_at. This prepares articles for fact extraction via the
Batch API.

The content extraction must be synchronous (HTTP requests to external sites),
but it uses the shared batch infrastructure for checkpointing, failure
tracking, and progress monitoring.

Examples:
    # Process pending URLs (default limit 100)
    python content_batch_processor.py

    # Process with custom limit
    python content_batch_processor.py --limit 500

    # Resume from checkpoint
    python content_batch_processor.py --checkpoint ./checkpoints/content.json

    # Process specific URLs
    python content_batch_processor.py --url-ids id1,id2,id3
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.logging import setup_logging
from src.shared.utils.env import load_env
from src.shared.db.connection import get_supabase_client
from src.shared.batch import (
    CheckpointManager,
    FailureTracker,
    ProgressTracker,
    MemoryMonitor,
    register_stage_failure,
    retry_on_network_error,
)
from src.functions.url_content_extraction.core.extractors import extractor_factory
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Hosts that require Playwright (must be processed sequentially)
_HEAVY_HOSTS = {
    "www.espn.com",
    "www.nfl.com",
    "sports.yahoo.com",
    "www.cbssports.com",
    "www.nbcsportsphiladelphia.com",
    "www.nbcsportschicago.com",
    "www.nbcsportsbayarea.com",
    "www.nbcsportsboston.com",
    "www.nbcsportswashington.com",
}


def is_heavy_url(url: str) -> bool:
    """Check if URL requires Playwright (heavy) extraction."""
    try:
        hostname = urlparse(url).hostname or ""
        return hostname in _HEAVY_HOSTS
    except Exception:
        return False


def fetch_pending_urls(
    client,
    limit: int = 100,
    url_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Fetch URLs pending content extraction.
    
    Args:
        client: Supabase client
        limit: Maximum URLs to fetch
        url_ids: Specific URL IDs to fetch (overrides limit)
        
    Returns:
        List of URL records with id and url
    """
    if url_ids:
        response = (
            client.table("news_urls")
            .select("id,url")
            .in_("id", url_ids)
            .execute()
        )
    else:
        response = (
            client.table("news_urls")
            .select("id,url")
            .is_("content_extracted_at", "null")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

    urls = getattr(response, "data", []) or []
    logger.info("Fetched %d pending URLs for content extraction", len(urls))
    return urls


def extract_content(url: str, timeout: int = 45) -> str:
    """Extract article content from URL.
    
    Args:
        url: Article URL
        timeout: Request timeout in seconds
        
    Returns:
        Extracted article content text
    """
    try:
        extractor = extractor_factory.get_extractor(url)
        result = extractor.extract(url, timeout=timeout)

        if result.error:
            logger.warning("Extraction error for %s: %s", url, result.error)
            return ""

        if result.paragraphs:
            content = "\n\n".join(result.paragraphs)
            return content.strip()

        logger.warning("Extractor returned no paragraphs for %s", url)
        return ""

    except Exception as e:
        logger.error("Content extraction failed for %s: %s", url, e)
        return ""


def store_content(client, url_id: str, content: str) -> bool:
    """Mark content as extracted (content is fetched at facts extraction time).
    
    Note: Content is NOT stored in the database for legal reasons.
    We only mark content_extracted_at to indicate extraction was successful.
    The actual content will be re-fetched when generating facts batches.
    
    Args:
        client: Supabase client
        url_id: News URL ID
        content: Extracted content (used for validation only, not stored)
        
    Returns:
        True if successful
    """
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        client.table("news_urls").update({
            "content_extracted_at": now_iso,
        }).eq("id", url_id).execute()
        return True
    except Exception as e:
        logger.error("Failed to mark content extracted for %s: %s", url_id, e)
        return False


def process_url(
    item: Dict[str, Any],
    client,
    checkpoint: CheckpointManager,
    failure_tracker: FailureTracker,
    timeout: int = 45,
) -> bool:
    """Process a single URL for content extraction.
    
    Args:
        item: URL record with id and url
        client: Supabase client
        checkpoint: Checkpoint manager
        failure_tracker: Failure tracker
        timeout: Request timeout
        
    Returns:
        True if successful
    """
    url_id = str(item.get("id", ""))
    url = item.get("url", "")

    if not url_id or not url:
        logger.warning("Skipping malformed URL item: %s", item)
        return False

    # Check if already complete
    if checkpoint.is_stage_complete(url_id, "content"):
        logger.debug("Skipping completed URL: %s", url_id)
        return True

    # Check if skipped due to failures
    if failure_tracker.is_skipped("content", url_id):
        logger.debug("Skipping failed URL: %s", url_id)
        return False

    try:
        # Extract content
        content = extract_content(url, timeout=timeout)

        if not content:
            register_stage_failure(
                "content",
                url_id,
                url,
                "Content extraction returned empty",
                failure_tracker,
            )
            return False

        # Store content
        success = retry_on_network_error(
            lambda: store_content(client, url_id, content)
        )

        if success:
            checkpoint.mark_stage_complete(url_id, "content")
            logger.debug("Extracted content for %s (%d chars)", url_id, len(content))
            return True
        else:
            register_stage_failure(
                "content",
                url_id,
                url,
                "Failed to store content",
                failure_tracker,
            )
            return False

    except Exception as e:
        import traceback
        register_stage_failure(
            "content",
            url_id,
            url,
            str(e),
            failure_tracker,
            tb=traceback.format_exc(),
        )
        return False


def run_batch_processor(
    limit: int = 100,
    url_ids: Optional[List[str]] = None,
    checkpoint_file: Optional[Path] = None,
    workers: int = 4,
    timeout: int = 45,
    flush_interval: int = 10,
) -> Dict[str, Any]:
    """Run the content batch processor.
    
    Args:
        limit: Maximum URLs to process
        url_ids: Specific URL IDs to process
        checkpoint_file: Path to checkpoint file
        workers: Number of concurrent workers
        timeout: Request timeout per URL
        flush_interval: Checkpoint flush interval
        
    Returns:
        Summary dict with statistics
    """
    client = get_supabase_client()

    # Initialize infrastructure
    checkpoint_path = checkpoint_file or Path("./checkpoints/content_extraction.json")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    
    checkpoint = CheckpointManager(str(checkpoint_path), stages=["content"])
    failure_tracker = FailureTracker()
    memory_monitor = MemoryMonitor()
    memory_monitor.start()

    try:
        # Fetch pending URLs
        urls = fetch_pending_urls(client, limit=limit, url_ids=url_ids)

        if not urls:
            logger.info("No pending URLs to process")
            return {"processed": 0, "successful": 0, "failed": 0}

        # Filter out already completed
        pending = [
            item for item in urls
            if not checkpoint.is_stage_complete(str(item.get("id", "")), "content")
        ]

        if not pending:
            logger.info("All URLs already processed")
            return {"processed": 0, "successful": 0, "failed": 0}

        logger.info("Processing %d URLs (skipping %d completed)", len(pending), len(urls) - len(pending))

        # Separate light and heavy URLs
        light_urls = [item for item in pending if not is_heavy_url(item.get("url", ""))]
        heavy_urls = [item for item in pending if is_heavy_url(item.get("url", ""))]
        
        logger.info("URL breakdown: %d light (parallel), %d heavy (sequential)", len(light_urls), len(heavy_urls))

        progress = ProgressTracker(total_articles=len(pending), stage="content")
        successful = 0
        failed = 0

        def process_and_track(item):
            """Process a URL and return success status."""
            nonlocal successful, failed
            try:
                success = process_url(item, client, checkpoint, failure_tracker, timeout)
                if success:
                    successful += 1
                    progress.increment(success=True)
                else:
                    failed += 1
                    progress.increment(success=False)
                return success
            except Exception as e:
                logger.error("Unexpected error processing %s: %s", item.get("id"), e)
                failed += 1
                progress.increment(success=False)
                return False

        # Process light URLs in parallel (safe with ThreadPoolExecutor)
        if light_urls:
            logger.info("Processing %d light URLs with %d workers...", len(light_urls), workers)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        process_url,
                        item,
                        client,
                        checkpoint,
                        failure_tracker,
                        timeout,
                    ): item
                    for item in light_urls
                }

                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        success = future.result()
                        if success:
                            successful += 1
                            progress.increment(success=True)
                        else:
                            failed += 1
                            progress.increment(success=False)
                    except Exception as e:
                        logger.error("Unexpected error processing %s: %s", item.get("id"), e)
                        failed += 1
                        progress.increment(success=False)

                    # Periodic checkpoint flush
                    if progress.processed_count % flush_interval == 0:
                        checkpoint.flush()

                    # Log progress
                    if progress.should_log():
                        progress.log_progress(extra_stats=memory_monitor.get_stats())

        # Process heavy URLs sequentially (Playwright not thread-safe)
        if heavy_urls:
            logger.info("Processing %d heavy URLs sequentially (Playwright)...", len(heavy_urls))
            for item in heavy_urls:
                process_and_track(item)
                
                # Periodic checkpoint flush
                if progress.processed_count % flush_interval == 0:
                    checkpoint.flush()

                # Log progress
                if progress.should_log():
                    progress.log_progress(extra_stats=memory_monitor.get_stats())

        # Final flush and summary
        checkpoint.flush()
        progress.log_summary()

        # Save failures
        if failure_tracker.get_summary():
            failures_path = checkpoint_path.with_name("content_failures.json")
            failure_tracker.save(failures_path)

        return {
            "processed": len(pending),
            "successful": successful,
            "failed": failed,
            "failure_summary": failure_tracker.get_summary(),
        }

    finally:
        memory_monitor.stop()


def setup_cli_parser() -> argparse.ArgumentParser:
    """Set up command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Batch content extraction from URLs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process pending URLs (default limit 100)
  python content_batch_processor.py

  # Process with custom limit
  python content_batch_processor.py --limit 500

  # Resume from checkpoint
  python content_batch_processor.py --checkpoint ./checkpoints/content.json

  # Process specific URLs
  python content_batch_processor.py --url-ids id1,id2,id3

  # Verbose logging
  python content_batch_processor.py --verbose
        """,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum URLs to process (default: 100)",
    )

    parser.add_argument(
        "--url-ids",
        type=str,
        help="Comma-separated list of specific URL IDs to process",
    )

    parser.add_argument(
        "--url-ids-file",
        type=Path,
        help="Path to file containing URL IDs (one per line)",
    )

    parser.add_argument(
        "--checkpoint",
        type=Path,
        help="Path to checkpoint file",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of concurrent workers for light URLs (default: 10, heavy URLs always sequential)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="Request timeout per URL in seconds (default: 45)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Set logging level explicitly",
    )

    return parser


def main():
    """Main entry point."""
    parser = setup_cli_parser()
    args = parser.parse_args()

    # Load environment
    load_env()

    # Set up logging
    if args.log_level:
        log_level = args.log_level
    elif args.verbose:
        log_level = "DEBUG"
    else:
        log_level = "INFO"

    setup_logging(level=log_level)

    logger.info("=" * 60)
    logger.info("Content Batch Processor")
    logger.info("=" * 60)

    # Parse URL IDs if provided (either from --url-ids or --url-ids-file)
    url_ids = None
    if args.url_ids:
        url_ids = [uid.strip() for uid in args.url_ids.split(",") if uid.strip()]
    elif args.url_ids_file:
        if args.url_ids_file.exists():
            with args.url_ids_file.open() as f:
                url_ids = [line.strip() for line in f if line.strip()]
            logger.info(f"Loaded {len(url_ids)} URL IDs from {args.url_ids_file}")
        else:
            logger.error(f"URL IDs file not found: {args.url_ids_file}")
            sys.exit(1)

    # Run processor
    result = run_batch_processor(
        limit=args.limit,
        url_ids=url_ids,
        checkpoint_file=args.checkpoint,
        workers=args.workers,
        timeout=args.timeout,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("CONTENT EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Total processed:  {result['processed']}")
    print(f"Successful:       {result['successful']}")
    print(f"Failed:           {result['failed']}")
    print("=" * 60)

    if result.get("failure_summary"):
        print("\nFailure summary:")
        for stage, count in result["failure_summary"].items():
            print(f"  {stage}: {count}")

    print("\n💡 Next step: Run fact extraction with:")
    print("   python facts_batch_cli.py --task create")

    sys.exit(0 if result["failed"] == 0 else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
