#!/usr/bin/env python3
"""Command-line interface for batch fact extraction using OpenAI Batch API.

Provides 50% cost savings for processing large article backlogs by using
the OpenAI Batch API with 24h completion window.

Examples:
    # Create a new batch job for pending articles
    python facts_batch_cli.py --task create --limit 500

    # Check status of a batch job
    python facts_batch_cli.py --task status --batch-id batch_abc123

    # Process completed batch results
    python facts_batch_cli.py --task process --batch-id batch_abc123

    # List recent batch jobs
    python facts_batch_cli.py --task list

    # Cancel a running batch
    python facts_batch_cli.py --task cancel --batch-id batch_abc123
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.logging import setup_logging
from src.shared.utils.env import load_env
from src.functions.url_content_extraction.core.facts_batch import FactsBatchPipeline
from src.shared.batch.tracking import BatchTracker, BatchStage

logger = logging.getLogger(__name__)


def setup_cli_parser() -> argparse.ArgumentParser:
    """Set up command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Batch fact extraction using OpenAI Batch API (50%% cost savings)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create batch job for 500 articles (default)
  python facts_batch_cli.py --task create

  # Create batch job with custom limit
  python facts_batch_cli.py --task create --limit 1000

  # Check batch status
  python facts_batch_cli.py --task status --batch-id batch_abc123

  # Process completed batch (writes to database)
  python facts_batch_cli.py --task process --batch-id batch_abc123

  # Process batch without writing (dry run)
  python facts_batch_cli.py --task process --batch-id batch_abc123 --dry-run

  # List recent batch jobs
  python facts_batch_cli.py --task list

  # Cancel running batch
  python facts_batch_cli.py --task cancel --batch-id batch_abc123

