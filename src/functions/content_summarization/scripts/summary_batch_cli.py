"""CLI to build and submit summary batch jobs using OpenAI Batch API.

This CLI provides ~50% cost savings compared to synchronous API calls by using
OpenAI's Batch API for asynchronous processing.

USAGE:
  # Create and submit a batch for all pending articles
  python summary_batch_cli.py --task all --limit 1000
  
  # Create batch file only (don't submit)
  python summary_batch_cli.py --task easy --limit 500 --no-submit
  
  # Check batch status
  python summary_batch_cli.py --status batch_abc123
  
  # Process completed batch results
  python summary_batch_cli.py --process batch_abc123
  
  # Process with embeddings disabled
  python summary_batch_cli.py --process batch_abc123 --no-embeddings
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Bootstrap sys.path when executed directly
try:
    from . import _bootstrap  # type: ignore  # noqa: F401
except ImportError:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.content_summarization.core.summary_batch import (
    SummaryBatchPipeline,
    SummaryBatchRequestGenerator,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create, check, or process summary batches using OpenAI Batch API"
    )
    parser.add_argument(
        "--task",
        choices=["easy", "hard", "all"],
        default="all",
        help="Which articles to process: easy (single summary), hard (topic summaries), or all",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max articles to include (defaults to 500 newest articles)",
    )
    parser.add_argument(
        "--model",
        default="gpt-5-nano",
        help="OpenAI model to use for summary generation",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./batch_files"),
        help="Directory to store batch payloads",
    )
    parser.add_argument(
        "--status",
        metavar="BATCH_ID",
        help="Check status for a batch id",
    )
    parser.add_argument(
        "--process",
        metavar="BATCH_ID",
        help="Download and process a completed batch id",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="When processing, skip articles that already have summaries",
    )
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip creating embeddings when processing (faster, use if embeddings exist)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse output but do not write to the database (processing only)",
    )
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Only write the JSONL file without creating a batch job",
    )
    return parser.parse_args()


def _load_task_from_metadata(batch_id: str, output_dir: Path) -> str:
    """Load task type from stored batch metadata."""

    metadata_path = output_dir / f"summary_batch_{batch_id}.json"
    if metadata_path.exists():
        try:
            with metadata_path.open("r") as handle:
                data = json.load(handle)
                return data.get("task", "all")
        except Exception:
            pass
    return "all"


def main() -> None:
    args = parse_args()
    setup_logging()
    load_env()

    # Ensure output directory exists
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Status check mode
    if args.status:
        pipeline = SummaryBatchPipeline(output_dir=args.output_dir)
        status = pipeline.check_status(args.status)
        
        logger.info("Batch status fetched", extra=status)
        print(f"\n{'='*50}")
        print(f"Batch: {status['batch_id']}")
        print(f"Status: {status['status']}")
        
        if status.get("request_counts"):
            counts = status["request_counts"]
            print(f"Requests: {counts.get('completed', 0)}/{counts.get('total', 0)} (failed: {counts.get('failed', 0)})")
        
        if status.get("created_at"):
            print(f"Created: {status['created_at']}")
        if status.get("completed_at"):
            print(f"Completed: {status['completed_at']}")
        if status.get("output_file_id"):
            print(f"Output file: {status['output_file_id']}")
        if status.get("error_file_id"):
            print(f"Error file: {status['error_file_id']}")
        print(f"{'='*50}\n")
        return

    # Process completed batch mode
    if args.process:
        pipeline = SummaryBatchPipeline(output_dir=args.output_dir)
        
        print(f"\nProcessing batch {args.process}...")
        summary = pipeline.process_batch(
            args.process,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
            create_embeddings=not args.no_embeddings,
        )
        
        logger.info("Processed batch", extra=summary)
        print(f"\n{'='*50}")
        print(f"Processed batch: {summary['batch_id']}")
        print(f"Output file: {summary['output_path']}")
        if summary.get("error_path"):
            print(f"Errors file: {summary['error_path']}")
        
        print("\n--- Processing Statistics ---")
        print(f"Articles in output:       {summary.get('articles_in_output', 'N/A')}")
        print(f"Articles processed:       {summary['articles_processed']}")
        print(f"Articles skipped (exist): {summary.get('articles_skipped_existing', 0)}")
        print(f"Articles skipped (no data): {summary.get('articles_skipped_no_data', 0)}")
        print(f"Summaries written:        {summary['summaries_written']}")
        print(f"Topic summaries written:  {summary['topic_summaries_written']}")
        print(f"Embeddings created:       {summary['embeddings_created']}")
        
        if summary.get("errors"):
            print(f"\nErrors encountered: {len(summary['errors'])}")
            for err in summary["errors"][:5]:
                print(f"  - {err[:100]}")
            if len(summary["errors"]) > 5:
                print(f"  ... and {len(summary['errors']) - 5} more")
        
        print(f"{'='*50}\n")
        return

    # Creation mode
    generator = SummaryBatchRequestGenerator(
        model=args.model,
        output_dir=args.output_dir,
    )

    if args.no_submit:
        # Just generate the file
        batch = generator.generate(task=args.task, limit=args.limit)
        
        print(f"\n{'='*50}")
        print("Generated batch file (not submitted)")
        print(f"File: {batch.file_path}")
        print(f"Metadata: {batch.metadata_path}")
        print(f"Requests: {batch.total_requests}")
        print(f"Articles: {batch.total_articles}")
        print(f"Model: {args.model}")
        print(f"{'='*50}\n")
        
        logger.info(
            "Generated batch file without submission",
            extra={
                "file": str(batch.file_path),
                "requests": batch.total_requests,
                "articles": batch.total_articles,
            },
        )
        return

    # Create and submit batch
    pipeline = SummaryBatchPipeline(generator=generator, output_dir=args.output_dir)
    result = pipeline.create_batch(task=args.task, limit=args.limit)

    print(f"\n{'='*50}")
    print("Batch submitted successfully!")
    print(f"Batch ID: {result.batch_id}")
    print(f"Status: {result.status}")
    print(f"Requests: {result.total_requests}")
    print(f"Articles: {result.total_articles}")
    print(f"Model: {args.model}")
    print(f"\nInput file: {result.input_file_path}")
    print(f"Metadata: {result.metadata_path}")
    print(f"\nTo check status:")
    print(f"  python summary_batch_cli.py --status {result.batch_id}")
    print(f"\nTo process when complete:")
    print(f"  python summary_batch_cli.py --process {result.batch_id}")
    print(f"{'='*50}\n")

    logger.info(
        "Batch submitted",
        extra={
            "batch_id": result.batch_id,
            "status": result.status,
            "requests": result.total_requests,
            "articles": result.total_articles,
        },
    )


if __name__ == "__main__":
    main()
