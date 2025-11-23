"""CLI to build and submit fact-level knowledge batch jobs."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

# Bootstrap sys.path
from . import _bootstrap  # noqa: F401

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.knowledge_extraction.core.fact_batch import (
    FactBatchPipeline,
    FactBatchRequestGenerator,
)


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create OpenAI batches for fact knowledge generation")
    parser.add_argument(
        "--task",
        choices=["topics", "entities"],
        required=True,
        help="Whether to request topics or entities for each fact",
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
        "--model",
        default="gpt-4-1-nano",
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
        "--no-submit",
        action="store_true",
        help="Only write the jsonl file without creating a batch job",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging()
    load_env()

    generator = FactBatchRequestGenerator(
        model=args.model,
        temperature=args.temperature,
        chunk_size=args.chunk_size,
        output_dir=args.output_dir,
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