Configuration:
  Set OPENAI_API_KEY in environment or .env file
        """,
    )

    parser.add_argument(
        "--task",
        choices=["create", "status", "process", "list", "cancel", "repair", "update-stats"],
        required=True,
        help="Task to perform: create, status, process, list, cancel, repair, or update-stats",
    )

    parser.add_argument(
        "--batch-id",
        type=str,
        help="Batch ID for status/process/cancel/repair tasks",
    )

    parser.add_argument(
        "--input-file",
        type=Path,
        help="Input JSONL file for repair task (fixes duplicates and resubmits)",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum articles to include in batch (default: 500)",
    )

    parser.add_argument(
        "--model",
        type=str,
        default="gpt-5-nano",
        help="Model for fact extraction (default: gpt-5-nano)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process batch without writing to database",
    )

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip articles that already have facts (default: True)",
    )

    parser.add_argument(
        "--no-skip-existing",
        action="store_false",
        dest="skip_existing",
        help="Don't skip articles that already have facts",
    )

    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip embedding creation when processing",
    )

    parser.add_argument(
        "--only-validated",
        action="store_true",
        help="Only process articles with content_extracted_at set (requires content_batch_processor first)",
    )

    parser.add_argument(
        "--high-fact-count",
        type=int,
        metavar="THRESHOLD",
        help="Re-extract articles with facts_count > THRESHOLD (deletes existing facts first)",
    )

    parser.add_argument(
        "--force-delete",
        action="store_true",
        help="Delete existing facts before inserting new ones (for re-extraction batches)",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for batch files (default: ./batch_files)",
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

    parser.add_argument(
        "--register",
        action="store_true",
        help="Register batch in tracking table for pipeline orchestration (used by GitHub Actions)",
    )

    return parser


def handle_create(pipeline: FactsBatchPipeline, args: argparse.Namespace) -> bool:
    """Create a new batch job."""
    high_fact_count = getattr(args, 'high_fact_count', None)
    only_validated = getattr(args, 'only_validated', False)
    register = getattr(args, 'register', False)
    
    if high_fact_count:
        logger.info(f"Creating batch job for re-extraction of high fact count articles (> {high_fact_count})...")
    else:
        logger.info("Creating batch job for fact extraction...")
    
    logger.info(f"  Limit: {args.limit}")
    logger.info(f"  Model: {args.model}")
    logger.info(f"  Skip existing: {args.skip_existing}")
    logger.info(f"  Only validated: {only_validated}")
    logger.info(f"  Register in tracking: {register}")
    if high_fact_count:
        logger.info(f"  High fact count threshold: > {high_fact_count}")

    try:
        result = pipeline.create_batch(
            limit=args.limit,
            skip_existing=args.skip_existing,
            high_fact_count_threshold=high_fact_count,
            include_unextracted=not only_validated,
        )

        # Register batch in tracking table if requested
        if register:
            try:
                tracker = BatchTracker()
                tracker.register_batch(
                    batch_id=result.batch_id,
                    stage=BatchStage.FACTS,
                    article_count=result.total_articles,
                    request_count=result.total_requests,
                    model=args.model,
                    metadata={
                        "high_fact_count_threshold": high_fact_count,
                        "only_validated": only_validated,
                        "skip_existing": args.skip_existing,
                    },
                )
                logger.info(f"Registered batch {result.batch_id} in tracking table")
            except Exception as e:
                logger.warning(f"Failed to register batch in tracking table: {e}")
                # Don't fail the whole operation if tracking fails

        print("\n" + "=" * 60)
        if high_fact_count:
            print("BATCH CREATED FOR RE-EXTRACTION (HIGH FACT COUNT)")
        else:
            print("BATCH CREATED SUCCESSFULLY")
        print("=" * 60)
        print(f"Batch ID:       {result.batch_id}")
        print(f"Status:         {result.status}")
        print(f"Articles:       {result.total_articles}")
        print(f"Requests:       {result.total_requests}")
        print(f"Input file:     {result.input_file_path}")
        if register:
            print(f"Tracking:       ✅ Registered")
        if high_fact_count:
            print(f"\n⚠️  NOTE: When processing this batch, existing facts will be DELETED")
            print(f"   for articles with facts_count > {high_fact_count}")
        print("=" * 60)
        print("\n💡 Check status with:")
        print(f"   python facts_batch_cli.py --task status --batch-id {result.batch_id}")
        print("\n⏳ Batch will complete within 24 hours.")
        print("   When complete, process with:")
        print(f"   python facts_batch_cli.py --task process --batch-id {result.batch_id}")

        return True

    except ValueError as e:
        logger.warning(str(e))
        return False
    except Exception as e:
        logger.error(f"Failed to create batch: {e}", exc_info=True)
        return False


def handle_status(pipeline: FactsBatchPipeline, args: argparse.Namespace) -> bool:
    """Check batch status."""
    if not args.batch_id:
        logger.error("--batch-id is required for status task")
        return False

    try:
        status = pipeline.check_status(args.batch_id)

        print("\n" + "=" * 60)
        print("BATCH STATUS")
        print("=" * 60)
        print(f"Batch ID:       {status['batch_id']}")
        print(f"Status:         {status['status']}")

        if status.get("request_counts"):
            counts = status["request_counts"]
            total = counts.get("total", 0)
            completed = counts.get("completed", 0)
            failed = counts.get("failed", 0)
            print(f"\nProgress:")
            print(f"  Total:        {total}")
            print(f"  Completed:    {completed}")
            print(f"  Failed:       {failed}")
            if total > 0:
                pct = (completed / total) * 100
                print(f"  Complete:     {pct:.1f}%")

        if status.get("created_at"):
            created = datetime.fromtimestamp(status["created_at"])
            print(f"\nCreated at:     {created}")

        if status.get("completed_at"):
            completed = datetime.fromtimestamp(status["completed_at"])
            print(f"Completed at:   {completed}")

        print("=" * 60)

        # Show next steps
        if status["status"] == "completed":
            print(f"\n✅ Batch completed! Process results with:")
            print(f"   python facts_batch_cli.py --task process --batch-id {args.batch_id}")
        elif status["status"] in ["failed", "expired", "cancelled"]:
            print(f"\n❌ Batch ended with status: {status['status']}")
        else:
            print(f"\n⏳ Batch is {status['status']}. Check again later.")

        return True

    except Exception as e:
        logger.error(f"Failed to check batch status: {e}", exc_info=True)
        return False


def handle_process(pipeline: FactsBatchPipeline, args: argparse.Namespace) -> bool:
    """Process completed batch results."""
    if not args.batch_id:
        logger.error("--batch-id is required for process task")
        return False

    force_delete = getattr(args, 'force_delete', False)

    try:
        logger.info(f"Processing batch: {args.batch_id}")
        if args.dry_run:
            logger.info("🔍 DRY RUN - No data will be written to database")
        if force_delete:
            logger.info("⚠️  FORCE DELETE - Existing facts will be deleted before inserting new ones")

        result = pipeline.process_batch(
            args.batch_id,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
            create_embeddings=not args.no_embeddings,
            force_delete=force_delete,
        )

        print("\n" + "=" * 60)
        print("BATCH PROCESSING RESULTS")
        print("=" * 60)
        print(f"Batch ID:               {result['batch_id']}")
        print(f"Articles in output:     {result['articles_in_output']}")
        print(f"Articles processed:     {result['articles_processed']}")
        print(f"Articles skipped (existing): {result['articles_skipped_existing']}")
        print(f"Articles skipped (no facts): {result['articles_skipped_no_facts']}")
        print(f"Articles with errors:   {result['articles_with_errors']}")
        print(f"\nFacts extracted:        {result['facts_extracted']}")
        print(f"Facts filtered:         {result['facts_filtered']}")
        print(f"Facts written:          {result['facts_written']}")
        print(f"Embeddings created:     {result['embeddings_created']}")
        print("=" * 60)

        if result.get("errors"):
            print("\nErrors (first 10):")
            for error in result["errors"][:10]:
                print(f"  • {error}")
            if len(result["errors"]) > 10:
                print(f"  ... and {len(result['errors']) - 10} more")

        if args.dry_run:
            print("\n💡 Remove --dry-run flag to save results to database")
        else:
            print("\n✅ Results saved to database!")

        return result["articles_with_errors"] == 0

    except ValueError as e:
        logger.error(str(e))
        return False
    except Exception as e:
        logger.error(f"Failed to process batch: {e}", exc_info=True)
        return False


def handle_list(pipeline: FactsBatchPipeline, args: argparse.Namespace) -> bool:
    """List recent batch jobs."""
    try:
        batches = pipeline.list_batches(limit=20)

        print("\n" + "=" * 60)
        print("RECENT FACTS BATCH JOBS")
        print("=" * 60)

        if not batches:
            print("No facts extraction batch jobs found")
        else:
            for batch in batches:
                created = datetime.fromtimestamp(batch["created_at"]) if batch.get("created_at") else "N/A"

                status_emoji = {
                    "completed": "✅",
                    "failed": "❌",
                    "cancelled": "🚫",
                    "in_progress": "⏳",
                    "validating": "🔍",
                    "finalizing": "📝",
                }.get(batch["status"], "•")

                print(f"\n{status_emoji} {batch['batch_id']}")
                print(f"   Status: {batch['status']}")
                print(f"   Model: {batch.get('model', 'N/A')}")
                print(f"   Created: {created}")
                if batch.get("progress"):
                    print(f"   Progress: {batch['progress']}")

        print("=" * 60)
        print("\n💡 Check specific batch with: --task status --batch-id BATCH_ID")

        return True

    except Exception as e:
        logger.error(f"Failed to list batches: {e}", exc_info=True)
        return False


def handle_cancel(pipeline: FactsBatchPipeline, args: argparse.Namespace) -> bool:
    """Cancel a running batch job."""
    if not args.batch_id:
        logger.error("--batch-id is required for cancel task")
        return False

    try:
        result = pipeline.cancel_batch(args.batch_id)
        print(f"\n✅ Batch {args.batch_id} is now {result['status']}")
        print("   (May take up to 10 minutes to fully cancel)")
        return True

    except Exception as e:
        logger.error(f"Failed to cancel batch: {e}", exc_info=True)
        return False


def handle_repair(pipeline: FactsBatchPipeline, args: argparse.Namespace) -> bool:
    """Repair a failed batch by removing duplicates and resubmitting.
    
    Reads the original JSONL file, removes duplicate custom_ids, and submits
    a new batch with the deduplicated requests.
    """
    import json
    import openai
    
    # Find the input file - either from --input-file or from batch metadata
    input_file = getattr(args, 'input_file', None)
    
    if not input_file and args.batch_id:
        # Try to find the input file from saved batch info
        batch_info_path = pipeline.output_dir / f"facts_batch_{args.batch_id}.json"
        if batch_info_path.exists():
            with batch_info_path.open() as f:
                info = json.load(f)
                input_file = Path(info.get("input_file_path", ""))
        
        if not input_file or not input_file.exists():
            # Search for matching batch files
            for f in pipeline.output_dir.glob("facts_batch_*.jsonl"):
                if "output" not in f.name and "error" not in f.name:
                    # This might be our file - check metadata
                    meta_path = f.with_suffix("").with_name(f.stem + "_metadata.json")
                    if meta_path.exists():
                        input_file = f
                        logger.info(f"Found potential input file: {f}")
                        break
    
    if not input_file or not input_file.exists():
        logger.error("Could not find input file. Use --input-file to specify the JSONL file path")
        logger.error("Look in the batch_files directory for files like facts_batch_YYYYMMDD_HHMMSS.jsonl")
        return False
    
    logger.info(f"Reading input file: {input_file}")
    
    # Read and deduplicate
    seen_ids = set()
    unique_requests = []
    duplicates_removed = 0
    
    with input_file.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                custom_id = request.get("custom_id", "")
                
                if custom_id in seen_ids:
                    duplicates_removed += 1
                    logger.debug(f"Line {line_num}: Removing duplicate {custom_id}")
                else:
                    seen_ids.add(custom_id)
                    unique_requests.append(request)
            except json.JSONDecodeError as e:
                logger.warning(f"Line {line_num}: Failed to parse JSON: {e}")
    
    if duplicates_removed == 0:
        logger.info("No duplicates found in the batch file")
        return True
    
    logger.info(f"Found {duplicates_removed} duplicates, {len(unique_requests)} unique requests remain")
    
    # Write repaired file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    repaired_file = pipeline.output_dir / f"facts_batch_{timestamp}_repaired.jsonl"
    
    with repaired_file.open("w") as f:
        for request in unique_requests:
            f.write(json.dumps(request) + "\n")
    
    logger.info(f"Wrote repaired file: {repaired_file}")
    
    # Upload and create new batch
    logger.info("Uploading repaired file to OpenAI...")
    with repaired_file.open("rb") as f:
        uploaded = openai.files.create(file=f, purpose="batch")
    
    logger.info(f"Uploaded file ID: {uploaded.id}")
    
    # Create new batch
    batch = openai.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={
            "type": "facts_extraction",
            "repaired_from": str(input_file.name),
            "original_requests": str(len(unique_requests) + duplicates_removed),
            "deduplicated_requests": str(len(unique_requests)),
            "duplicates_removed": str(duplicates_removed),
        },
    )
    
    print("\n" + "=" * 60)
    print("BATCH REPAIRED AND RESUBMITTED")
    print("=" * 60)
    print(f"Original file:       {input_file.name}")
    print(f"Repaired file:       {repaired_file.name}")
    print(f"Duplicates removed:  {duplicates_removed}")
    print(f"Unique requests:     {len(unique_requests)}")
    print(f"\nNew Batch ID:        {batch.id}")
    print(f"Status:              {batch.status}")
    print("=" * 60)
    print("\n💡 Check status with:")
    print(f"   python facts_batch_cli.py --task status --batch-id {batch.id}")
    
    return True


def handle_update_stats(pipeline: FactsBatchPipeline, args: argparse.Namespace) -> bool:
    """Update facts_count and article_difficulty for already-processed articles.
    
    Use this if you processed a batch before the stats update code was added.
    Reads the batch output file and updates news_urls with correct stats.
    """
    import json
    from datetime import timezone
    from src.shared.db import get_supabase_client
    
    if not args.batch_id:
        logger.error("--batch-id is required for update-stats task")
        return False
    
    # First download/find the output file
    import openai
    
    try:
        batch = openai.batches.retrieve(args.batch_id)
        if batch.status != "completed":
            logger.error(f"Batch status is {batch.status}, must be completed")
            return False
        
        if not batch.output_file_id:
            logger.error("Batch has no output file")
            return False
        
        # Download output file
        output_file = pipeline.output_dir / f"batch_{args.batch_id}_output_for_stats.jsonl"
        if not output_file.exists():
            logger.info(f"Downloading output file...")
            response = openai.files.content(batch.output_file_id)
            output_file.write_bytes(response.content)
            logger.info(f"Saved to: {output_file}")
        else:
            logger.info(f"Using cached output file: {output_file}")
        
        # Parse output to get article IDs
        article_ids = []
        with output_file.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    custom_id = data.get("custom_id", "")
                    if custom_id.startswith("facts_"):
                        article_id = custom_id[6:]  # Remove "facts_" prefix
                        article_ids.append(article_id)
                except json.JSONDecodeError:
                    continue
        
        logger.info(f"Found {len(article_ids)} articles in batch output")
        
        if not article_ids:
            logger.error("No articles found in batch output")
            return False
        
        # Get facts counts from database
        client = get_supabase_client()
        
        # Query facts table for counts - need to paginate properly since each article can have many facts
        logger.info("Counting facts per article from database...")
        facts_counts = {}
        chunk_size = 50  # Smaller chunks since each article can have 50+ facts
        
        for i in range(0, len(article_ids), chunk_size):
            chunk = article_ids[i:i + chunk_size]
            
            # For each article in chunk, we need to count all its facts
            # Paginate through all facts for this chunk of articles
            offset = 0
            page_size = 1000
            
            while True:
                response = (
                    client.table("news_facts")
                    .select("news_url_id")
                    .in_("news_url_id", chunk)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                rows = getattr(response, "data", []) or []
                
                for row in rows:
                    url_id = row.get("news_url_id")
                    if url_id:
                        facts_counts[url_id] = facts_counts.get(url_id, 0) + 1
                
                # If we got less than page_size, we've reached the end
                if len(rows) < page_size:
                    break
                offset += page_size
            
            logger.debug(f"Processed chunk {i//chunk_size + 1}/{(len(article_ids) + chunk_size - 1)//chunk_size}")
        
        logger.info(f"Found facts for {len(facts_counts)} articles")
        
        # Update news_urls with counts and difficulty
        now_iso = datetime.now(timezone.utc).isoformat()
        updated = 0
        
        for article_id, count in facts_counts.items():
            # Calculate difficulty based on facts count
            if count < 10:
                difficulty = "easy"
            elif count <= 30:
                difficulty = "medium"
            else:
                difficulty = "hard"
            
            try:
                client.table("news_urls").update({
                    "facts_extracted_at": now_iso,
                    "facts_count": count,
                    "article_difficulty": difficulty,
                }).eq("id", article_id).execute()
                updated += 1
            except Exception as e:
                logger.error(f"Failed to update {article_id}: {e}")
        
        print("\n" + "=" * 60)
        print("STATS UPDATE COMPLETE")
        print("=" * 60)
        print(f"Articles in batch:      {len(article_ids)}")
        print(f"Articles with facts:    {len(facts_counts)}")
        print(f"Articles updated:       {updated}")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to update stats: {e}", exc_info=True)
        return False


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
    logger.info("Facts Batch CLI - OpenAI Batch API (50%% cost savings)")
    logger.info("=" * 60)

    # Validate OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY environment variable not set")
        logger.error("Set it in .env file or export OPENAI_API_KEY=your-key")
        sys.exit(1)

    # Initialize pipeline
    try:
        pipeline = FactsBatchPipeline(
            model=args.model,
            output_dir=args.output_dir,
        )
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Handle task
    handlers = {
        "create": handle_create,
        "status": handle_status,
        "process": handle_process,
        "list": handle_list,
        "cancel": handle_cancel,
        "repair": handle_repair,
        "update-stats": handle_update_stats,
    }

    handler = handlers.get(args.task)
    if not handler:
        logger.error(f"Unknown task: {args.task}")
        sys.exit(1)

    success = handler(pipeline, args)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
