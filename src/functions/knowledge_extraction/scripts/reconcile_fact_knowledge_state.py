#!/usr/bin/env python3
"""Repair stranded fact/knowledge pipeline state.

This script reconciles URL-level timestamps with fact/topic/entity rows so
scheduled workflows can automatically recover from partial processing.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Sequence, Set

# Bootstrap sys.path when executed directly.
try:
    from . import _bootstrap  # type: ignore  # noqa: F401
except ImportError:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.shared.batch import retry_on_network_error
from src.shared.batch.tracking import BatchTracker
from src.shared.db.connection import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair facts/knowledge timestamps for stranded URLs and stale batch creation state."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist repairs. Without this flag the script only reports what it would change.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Pagination size for Supabase queries (default: 100).",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=60,
        help="Only inspect URLs created within this many days (default: 60, use 0 to disable).",
    )
    parser.add_argument(
        "--stale-batch-age-minutes",
        type=int,
        default=30,
        help="Mark CREATING batches older than this as failed (default: 30).",
    )
    parser.add_argument(
        "--skip-stale-batches",
        action="store_true",
        help="Skip stale CREATING batch cleanup.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level.",
    )
    return parser.parse_args()


def chunked(values: Sequence[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(values), size):
        yield list(values[index : index + size])


def build_cutoff_iso(*, max_age_days: int | None) -> str | None:
    if max_age_days is None or max_age_days <= 0:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()


def execute_with_retry(func):
    """Run a Supabase/PostgREST call with retry protection."""
    return retry_on_network_error(func, max_retries=4, initial_delay=1.0)


def fetch_timestamped_urls(
    client,
    *,
    column: str,
    page_size: int,
    cutoff_iso: str | None,
) -> List[str]:
    url_ids: List[str] = []
    offset = 0

    while True:
        query = (
            client.table("news_urls")
            .select("id")
            .not_.is_(column, "null")
            .order("id")
        )
        if cutoff_iso:
            query = query.gte("created_at", cutoff_iso)
        response = execute_with_retry(
            lambda: query.range(offset, offset + page_size - 1).execute()
        )
        rows = getattr(response, "data", []) or []
        if not rows:
            break
        url_ids.extend(row["id"] for row in rows if row.get("id"))
        offset += len(rows)
        if len(rows) < page_size:
            break

    return url_ids


def find_urls_without_facts(client, *, page_size: int, cutoff_iso: str | None) -> Set[str]:
    timestamped_url_ids = fetch_timestamped_urls(
        client,
        column="facts_extracted_at",
        page_size=page_size,
        cutoff_iso=cutoff_iso,
    )
    if not timestamped_url_ids:
        return set()

    missing_url_ids: Set[str] = set()
    for url_id in timestamped_url_ids:
        response = execute_with_retry(
            lambda: (
                client.table("news_facts")
                .select("id")
                .eq("news_url_id", url_id)
                .limit(1)
                .execute()
            )
        )
        rows = getattr(response, "data", []) or []
        if not rows:
            missing_url_ids.add(url_id)

    return missing_url_ids


def find_urls_with_incomplete_knowledge(
    client,
    *,
    page_size: int,
    cutoff_iso: str | None,
) -> Set[str]:
    completed_url_ids = fetch_timestamped_urls(
        client,
        column="knowledge_extracted_at",
        page_size=page_size,
        cutoff_iso=cutoff_iso,
    )
    if not completed_url_ids:
        return set()

    incomplete_url_ids: Set[str] = set()
    for url_id in completed_url_ids:
        fact_ids = fetch_fact_ids_for_url(client, url_id=url_id, page_size=page_size)

        if not fact_ids:
            continue

        facts_with_topics: Set[str] = set()
        facts_with_entities: Set[str] = set()

        for fact_chunk in chunked(fact_ids, page_size):
            topic_response = execute_with_retry(
                lambda: (
                    client.table("news_fact_topics")
                    .select("news_fact_id")
                    .in_("news_fact_id", fact_chunk)
                    .execute()
                )
            )
            entity_response = execute_with_retry(
                lambda: (
                    client.table("news_fact_entities")
                    .select("news_fact_id")
                    .in_("news_fact_id", fact_chunk)
                    .execute()
                )
            )
            facts_with_topics.update(
                row["news_fact_id"]
                for row in (getattr(topic_response, "data", []) or [])
                if row.get("news_fact_id")
            )
            facts_with_entities.update(
                row["news_fact_id"]
                for row in (getattr(entity_response, "data", []) or [])
                if row.get("news_fact_id")
            )

        for fact_id in fact_ids:
            if fact_id not in facts_with_topics or fact_id not in facts_with_entities:
                incomplete_url_ids.add(url_id)
                break

    return incomplete_url_ids


def fetch_fact_ids_for_url(client, *, url_id: str, page_size: int) -> List[str]:
    fact_ids: List[str] = []
    offset = 0

    while True:
        response = execute_with_retry(
            lambda: (
                client.table("news_facts")
                .select("id")
                .eq("news_url_id", url_id)
                .order("id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
        )
        rows = getattr(response, "data", []) or []
        if not rows:
            break
        fact_ids.extend(row["id"] for row in rows if row.get("id"))
        offset += len(rows)
        if len(rows) < page_size:
            break

    return fact_ids


def count_content_ready_without_facts(
    client,
    *,
    page_size: int,
    cutoff_iso: str | None,
) -> int:
    total = 0
    offset = 0

    while True:
        query = (
            client.table("news_urls")
            .select("id")
            .not_.is_("content_extracted_at", "null")
            .is_("facts_extracted_at", "null")
            .is_("content_quarantined_at", "null")
            .order("id")
        )
        if cutoff_iso:
            query = query.gte("created_at", cutoff_iso)
        response = execute_with_retry(
            lambda: query.range(offset, offset + page_size - 1).execute()
        )
        rows = getattr(response, "data", []) or []
        if not rows:
            break
        total += len(rows)
        offset += len(rows)
        if len(rows) < page_size:
            break

    return total


def update_urls(client, *, url_ids: Set[str], payload: dict, page_size: int, dry_run: bool) -> int:
    if not url_ids:
        return 0

    if dry_run:
        return len(url_ids)

    updated = 0
    for url_chunk in chunked(sorted(url_ids), page_size):
        execute_with_retry(
            lambda: client.table("news_urls").update(payload).in_("id", url_chunk).execute()
        )
        updated += len(url_chunk)
    return updated


def cleanup_stale_batches(*, max_age_minutes: int, dry_run: bool) -> int:
    tracker = BatchTracker()
    stale_batches = execute_with_retry(
        lambda: tracker.get_stale_creating_batches(max_age_minutes=max_age_minutes)
    )
    if not stale_batches:
        return 0

    if dry_run:
        return len(stale_batches)

    for batch in stale_batches:
        execute_with_retry(
            lambda batch=batch: tracker.mark_failed(
                batch.batch_id,
                f"Batch creation exceeded {max_age_minutes} minutes",
                increment_retry=False,
            )
        )
    return len(stale_batches)


def main() -> None:
    args = parse_args()
    setup_logging(level=args.log_level)
    load_env()

    client = get_supabase_client()
    dry_run = not args.apply
    cutoff_iso = build_cutoff_iso(max_age_days=args.max_age_days)

    stale_batches_cleaned = 0
    if not args.skip_stale_batches:
        stale_batches_cleaned = cleanup_stale_batches(
            max_age_minutes=args.stale_batch_age_minutes,
            dry_run=dry_run,
        )

    urls_without_facts = find_urls_without_facts(
        client,
        page_size=args.page_size,
        cutoff_iso=cutoff_iso,
    )
    incomplete_knowledge_urls = find_urls_with_incomplete_knowledge(
        client,
        page_size=args.page_size,
        cutoff_iso=cutoff_iso,
    )
    content_ready_without_facts = count_content_ready_without_facts(
        client,
        page_size=args.page_size,
        cutoff_iso=cutoff_iso,
    )

    facts_reset = update_urls(
        client,
        url_ids=urls_without_facts,
        payload={
            "facts_extracted_at": None,
            "facts_count": None,
            "article_difficulty": None,
            "knowledge_extracted_at": None,
            "knowledge_error_count": 0,
            "summary_created_at": None,
        },
        page_size=args.page_size,
        dry_run=dry_run,
    )
    knowledge_reset = update_urls(
        client,
        url_ids=incomplete_knowledge_urls,
        payload={
            "knowledge_extracted_at": None,
            "knowledge_error_count": 0,
            "summary_created_at": None,
        },
        page_size=args.page_size,
        dry_run=dry_run,
    )

    action_label = "would reset" if dry_run else "reset"
    print("\n" + "=" * 60)
    print("FACT / KNOWLEDGE RECONCILIATION")
    print("=" * 60)
    print(f"Mode:                          {'dry-run' if dry_run else 'apply'}")
    print(f"URL age window:                {args.max_age_days or 'all'} day(s)")
    print(f"Stale creating batches:        {stale_batches_cleaned}")
    print(f"URLs {action_label} (no facts): {facts_reset}")
    print(f"URLs {action_label} (knowledge incomplete): {knowledge_reset}")
    print(f"Content-ready URLs pending facts: {content_ready_without_facts}")
    print("=" * 60)


if __name__ == "__main__":
    main()
