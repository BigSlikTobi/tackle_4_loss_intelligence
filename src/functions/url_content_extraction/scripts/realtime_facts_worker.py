#!/usr/bin/env python3
"""Near-real-time facts worker for content-ready URLs."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.db.connection import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.url_content_extraction.scripts.extract_facts_cli import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MODEL,
    process_single_article,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process a small realtime queue of fact-ready URLs")
    parser.add_argument("--limit", type=int, default=10, help="Maximum URLs to process per run")
    parser.add_argument(
        "--url-ids",
        type=str,
        help="Comma-separated URL IDs to process instead of queue lookup",
    )
    parser.add_argument(
        "--url-ids-file",
        type=Path,
        help="File containing URL IDs to process (one per line)",
    )
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=None,
        help="Only process URLs created within this many hours",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model for fact extraction (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help=f"Embedding model (default: {DEFAULT_EMBEDDING_MODEL})",
    )
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip embedding creation",
    )
    parser.add_argument(
        "--force-playwright",
        action="store_true",
        help="Force Playwright extraction for all URLs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction without persisting facts",
    )
    parser.add_argument(
        "--output-success-ids-file",
        type=Path,
        help="Write URL IDs successfully processed for facts to this file",
    )
    return parser.parse_args()


def fetch_pending_urls(client, *, limit: int, max_age_hours: int | None) -> List[Dict]:
    query = (
        client.table("news_urls")
        .select("id,url")
        .not_.is_("content_extracted_at", "null")
        .is_("facts_extracted_at", "null")
        .is_("content_quarantined_at", "null")
        .is_("extraction_error", "null")
        .order("created_at", desc=True)
        .limit(limit)
    )

    if max_age_hours and max_age_hours > 0:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        query = query.gte("created_at", cutoff_iso)

    response = query.execute()
    return getattr(response, "data", []) or []


def fetch_urls_by_ids(client, url_ids: List[str]) -> List[Dict]:
    if not url_ids:
        return []
    response = (
        client.table("news_urls")
        .select("id,url")
        .in_("id", url_ids)
        .execute()
    )
    rows = getattr(response, "data", []) or []
    requested_order = {url_id: index for index, url_id in enumerate(url_ids)}
    rows.sort(key=lambda row: requested_order.get(row.get("id", ""), 10**9))
    return rows


def parse_url_ids(args: argparse.Namespace) -> List[str]:
    if args.url_ids:
        return [value.strip() for value in args.url_ids.split(",") if value.strip()]
    if args.url_ids_file:
        if not args.url_ids_file.exists():
            raise SystemExit(f"URL IDs file not found: {args.url_ids_file}")
        return [
            line.strip()
            for line in args.url_ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return []


def build_runtime_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        content_file=None,
        model=args.model,
        embedding_model=args.embedding_model,
        no_embeddings=args.no_embeddings,
        force=False,
        force_playwright=args.force_playwright,
        dry_run=args.dry_run,
        output=None,
        verbose=False,
    )


def main() -> None:
    args = parse_args()
    setup_logging()
    load_env()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")

    client = get_supabase_client()
    explicit_url_ids = parse_url_ids(args)
    if explicit_url_ids:
        pending_urls = fetch_urls_by_ids(client, explicit_url_ids)
    else:
        pending_urls = fetch_pending_urls(
            client,
            limit=args.limit,
            max_age_hours=args.max_age_hours,
        )

    if not pending_urls:
        print("No content-ready URLs pending facts")
        return

    runtime_args = build_runtime_args(args)
    stats = {
        "selected": len(pending_urls),
        "processed": 0,
        "failed": 0,
    }
    successful_url_ids: List[str] = []

    for row in pending_urls:
        url_id = row.get("id")
        article_url = row.get("url")
        if not url_id or not article_url:
            stats["failed"] += 1
            continue

        try:
            success = process_single_article(
                client,
                str(url_id),
                str(article_url),
                runtime_args,
                api_key,
            )
        except Exception as exc:
            logger.error("Realtime facts failed for %s: %s", url_id, exc, exc_info=True)
            success = False

        if success:
            stats["processed"] += 1
            successful_url_ids.append(str(url_id))
        else:
            stats["failed"] += 1

    if args.output_success_ids_file:
        args.output_success_ids_file.parent.mkdir(parents=True, exist_ok=True)
        args.output_success_ids_file.write_text(
            "\n".join(successful_url_ids) + ("\n" if successful_url_ids else ""),
            encoding="utf-8",
        )
        logger.info(
            "Wrote %d fact-processed URL IDs to %s",
            len(successful_url_ids),
            args.output_success_ids_file,
        )

    print("\n" + "=" * 52)
    print("REALTIME FACTS WORKER")
    print("=" * 52)
    print(f"URLs selected:   {stats['selected']}")
    print(f"URLs processed:  {stats['processed']}")
    print(f"URLs failed:     {stats['failed']}")
    print("=" * 52)


if __name__ == "__main__":
    main()
