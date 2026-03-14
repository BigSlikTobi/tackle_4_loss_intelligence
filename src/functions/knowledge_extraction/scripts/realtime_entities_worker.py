#!/usr/bin/env python3
"""Near-real-time entity extraction worker for facts missing entity rows."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.db.connection import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.knowledge_extraction.core.db.completion_tracker import (
    KnowledgeCompletionTracker,
)
from src.functions.knowledge_extraction.core.db.knowledge_writer import KnowledgeWriter
from src.functions.knowledge_extraction.core.extraction.entity_extractor import (
    EntityExtractor,
    ExtractedEntity,
)
from src.functions.knowledge_extraction.core.resolution.entity_resolver import (
    EntityResolver,
    ResolvedEntity,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process a small realtime queue of facts missing entities")
    parser.add_argument("--limit", type=int, default=250, help="Maximum facts to process per run")
    parser.add_argument(
        "--news-url-ids",
        type=str,
        help="Comma-separated news_url IDs to scope entity extraction",
    )
    parser.add_argument(
        "--news-url-ids-file",
        type=Path,
        help="File containing news_url IDs to scope entity extraction",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=250,
        help="Maximum rows to fetch from Supabase per page",
    )
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=None,
        help="Only process facts created within this many hours",
    )
    parser.add_argument(
        "--model",
        default="gpt-5-nano",
        help="OpenAI model for entity extraction",
    )
    parser.add_argument(
        "--max-entities",
        type=int,
        default=10,
        help="Maximum entities to request per fact",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction without persisting results",
    )
    return parser.parse_args()


def fetch_pending_facts(
    client,
    *,
    limit: int,
    page_size: int,
    max_age_hours: Optional[int],
    news_url_ids: Optional[Sequence[str]],
) -> List[Dict]:
    pending: List[Dict] = []
    offset = 0

    cutoff_iso = None
    if max_age_hours and max_age_hours > 0:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()

    while len(pending) < limit:
        fetch_count = min(page_size, limit - len(pending))
        query = (
            client.table("news_facts")
            .select("id,fact_text,news_url_id,news_fact_entities!left(id),news_urls!inner(id)")
            .is_("news_fact_entities.id", None)
            .is_("news_urls.knowledge_extracted_at", None)
            .order("created_at", desc=True)
            .range(offset, offset + fetch_count - 1)
        )
        if news_url_ids:
            query = query.in_("news_url_id", list(news_url_ids))
        if cutoff_iso:
            query = query.gte("created_at", cutoff_iso)

        response = query.execute()
        rows = getattr(response, "data", []) or []
        if not rows:
            break

        for row in rows:
            fact_id = row.get("id")
            fact_text = (row.get("fact_text") or "").strip()
            news_url_id = row.get("news_url_id")
            if fact_id and fact_text and news_url_id:
                pending.append(
                    {
                        "id": fact_id,
                        "fact_text": fact_text,
                        "news_url_id": news_url_id,
                    }
                )
                if len(pending) >= limit:
                    break

        offset += len(rows)
        if len(rows) < fetch_count:
            break

    return pending


def parse_news_url_ids(args: argparse.Namespace) -> List[str]:
    if args.news_url_ids:
        return [value.strip() for value in args.news_url_ids.split(",") if value.strip()]
    if args.news_url_ids_file:
        if not args.news_url_ids_file.exists():
            raise SystemExit(f"News URL IDs file not found: {args.news_url_ids_file}")
        return [
            line.strip()
            for line in args.news_url_ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return []


def build_no_entity_marker() -> ResolvedEntity:
    return ResolvedEntity(
        entity_type="none",
        entity_id="NO_ENTITIES_FOUND",
        mention_text="[no entities extracted]",
        matched_name="[no entities extracted]",
        confidence=0.0,
    )


def resolve_entities(
    extracted_entities: Sequence[ExtractedEntity],
    resolver: EntityResolver,
) -> List[ResolvedEntity]:
    resolved: List[ResolvedEntity] = []
    for entity in extracted_entities:
        try:
            resolved_entity: Optional[ResolvedEntity] = None
            if entity.entity_type == "player":
                resolved_entity = resolver.resolve_player(
                    entity.mention_text,
                    context=entity.context,
                    position=entity.position,
                    team_abbr=entity.team_abbr,
                    team_name=entity.team_name,
                )
            elif entity.entity_type == "team":
                resolved_entity = resolver.resolve_team(
                    entity.mention_text,
                    context=entity.context,
                )
            elif entity.entity_type == "game":
                resolved_entity = resolver.resolve_game(
                    entity.mention_text,
                    context=entity.context,
                )

            if not resolved_entity:
                continue

            resolved_entity.is_primary = entity.is_primary
            resolved_entity.rank = entity.rank
            if entity.entity_type == "player":
                resolved_entity.position = entity.position
                resolved_entity.team_abbr = entity.team_abbr
                resolved_entity.team_name = entity.team_name

            resolved.append(resolved_entity)
        except Exception as exc:
            logger.warning("Failed to resolve entity %s: %s", entity.mention_text, exc)
    return resolved


def main() -> None:
    args = parse_args()
    setup_logging()
    load_env()

    client = get_supabase_client()
    writer = KnowledgeWriter()
    resolver = EntityResolver()
    extractor = EntityExtractor(model=args.model)
    completion_tracker = KnowledgeCompletionTracker(client=writer.client)
    scoped_url_ids = parse_news_url_ids(args)

    pending_facts = fetch_pending_facts(
        client,
        limit=args.limit,
        page_size=args.page_size,
        max_age_hours=args.max_age_hours,
        news_url_ids=scoped_url_ids or None,
    )
    if not pending_facts:
        print("No facts pending entity extraction")
        return

    stats = {
        "selected": len(pending_facts),
        "processed": 0,
        "skipped_existing": 0,
        "skipped_no_data": 0,
        "failed": 0,
        "entities_written": 0,
        "urls_completed": 0,
    }
    processed_fact_ids: List[str] = []

    existing_response = (
        writer.client.table("news_fact_entities")
        .select("news_fact_id")
        .in_("news_fact_id", [row["id"] for row in pending_facts])
        .execute()
    )
    existing_fact_ids = {
        row["news_fact_id"]
        for row in (getattr(existing_response, "data", []) or [])
        if row.get("news_fact_id")
    }

    # Filter out already-existing facts
    facts_to_process = [
        row for row in pending_facts if row["id"] not in existing_fact_ids
    ]
    stats["skipped_existing"] = len(pending_facts) - len(facts_to_process)

    # Use batched multi-fact extraction (Phase 3 optimization)
    if facts_to_process:
        multi_results = extractor.extract_multi(
            facts_to_process,
            max_entities_per_fact=args.max_entities,
            chunk_size=15,
        )

        for row in facts_to_process:
            fact_id = row["id"]
            try:
                extracted = multi_results.get(fact_id, [])
                resolved = resolve_entities(extracted, resolver)
                if not resolved:
                    resolved = [build_no_entity_marker()]
                    stats["skipped_no_data"] += 1

                written = writer.write_fact_entities(
                    news_fact_id=fact_id,
                    entities=resolved,
                    llm_model=args.model,
                    dry_run=args.dry_run,
                )
                stats["entities_written"] += written
                stats["processed"] += 1
                processed_fact_ids.append(fact_id)
            except Exception as exc:
                stats["failed"] += 1
                logger.error("Realtime entities failed for %s: %s", fact_id, exc, exc_info=True)

    if processed_fact_ids:
        stats["urls_completed"] = completion_tracker.mark_complete_for_fact_ids(
            processed_fact_ids,
            dry_run=args.dry_run,
        )

    print("\n" + "=" * 52)
    print("REALTIME ENTITIES WORKER")
    print("=" * 52)
    print(f"Facts selected:       {stats['selected']}")
    print(f"Facts processed:      {stats['processed']}")
    print(f"Facts skipped exist:  {stats['skipped_existing']}")
    print(f"Facts no entities:    {stats['skipped_no_data']}")
    print(f"Facts failed:         {stats['failed']}")
    print(f"Entities written:     {stats['entities_written']}")
    print(f"URLs completed:       {stats['urls_completed']}")
    print("=" * 52)


if __name__ == "__main__":
    main()
