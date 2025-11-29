"""Database storage operations for facts and embeddings."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Set

from .prompts import FACT_PROMPT_VERSION
from .filter import is_valid_nfl_fact

logger = logging.getLogger(__name__)


def store_facts(
    client,
    news_url_id: str,
    facts: Sequence[str],
    llm_model: str,
) -> List[str]:
    """Insert extracted facts into news_facts table.
    
    Args:
        client: Supabase client
        news_url_id: ID of the news URL
        facts: List of fact strings to store
        llm_model: Model used for extraction
        
    Returns:
        List of created fact IDs
    """
    if not facts:
        return []

    # Clean up any existing invalid facts first
    removed = remove_non_story_facts_from_db(client, news_url_id)
    if removed:
        logger.info(
            "Deleted existing non-story facts before insert",
            extra={"news_url_id": news_url_id, "removed": removed},
        )

    # Check for existing facts
    existing_ids = fetch_existing_fact_ids(client, news_url_id)
    if existing_ids:
        logger.info(
            "Facts already present for URL, skipping insert",
            extra={"news_url_id": news_url_id},
        )
        return existing_ids

    records = [
        {
            "news_url_id": news_url_id,
            "fact_text": fact,
            "llm_model": llm_model,
            "prompt_version": FACT_PROMPT_VERSION,
        }
        for fact in facts
    ]

    response = client.table("news_facts").insert(records).execute()
    data = getattr(response, "data", []) or []
    return [row.get("id") for row in data if isinstance(row, dict) and row.get("id")]


def fetch_existing_fact_ids(client, news_url_id: str) -> List[str]:
    """Fetch existing fact IDs for a URL.
    
    Args:
        client: Supabase client
        news_url_id: ID of the news URL
        
    Returns:
        List of fact IDs
    """
    page_size = 1000
    offset = 0
    fact_ids: List[str] = []

    while True:
        response = (
            client.table("news_facts")
            .select("id")
            .eq("news_url_id", news_url_id)
            .eq("prompt_version", FACT_PROMPT_VERSION)
            .order("id", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        fact_ids.extend([row.get("id") for row in rows if row.get("id") is not None])
        if len(rows) < page_size:
            break
        offset += page_size

    return fact_ids


def remove_non_story_facts_from_db(client, news_url_id: str) -> int:
    """Delete persisted facts (and embeddings) that fail validation.
    
    Args:
        client: Supabase client
        news_url_id: ID of the news URL
        
    Returns:
        Number of facts removed
    """
    response = (
        client.table("news_facts")
        .select("id,fact_text")
        .eq("news_url_id", news_url_id)
        .eq("prompt_version", FACT_PROMPT_VERSION)
        .execute()
    )

    rows = getattr(response, "data", []) or []
    if not rows:
        return 0

    invalid_ids: List[str] = []
    for row in rows:
        fact_id = row.get("id")
        fact_text = row.get("fact_text", "")
        if not fact_id or not isinstance(fact_text, str):
            continue
        if not is_valid_nfl_fact(fact_text):
            invalid_ids.append(fact_id)

    if not invalid_ids:
        return 0

    # Delete embeddings first (foreign key)
    client.table("facts_embeddings").delete().in_("news_fact_id", invalid_ids).execute()
    client.table("news_facts").delete().in_("id", invalid_ids).execute()

    logger.info(
        "Removed persisted non-story facts",
        extra={"news_url_id": news_url_id, "removed": len(invalid_ids)},
    )

    return len(invalid_ids)


def bulk_check_embeddings(client, fact_ids: Sequence[str]) -> Set[str]:
    """Check which facts already have embeddings.
    
    Args:
        client: Supabase client
        fact_ids: List of fact IDs to check
        
    Returns:
        Set of fact IDs that have embeddings
    """
    if not fact_ids:
        return set()

    existing_ids: Set[str] = set()
    page_size = 1000

    # Process in chunks to avoid query limits
    for i in range(0, len(fact_ids), page_size):
        chunk = list(fact_ids)[i:i + page_size]
        response = (
            client.table("facts_embeddings")
            .select("news_fact_id")
            .in_("news_fact_id", chunk)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        existing_ids.update(row.get("news_fact_id") for row in rows if row.get("news_fact_id"))

    return existing_ids


def create_fact_embeddings(
    client,
    fact_ids: Sequence[str],
    embedding_api_key: str,
    embedding_model: str = "text-embedding-3-small",
) -> int:
    """Create embeddings for facts and store them.
    
    Args:
        client: Supabase client
        fact_ids: List of fact IDs to create embeddings for
        embedding_api_key: OpenAI API key for embeddings
        embedding_model: Embedding model to use
        
    Returns:
        Number of embeddings created
    """
    import openai
    
    pending_ids = [fact_id for fact_id in fact_ids if fact_id is not None]
    if not pending_ids:
        return 0

    # Check existing
    existing = bulk_check_embeddings(client, pending_ids)
    to_embed = [fact_id for fact_id in pending_ids if fact_id not in existing]

    if not to_embed:
        logger.info("All fact embeddings already exist", extra={"count": len(pending_ids)})
        return 0

    # Fetch fact texts
    page_size = 100
    total_created = 0

    for i in range(0, len(to_embed), page_size):
        chunk_ids = to_embed[i:i + page_size]
        
        response = (
            client.table("news_facts")
            .select("id,fact_text")
            .in_("id", chunk_ids)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        
        if not rows:
            continue
        
        # Generate embeddings
        texts = [row.get("fact_text", "") for row in rows]
        ids = [row.get("id") for row in rows]
        
        try:
            openai.api_key = embedding_api_key
            embed_response = openai.embeddings.create(
                model=embedding_model,
                input=texts,
            )
            
            records = []
            for idx, embedding_data in enumerate(embed_response.data):
                records.append({
                    "news_fact_id": ids[idx],
                    "embedding_vector": embedding_data.embedding,
                    "model_name": embedding_model,
                })
            
            if records:
                client.table("facts_embeddings").insert(records).execute()
                total_created += len(records)
                logger.debug("Created %d fact embeddings", len(records))
                
        except Exception as e:
            logger.error("Failed to create embeddings: %s", e)
            continue

    logger.info("Created fact embeddings", extra={"count": total_created})
    return total_created


def bulk_store_facts(
    client,
    facts_by_url: Dict[str, List[str]],
    llm_model: str,
) -> Dict[str, List[str]]:
    """Bulk insert facts for multiple URLs.
    
    Args:
        client: Supabase client
        facts_by_url: Dict mapping news_url_id to list of fact strings
        llm_model: Model used for extraction
        
    Returns:
        Dict mapping news_url_id to list of created fact IDs
    """
    if not facts_by_url:
        return {}

    # Build all records
    all_records = []
    url_order = []  # Track order for mapping results back
    
    for news_url_id, facts in facts_by_url.items():
        for fact in facts:
            all_records.append({
                "news_url_id": news_url_id,
                "fact_text": fact,
                "llm_model": llm_model,
                "prompt_version": FACT_PROMPT_VERSION,
            })
            url_order.append(news_url_id)

    if not all_records:
        return {}

    # Insert in chunks
    chunk_size = 1000
    result_ids: Dict[str, List[str]] = {url_id: [] for url_id in facts_by_url}
    record_idx = 0

    for i in range(0, len(all_records), chunk_size):
        chunk = all_records[i:i + chunk_size]
        try:
            response = client.table("news_facts").insert(chunk).execute()
            data = getattr(response, "data", []) or []
            
            for row in data:
                if isinstance(row, dict) and row.get("id"):
                    url_id = url_order[record_idx]
                    result_ids[url_id].append(row["id"])
                record_idx += 1
                
        except Exception as e:
            logger.error("Failed to bulk insert facts: %s", e)
            record_idx += len(chunk)

    return result_ids


def bulk_insert_embeddings(
    client,
    records: List[Dict[str, Any]],
) -> int:
    """Bulk insert embedding records.
    
    Args:
        client: Supabase client
        records: List of embedding records with news_fact_id, embedding, model
        
    Returns:
        Number of embeddings inserted
    """
    if not records:
        return 0

    chunk_size = 1000
    total_inserted = 0

    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        try:
            response = client.table("facts_embeddings").insert(chunk).execute()
            inserted = len(getattr(response, "data", []) or [])
            total_inserted += inserted
            logger.debug("Inserted %d embeddings (batch %d)", inserted, i // chunk_size + 1)
        except Exception as e:
            logger.error("Failed to insert embedding batch: %s", e)

    return total_inserted
