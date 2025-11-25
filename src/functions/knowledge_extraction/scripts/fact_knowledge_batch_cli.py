"""CLI to build and submit fact-level knowledge batch jobs."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Bootstrap sys.path when executed directly (relative import fails without package context)
try:
    from . import _bootstrap  # type: ignore  # noqa: F401
except ImportError:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.knowledge_extraction.core.fact_batch import (
    FactBatchPipeline,
    FactBatchRequestGenerator,
)


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create, check, or process fact knowledge batches")
    parser.add_argument(
        "--task",
        choices=["topics", "entities"],
        required=False,
        help="Whether to request topics or entities for each fact (required when creating or processing if not in metadata)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max facts to include (defaults to all available)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=25,
        help="Number of facts per model request",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=200,
        help="DB page size when streaming facts (lower to reduce DB timeouts)",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="Skip over fact pages that error even at minimum page size (best-effort mode)",
    )
    parser.add_argument(
        "--include-completed-urls",
        action="store_true",
        help="Do not filter out URLs that already have knowledge_extracted_at set (useful for reprocessing)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1-nano-2025-04-14",
        help="OpenAI model to use for knowledge extraction",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Sampling temperature for the model",
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
        help="When processing, skip facts that already have topics/entities",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse output but do not write to the database (processing only)",
    )
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Only write the jsonl file without creating a batch job",
    )
    return parser.parse_args()


def _load_task_from_metadata(batch_id: str, output_dir: Path) -> str | None:
    """Load task type from stored batch metadata."""
    metadata_path = output_dir / f"fact_knowledge_batch_{batch_id}.json"
    if not metadata_path.exists():
        return None
    try:
        with metadata_path.open("r") as handle:
            data = json.load(handle)
            return data.get("task")
    except Exception:
        return None


def main() -> None:
    args = parse_args()
    setup_logging()
    load_env()

    # Determine mode
    if args.status:
        pipeline = FactBatchPipeline(output_dir=args.output_dir)
        status = pipeline.check_status(args.status)
        logger.info("Batch status fetched", extra=status)
        print(f"Batch: {status['batch_id']}")
        print(f"Status: {status['status']}")
        if status.get("request_counts"):
            counts = status["request_counts"]
            print(f"Requests: {counts.get('completed', 0)}/{counts.get('total', 0)} (failed: {counts.get('failed', 0)})")
        if status.get("output_file_id"):
            print(f"Output file id: {status['output_file_id']}")
        return

    if args.process:
        task = args.task or _load_task_from_metadata(args.process, args.output_dir)
        if not task:
            raise SystemExit("Task is required to process batch (provide --task or ensure metadata exists).")

        pipeline = FactBatchPipeline(output_dir=args.output_dir)
        summary = pipeline.process_batch(
            args.process,
            task=task,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
        )
        logger.info("Processed batch", extra=summary)
        print(f"Processed batch {summary['batch_id']}")
        print(f"Output: {summary['output_path']}")
        if summary.get("error_path"):
            print(f"Errors: {summary['error_path']}")
        print(f"Facts processed: {summary['facts_processed']}")
        print(f"Topics written: {summary['topics_written']}")
        print(f"Entities written: {summary['entities_written']}")
        missing = summary.get("missing_fact_ids") or []
        if missing:
            print(f"Missing facts (not in DB): {len(missing)}")
            for fact_id in missing:
                print(f"  - {fact_id}")
        if summary.get("errors"):
            print(f"Errors encountered: {len(summary['errors'])}")
        return

    # Creation flow
    if not args.task:
        raise SystemExit("--task is required when creating a batch")

    generator = FactBatchRequestGenerator(
        model=args.model,
        temperature=args.temperature,
        chunk_size=args.chunk_size,
        output_dir=args.output_dir,
        page_size=args.page_size,
        skip_errors=args.skip_errors,
        pending_urls_only=not args.include_completed_urls,
    )

    if args.no_submit:
        batch = generator.generate(task=args.task, limit=args.limit)
        logger.info(
            "Generated batch file without submission",
            extra={
                "file": str(batch.file_path),
                "requests": batch.total_requests,
                "facts": batch.total_facts,
            },
        )
        return

    pipeline = FactBatchPipeline(generator=generator, output_dir=args.output_dir)
    result = pipeline.create_batch(task=args.task, limit=args.limit)

    logger.info(
        "Batch submitted",
        extra={
            "batch_id": result.batch_id,
            "status": result.status,
            "requests": result.total_requests,
            "facts": result.total_facts,
        },
    )


if __name__ == "__main__":
    main()
