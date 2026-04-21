"""Streamlined fact extraction post-processor for URL content extraction integration.

This module provides lightweight fact extraction for real-time processing (1-10 articles).
For bulk processing (1000+ articles), use the ``facts_batch`` pipeline instead.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Tuple

import httpx

# Single source of truth for the prompt and filter so the realtime path
# cannot drift from the batch path.
from ..facts.prompts import get_formatted_prompt
from ..facts.filter import filter_story_facts
from ..db import FactsReader, FactsWriter

logger = logging.getLogger(__name__)

DEFAULT_FACT_MODEL = "gemma-3n-e4b-it"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def extract_and_store_facts(
    article_content: str,
    news_url_id: str,
    supabase_config: Dict[str, str],
    llm_config: Dict[str, str],
    embedding_config: Dict[str, str],
) -> Dict[str, Any]:
    """Extract facts from article content and store to database.

    Streamlined single-article entry point for the url_extraction Cloud
    Function. Shares the facts schema layer (``FactsReader`` / ``FactsWriter``)
    with the batch path, so both paths insert, mark, and pool identically.

    Returns a dict with ``facts_count``, ``facts_extracted``, ``embedding_count``,
    and ``error``.
    """
    try:
        from supabase import create_client

        client = create_client(supabase_config["url"], supabase_config["key"])
        reader = FactsReader(client)
        writer = FactsWriter(client)

        model = llm_config.get("model", DEFAULT_FACT_MODEL)
        embedding_model = embedding_config.get("model", DEFAULT_EMBEDDING_MODEL)

        # 1. Extract facts via LLM.
        facts = _extract_facts_llm(
            article_content,
            llm_config["api_url"],
            llm_config["api_key"],
            model,
        )
        if not facts:
            return _result(0, False, 0, "No facts extracted from article")

        # 2. Filter (shared with batch path).
        filtered_facts, _rejected = filter_story_facts(facts)
        if not filtered_facts:
            return _result(
                0, False, 0,
                "All extracted facts were filtered as non-story content",
            )

        # 3. Skip if already stored.
        if reader.fetch_existing_fact_ids(news_url_id):
            logger.info("Facts already exist for %s", news_url_id)
            return _result(
                len(filtered_facts), True, 0,
                "Facts already exist or storage failed",
            )

        # 4. Insert — get back (ids, texts_by_id) so downstream stages skip a
        # redundant SELECT.
        fact_ids, texts_by_id = writer.insert_facts_for_article(
            news_url_id, filtered_facts, model
        )
        if not fact_ids:
            return _result(
                len(filtered_facts), True, 0,
                "Facts already exist or storage failed",
            )

        # 5. Embeddings + pooled article embedding (reusing in-memory vectors).
        embedding_count, fresh_vectors = _create_embeddings(
            reader,
            writer,
            fact_ids,
            texts_by_id,
            embedding_config["api_url"],
            embedding_config["api_key"],
            embedding_model,
        )
        if not reader.pooled_embedding_exists(news_url_id):
            writer.insert_pooled_embedding(
                news_url_id,
                fresh_vectors or reader.fetch_fact_embeddings(fact_ids),
                embedding_model,
            )

        # 6. Stamp facts_extracted_at; backfill content_extracted_at only
        # when still null (so we don't overwrite a truer upstream value).
        writer.mark_single_article_facts_extracted(news_url_id)

        return _result(len(fact_ids), True, embedding_count, None)

    except Exception as e:
        logger.error(
            "Fact extraction failed for %s: %s", news_url_id, e, exc_info=True
        )
        return _result(0, False, 0, str(e))


def _result(
    facts_count: int,
    facts_extracted: bool,
    embedding_count: int,
    error: str | None,
) -> Dict[str, Any]:
    return {
        "facts_count": facts_count,
        "facts_extracted": facts_extracted,
        "embedding_count": embedding_count,
        "error": error,
    }


# ---------------------------------------------------------------------------
# LLM fact extraction (Gemini)
# ---------------------------------------------------------------------------


def _extract_facts_llm(
    article_content: str,
    llm_api_url: str,
    llm_api_key: str,
    model: str,
) -> List[str]:
    """Call the Gemini API to extract facts and return them as a flat list."""
    formatted_prompt = get_formatted_prompt()
    url = f"{llm_api_url}/{model}:generateContent?key={llm_api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {"parts": [{"text": f"{formatted_prompt}\n\nArticle:\n{article_content}"}]}
        ],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 32000},
    }

    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error("LLM fact extraction failed: %s", e)
        return []

    if not isinstance(data, dict) or "candidates" not in data:
        logger.warning("Failed to parse LLM response for facts")
        return []

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Unexpected Gemini response shape")
        return []

    # Strip control characters.
    text = "".join(c for c in text if ord(c) >= 32 or c in "\t\n\r")

    # First: look for a ```json code block.
    json_match = re.search(r"```(?:json)?\s*(\{.*)", text, re.DOTALL)
    if json_match:
        json_str = re.sub(r"\s*```\s*$", "", json_match.group(1))
        json_str = "".join(c for c in json_str if ord(c) >= 32 or c in "\t\n\r")
        facts = _parse_facts_json(json_str)
        if facts is not None:
            return facts

    # Fallback: parse the whole message.
    facts = _parse_facts_json(text.strip())
    if facts is not None:
        return facts

    logger.warning("Failed to parse LLM response for facts")
    return []


def _parse_facts_json(raw: str) -> List[str] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    facts = parsed.get("facts") if isinstance(parsed, dict) else None
    if not isinstance(facts, list):
        return None
    return [f.strip() for f in facts if isinstance(f, str) and f.strip()]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def _create_embeddings(
    reader: FactsReader,
    writer: FactsWriter,
    fact_ids: List[str],
    texts_by_id: Dict[str, str],
    embedding_api_url: str,
    embedding_api_key: str,
    model: str,
) -> Tuple[int, List[List[float]]]:
    """Generate embeddings for ``fact_ids`` and persist them.

    Returns ``(inserted_count, vectors)``. ``vectors`` lets the caller feed
    the freshly-computed embeddings straight into pooled embedding creation
    without re-reading ``facts_embeddings``.
    """
    if not fact_ids:
        return 0, []

    existing = reader.check_existing_embeddings(fact_ids)
    facts_to_embed = [fid for fid in fact_ids if fid not in existing]
    if not facts_to_embed:
        return 0, []

    ordered_texts = [(fid, texts_by_id.get(fid, "")) for fid in facts_to_embed]
    ordered_texts = [(fid, text) for fid, text in ordered_texts if text]
    if not ordered_texts:
        return 0, []

    texts = [text for _, text in ordered_texts]
    embeddings = _generate_embeddings_batch(
        texts, embedding_api_url, embedding_api_key, model
    )
    if not embeddings or len(embeddings) != len(ordered_texts):
        logger.error("Embedding generation failed or count mismatch")
        return 0, []

    records: List[Dict[str, Any]] = []
    kept_vectors: List[List[float]] = []
    for (fid, _text), vector in zip(ordered_texts, embeddings):
        if vector:
            records.append(
                {
                    "news_fact_id": fid,
                    "embedding_vector": vector,
                    "model_name": model,
                }
            )
            kept_vectors.append(vector)

    inserted = writer.insert_fact_embeddings(records)
    if inserted:
        logger.info("Created %d embeddings", inserted)
    return inserted, kept_vectors


def _generate_embeddings_batch(
    texts: List[str],
    api_url: str,
    api_key: str,
    model: str,
) -> List[List[float]]:
    """Generate embeddings for ``texts`` in batches of 100 over a shared client."""
    if not texts:
        return []

    BATCH_SIZE = 100
    all_embeddings: List[List[float]] = []
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=30) as client:
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            try:
                response = client.post(
                    api_url,
                    headers=headers,
                    json={"model": model, "input": batch},
                )
                response.raise_for_status()
                data = response.json()

                batch_embeddings: List[List[float]] = []
                for item in data.get("data", []):
                    embedding = item.get("embedding", [])
                    if isinstance(embedding, list):
                        batch_embeddings.append(embedding)

                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                logger.error("Embedding batch failed: %s", e)
                all_embeddings.extend([[] for _ in batch])

    return all_embeddings
