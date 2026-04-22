#!/usr/bin/env python3
"""Sweep deleted/expired rows from news_url_content_ephemeral.

Intended to run from the content-pipeline-poll workflow after the facts
stage has marked rows consumed. Safe to run standalone; safe to run with
`--dry-run` to preview the row count.

Examples:
    python ephemeral_sweep_cli.py
    python ephemeral_sweep_cli.py --dry-run
    python ephemeral_sweep_cli.py --batch-size 200 --max-batches 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.db.connection import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.url_content_extraction.core.db import EphemeralContentWriter

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete consumed/expired rows from news_url_content_ephemeral",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows to fetch+delete per batch (default: 500)",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Stop after this many batches (default: until empty)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts only; do not delete",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    load_env()
    setup_logging(level="DEBUG" if args.verbose else "INFO")

    client = get_supabase_client()
    writer = EphemeralContentWriter(client)

    deleted = writer.delete_expired_and_consumed(
        batch_size=args.batch_size,
        max_batches=args.max_batches,
        dry_run=args.dry_run,
    )

    action = "Would delete" if args.dry_run else "Deleted"
    logger.info("%s %d ephemeral rows", action, deleted)
    print(f"{action} {deleted} ephemeral rows")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
