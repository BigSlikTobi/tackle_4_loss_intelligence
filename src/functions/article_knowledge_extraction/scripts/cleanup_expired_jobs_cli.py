"""Cleanup CLI for the article knowledge extraction job store.

Two responsibilities:
1. Delete all rows past `expires_at` (TTL garbage collection).
2. Optionally re-POST stale queued/running jobs to the worker endpoint so a
   dropped self-invoke doesn't leave a job stuck forever.

Run every 5 minutes from a scheduler (GitHub Actions) or ad-hoc locally.

Examples:
    python -m src.functions.article_knowledge_extraction.scripts.cleanup_expired_jobs_cli
    python -m src.functions.article_knowledge_extraction.scripts.cleanup_expired_jobs_cli \\
        --requeue-stale --worker-url https://... --worker-token $TOKEN
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.article_knowledge_extraction.core.config import SupabaseConfig
from src.functions.article_knowledge_extraction.core.db.job_store import JobStore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supabase-url", help="Supabase URL (falls back to SUPABASE_URL env)")
    parser.add_argument("--supabase-key", help="Supabase key (falls back to SUPABASE_KEY env)")
    parser.add_argument(
        "--jobs-table",
        default="extraction_jobs",
        help="Override the jobs table name",
    )
    parser.add_argument(
        "--service",
        default="article_knowledge_extraction",
        help="Service discriminator. Each service only sees and sweeps its own rows.",
    )
    parser.add_argument(
        "--requeue-stale",
        action="store_true",
        help="Re-POST stale queued/running jobs to the worker endpoint",
    )
    parser.add_argument(
        "--stale-queued-seconds",
        type=int,
        default=120,
        help="Consider queued jobs stale after this many seconds (default: 120)",
    )
    parser.add_argument(
        "--stale-running-seconds",
        type=int,
        default=600,
        help="Consider running jobs stale after this many seconds (default: 600)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Do not requeue jobs that have already hit this many attempts",
    )
    parser.add_argument(
        "--worker-url",
        help="Worker endpoint URL (falls back to WORKER_URL env)",
    )
    parser.add_argument(
        "--worker-token",
        help="Shared secret sent in X-Worker-Token (falls back to WORKER_TOKEN env)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    load_env()
    setup_logging(level="DEBUG" if args.verbose else os.getenv("LOG_LEVEL", "INFO"))
    logger = logging.getLogger(__name__)

    supabase_url = args.supabase_url or os.getenv("SUPABASE_URL")
    supabase_key = args.supabase_key or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        logger.error("Supabase URL and key are required")
        return 2

    store = JobStore(
        SupabaseConfig(url=supabase_url, key=supabase_key, jobs_table=args.jobs_table),
        service=args.service,
    )

    if args.dry_run:
        stale = store.list_stale(
            queued_older_than_seconds=args.stale_queued_seconds,
            running_older_than_seconds=args.stale_running_seconds,
            max_attempts=args.max_attempts,
        )
        logger.info("[dry-run] would inspect %d stale jobs", len(stale))
        logger.info("[dry-run] would delete rows past expires_at")
        return 0

    deleted = store.delete_expired()
    logger.info("Deleted %d expired rows", deleted)

    if not args.requeue_stale:
        return 0

    worker_url = args.worker_url or os.getenv("WORKER_URL")
    worker_token = args.worker_token or os.getenv("WORKER_TOKEN")
    if not worker_url:
        logger.error("--worker-url or WORKER_URL env required for --requeue-stale")
        return 2

    import requests

    # Stale `running` rows would otherwise be unclaimable — mark_running only
    # transitions queued -> running. Reset them first so the worker can claim.
    reset = store.reset_stale_running(
        running_older_than_seconds=args.stale_running_seconds,
        max_attempts=args.max_attempts,
    )
    if reset:
        logger.info("Reset %d stale running rows back to queued", reset)

    stale = store.list_stale(
        queued_older_than_seconds=args.stale_queued_seconds,
        running_older_than_seconds=args.stale_running_seconds,
        max_attempts=args.max_attempts,
    )
    if not stale:
        logger.info("No stale jobs to requeue")
        return 0

    headers = {"Content-Type": "application/json"}
    if worker_token:
        headers["X-Worker-Token"] = worker_token

    sent = 0
    for row in stale:
        job_id = row.get("job_id")
        if not job_id:
            continue
        payload = {
            "job_id": job_id,
            "supabase": {
                "url": supabase_url,
                "key": supabase_key,
                "jobs_table": args.jobs_table,
            },
        }
        try:
            response = requests.post(
                worker_url, json=payload, headers=headers, timeout=(3, 3)
            )
            # 403/500 without raise_for_status would silently count as
            # "requeued" — misleading ops signal + stale jobs never recover.
            response.raise_for_status()
            sent += 1
        except requests.RequestException as exc:
            logger.warning("Failed to requeue job %s: %s", job_id, exc)

    logger.info("Requeued %d / %d stale jobs", sent, len(stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
