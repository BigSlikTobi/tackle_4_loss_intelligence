"""Content summarization pipeline CLI for multi-step fact-first processing."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

logger = logging.getLogger(__name__)

FACT_PROMPT_VERSION = "facts-v1"
SUMMARY_PROMPT_VERSION = "summary-from-facts-v1"
DEFAULT_FACT_MODEL = "gemma-3n"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EDGE_FUNCTION_NAME = "get-pending-news-urls"

FACT_PROMPT = """ASK: Extract discrete facts from the article. Closed world. No inferences.

RULES
- Use only the information explicitly stated in the text.
- Do not infer motivations, causes, consequences, or relationships.
- Do not add external knowledge.
- Maintain the original order of the article.
- Keep each statement short, specific, and self-contained.
- Exactly ONE factual claim per statement. Avoid using “and” to combine different events.
- Prefer repeating full player names, team names, and entities instead of pronouns when it improves clarity.
- Preserve all numbers, dates, scores, contract amounts, and durations exactly as written.
- Ignore navigation menus, cookie banners, share buttons, and other website boilerplate. Only use the main article content.
- Include all player names, team names, dates, trades, quotes, contract references, injuries, and statements about future plans that are explicitly stated.
- If something is not in the article, do NOT mention it.

INSTRUCTIONS
1. Divide the article into logical segments in your reasoning.
2. Extract each factual statement as a separate item.
3. Do not summarize or compress multiple facts into one statement.
4. Do not omit any named entity or event that appears in a factual statement.

INVALID EXAMPLES (DO NOT DO):
- "Gardner was traded to Team X" when not stated → INVALID inference
- "Johnson demanded a trade" if not stated → INVALID inference
- Adding any commentary, opinions, or analysis.

OUTPUT FORMAT (JSON only):
{
  "facts": [
    "fact 1",
    "fact 2",
    "fact 3"
  ]
}

Output ONLY valid JSON. No extra text, no comments, no explanations.
"""

SUMMARY_PROMPT = """TASK: Summarize using ONLY the provided "facts". Closed world.

RULES
- You may only use content from the `facts` list.
- Do not infer or guess missing information.
- Do not add external knowledge.
- Preserve all named entities and the relationships stated in the facts.
- Maintain chronological order.
- Reduce redundancy and remove filler language.
- Keep the summary concise, factual, and information-dense.
- Write the summary as continuous prose (one or more paragraphs), not as bullet points.
- If multiple facts describe the same event, merge them into a single clear sentence.

CHECKLIST BEFORE OUTPUT
- Every player and team mentioned in the facts is mentioned in the summary.
- Every distinct event or transaction mentioned in the facts is represented at least once.
- No new assumptions or external information were introduced.

OUTPUT FORMAT (JSON only):
{
  "summary": "your complete summarized text here"
}
"""


@dataclass
class PipelineConfig:
    """Runtime configuration for the content pipeline."""

    edge_function_base_url: str
    content_extraction_url: str
    llm_api_url: str
    llm_api_key: str
    embedding_api_url: str
    embedding_api_key: str
    fact_llm_model: str = DEFAULT_FACT_MODEL
    summary_llm_model: str = DEFAULT_FACT_MODEL
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL
    batch_limit: int = 25
    llm_timeout_seconds: int = 60
    embedding_timeout_seconds: int = 30
    content_timeout_seconds: int = 45


def build_config(env: Dict[str, str]) -> PipelineConfig:
    """Create pipeline configuration from environment variables."""

    required_keys = [
        "EDGE_FUNCTION_BASE_URL",
        "CONTENT_EXTRACTION_URL",
        "LLM_API_URL",
        "LLM_API_KEY",
    ]
    missing = [key for key in required_keys if not env.get(key)]
    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    batch_limit = int(env.get("BATCH_LIMIT", "25"))
    llm_timeout = int(env.get("LLM_TIMEOUT_SECONDS", "60"))
    embedding_timeout = int(env.get("EMBEDDING_TIMEOUT_SECONDS", "30"))
    content_timeout = int(env.get("CONTENT_TIMEOUT_SECONDS", "45"))

    return PipelineConfig(
        edge_function_base_url=env["EDGE_FUNCTION_BASE_URL"],
        content_extraction_url=env["CONTENT_EXTRACTION_URL"],
        llm_api_url=env["LLM_API_URL"],
        llm_api_key=env["LLM_API_KEY"],
        embedding_api_url=env.get("EMBEDDING_API_URL", env["LLM_API_URL"]),
        embedding_api_key=env.get("EMBEDDING_API_KEY", env["LLM_API_KEY"]),
        fact_llm_model=env.get("FACT_LLM_MODEL", DEFAULT_FACT_MODEL),
        summary_llm_model=env.get("SUMMARY_LLM_MODEL", env.get("FACT_LLM_MODEL", DEFAULT_FACT_MODEL)),
        embedding_model_name=env.get("EMBEDDING_MODEL_NAME", DEFAULT_EMBEDDING_MODEL),
        batch_limit=batch_limit,
        llm_timeout_seconds=llm_timeout,
        embedding_timeout_seconds=embedding_timeout,
        content_timeout_seconds=content_timeout,
    )


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description="Run the content pipeline stages.")
    parser.add_argument(
        "--stage",
        choices=["content", "facts", "summary", "full"],
        default="facts",
        help="Pipeline stage to run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Override batch size limit fetched from pending URL edge function.",
    )

    args = parser.parse_args()

    load_env()
    setup_logging()

    env = dict(os.environ)
    config = build_config(env)
    if args.limit:
        config.batch_limit = args.limit

    logger.info(
        "Starting content pipeline stage", {"stage": args.stage, "limit": config.batch_limit}
    )

    client = get_supabase_client()

    if args.stage in {"content", "full"}:
        process_content_stage(client, config)

    if args.stage in {"facts", "full"}:
        process_facts_stage(client, config)

    if args.stage in {"summary", "full"}:
        process_summary_stage(client, config)

    logger.info("Completed content pipeline run", {"stage": args.stage})


def process_content_stage(client, config: PipelineConfig) -> None:
    """Fetch article content to mark content_extracted_at."""

    urls = fetch_pending_urls("content", config)
    if not urls:
        logger.info("No URLs pending content extraction.")
        return

    logger.info("Processing content stage", {"count": len(urls)})
    for item in urls:
        url_id = item.get("id")
        article_url = item.get("url")
        if not url_id or not article_url:
            logger.warning("Skipping malformed URL payload", {"item": item})
            continue
        try:
            article_text = fetch_article_content(article_url, config)
            if not article_text:
                logger.warning(
                    "No content returned from extractor", {"news_url_id": url_id}
                )
                continue
            mark_news_url_timestamp(client, url_id, "content_extracted_at")
        except Exception:
            logger.exception(
                "Failed to fetch content for URL", {"news_url_id": url_id, "url": article_url}
            )
            continue


def process_facts_stage(client, config: PipelineConfig) -> None:
    """Process pending URLs to extract facts and embeddings."""

    urls = fetch_pending_urls("facts", config)
    if not urls:
        logger.info("No URLs pending fact extraction.")
        return

    logger.info("Processing facts stage", {"count": len(urls)})
    for item in urls:
        url_id = item.get("id")
        article_url = item.get("url")
        if not url_id or not article_url:
            logger.warning("Skipping malformed URL payload", {"item": item})
            continue

        try:
            article_text = fetch_article_content(article_url, config)
            if not article_text:
                logger.warning("Extractor returned empty article", {"news_url_id": url_id})
                continue

            mark_news_url_timestamp(client, url_id, "content_extracted_at")

            facts = extract_facts(article_text, config)
            if not facts:
                logger.warning("LLM produced no facts", {"news_url_id": url_id})
                continue

            fact_ids = store_facts(client, url_id, facts, config)
            if not fact_ids:
                logger.info("Facts already existed or insert skipped", {"news_url_id": url_id})
            else:
                logger.info(
                    "Stored facts for URL",
                    {"news_url_id": url_id, "fact_count": len(fact_ids)},
                )

            create_fact_embeddings(client, fact_ids, config)
            create_fact_pooled_embedding(client, url_id, config)

            if fact_stage_completed(client, url_id):
                mark_news_url_timestamp(client, url_id, "facts_extracted_at")
            else:
                logger.warning(
                    "Fact stage incomplete after processing",
                    {"news_url_id": url_id},
                )
        except Exception:
            logger.exception(
                "Failed to process facts stage for URL",
                {"news_url_id": url_id, "url": article_url},
            )
            continue


def process_summary_stage(client, config: PipelineConfig) -> None:
    """Generate summaries and summary embeddings from stored facts."""

    urls = fetch_pending_urls("summary", config)
    if not urls:
        logger.info("No URLs pending summary generation.")
        return

    logger.info("Processing summary stage", {"count": len(urls)})
    for item in urls:
        url_id = item.get("id")
        if not url_id:
            logger.warning("Skipping malformed URL payload", {"item": item})
            continue

        try:
            summary_text = create_summary_from_facts(client, url_id, config)
            if not summary_text:
                logger.warning("Summary generation returned empty text", {"news_url_id": url_id})
                continue

            stored_summary = store_summary(client, url_id, summary_text, config)
            if stored_summary:
                logger.info("Stored summary", {"news_url_id": url_id})
            else:
                logger.info("Summary already existed", {"news_url_id": url_id})

            create_summary_embedding(client, url_id, config)

            if summary_stage_completed(client, url_id):
                mark_news_url_timestamp(client, url_id, "summary_created_at")
            else:
                logger.warning(
                    "Summary stage incomplete after processing", {"news_url_id": url_id}
                )
        except Exception:
            logger.exception(
                "Failed to process summary stage for URL", {"news_url_id": url_id}
            )
            continue


def fetch_pending_urls(stage: str, config: PipelineConfig) -> List[Dict[str, Any]]:
    """Call the Supabase Edge Function to fetch pending URLs."""

    endpoint = f"{config.edge_function_base_url.rstrip('/')}/{EDGE_FUNCTION_NAME}"
    params = {"stage": stage, "limit": str(config.batch_limit)}
    try:
        response = requests.get(endpoint, params=params, timeout=15)
    except requests.RequestException as exc:
        logger.error("Edge function request failed", {"stage": stage, "error": str(exc)})
        return []

    if response.status_code != 200:
        logger.error(
            "Edge function returned non-200",
            {"stage": stage, "status": response.status_code, "body": response.text},
        )
        return []

    try:
        payload = response.json()
    except ValueError:
        logger.error("Edge function response was not valid JSON", {"stage": stage})
        return []

    urls = payload.get("urls")
    if not isinstance(urls, list):
        logger.error("Edge function payload missing 'urls' list", {"stage": stage})
        return []

    logger.info(
        "Fetched pending URLs",
        {"stage": stage, "count": len(urls), "limit": params["limit"]},
    )
    return urls


def fetch_article_content(url: str, config: PipelineConfig) -> str:
    """Fetch article content from the extraction service."""

    payload = {"url": url}
    headers = {"Content-Type": "application/json"}

    for attempt in range(3):
        try:
            response = requests.post(
                config.content_extraction_url,
                json=payload,
                headers=headers,
                timeout=config.content_timeout_seconds,
            )
            if response.status_code >= 500:
                logger.warning(
                    "Extractor server error", {"status": response.status_code, "attempt": attempt + 1}
                )
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                logger.error(
                    "Extractor returned non-200",
                    {"status": response.status_code, "body": response.text},
                )
                return ""
            data = response.json()
            content = data.get("content")
            if isinstance(content, str):
                return content.strip()
            logger.warning("Extractor response missing 'content' field")
            return ""
        except requests.RequestException as exc:
            logger.warning(
                "Extractor request failed",
                {"error": str(exc), "attempt": attempt + 1, "url": url},
            )
            time.sleep(2 ** attempt)
    return ""


def extract_facts(article_text: str, config: PipelineConfig) -> List[str]:
    """Extract atomic facts from article text using the LLM."""

    for attempt in range(2):
        response_json = call_llm_json(
            prompt=FACT_PROMPT,
            user_content=article_text,
            model=config.fact_llm_model,
            config=config,
        )
        facts = parse_fact_response(response_json)
        if facts:
            return facts
        logger.warning("LLM returned invalid facts payload", {"attempt": attempt + 1})
    return []


def call_llm_json(
    *, prompt: str, user_content: str, model: str, config: PipelineConfig
) -> Dict[str, Any]:
    """Call the LLM endpoint and return parsed JSON content if possible."""

    headers = {
        "Authorization": f"Bearer {config.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }

    try:
        response = requests.post(
            config.llm_api_url,
            headers=headers,
            json=payload,
            timeout=config.llm_timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("LLM request failed", {"model": model, "error": str(exc)})
        return {}

    try:
        data = response.json()
    except ValueError:
        logger.error("LLM response was not valid JSON", {"model": model})
        return {}

    # Support OpenAI-style responses with choices
    if isinstance(data, dict) and "choices" in data:
        try:
            message = data["choices"][0]["message"]["content"]
            return json.loads(message)
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            logger.error("Failed to parse choices message JSON", {"error": str(exc)})
            return {}

    if isinstance(data, dict):
        return data

    logger.error("LLM response had unexpected format", {"type": type(data).__name__})
    return {}


def parse_fact_response(payload: Dict[str, Any]) -> List[str]:
    """Validate and normalize facts payload."""

    facts_raw = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(facts_raw, list):
        return []

    facts: List[str] = []
    for item in facts_raw:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                facts.append(cleaned)
    return facts


def store_facts(
    client,
    news_url_id: int,
    facts: Sequence[str],
    config: PipelineConfig,
) -> List[int]:
    """Insert extracted facts into news_facts table."""

    if not facts:
        return []

    existing_ids = fetch_existing_fact_ids(client, news_url_id)
    if existing_ids:
        logger.info(
            "Facts already present for URL, skipping insert", {"news_url_id": news_url_id}
        )
        return existing_ids

    records = [
        {
            "news_url_id": news_url_id,
            "fact_text": fact,
            "llm_model": config.fact_llm_model,
            "prompt_version": FACT_PROMPT_VERSION,
        }
        for fact in facts
    ]

    response = client.table("news_facts").insert(records).select("id").execute()
    data = getattr(response, "data", []) or []
    return [row.get("id") for row in data if isinstance(row, dict) and row.get("id")]


def fetch_existing_fact_ids(client, news_url_id: int) -> List[int]:
    """Fetch existing fact IDs for a URL."""

    page_size = 1000
    offset = 0
    fact_ids: List[int] = []

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


def create_fact_embeddings(client, fact_ids: Sequence[int], config: PipelineConfig) -> None:
    """Create embeddings for new facts and store them."""

    pending_ids = [fact_id for fact_id in fact_ids if fact_id is not None]
    if not pending_ids:
        return

    existing = (
        client.table("facts_embeddings")
        .select("news_fact_id")
        .in_("news_fact_id", pending_ids)
        .execute()
    )
    existing_ids = {row.get("news_fact_id") for row in (getattr(existing, "data", []) or [])}
    to_embed = [fact_id for fact_id in pending_ids if fact_id not in existing_ids]

    if not to_embed:
        logger.info("All fact embeddings already exist", {"count": len(pending_ids)})
        return

    logger.info("Creating fact embeddings", {"count": len(to_embed)})

    chunks = list(chunked(to_embed, 200))
    for chunk in chunks:
        facts_response = (
            client.table("news_facts")
            .select("id,fact_text")
            .in_("id", chunk)
            .order("id", ascending=True)
            .execute()
        )
        rows = getattr(facts_response, "data", []) or []
        for row in rows:
            fact_id = row.get("id")
            fact_text = row.get("fact_text", "")
            if not fact_id or not fact_text:
                continue
            embedding = generate_embedding(fact_text, config)
            if not embedding:
                logger.warning(
                    "Embedding API returned empty vector", {"news_fact_id": fact_id}
                )
                continue
            client.table("facts_embeddings").insert(
                {
                    "news_fact_id": fact_id,
                    "embedding_vector": embedding,
                    "model_name": config.embedding_model_name,
                }
            ).execute()


def generate_embedding(text: str, config: PipelineConfig) -> List[float]:
    """Call embedding API to generate vector representation."""

    headers = {
        "Authorization": f"Bearer {config.embedding_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.embedding_model_name,
        "input": text,
    }

    try:
        response = requests.post(
            config.embedding_api_url,
            headers=headers,
            json=payload,
            timeout=config.embedding_timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Embedding request failed", {"error": str(exc)})
        return []

    try:
        data = response.json()
    except ValueError:
        logger.error("Embedding response was not valid JSON")
        return []

    if isinstance(data, dict):
        if "data" in data:
            try:
                return list(data["data"][0]["embedding"])
            except (KeyError, IndexError, TypeError):
                logger.error("Unexpected embedding payload structure with 'data'")
                return []
        if "embedding" in data:
            embedding = data.get("embedding")
            if isinstance(embedding, list):
                return [float(value) for value in embedding]

    logger.error("Embedding response had unexpected format", {"payload": data})
    return []


def create_fact_pooled_embedding(client, news_url_id: int, config: PipelineConfig) -> None:
    """Create URL-level embedding by averaging fact embeddings."""

    existing = (
        client.table("story_embeddings")
        .select("id")
        .eq("news_url_id", news_url_id)
        .eq("embedding_type", "fact_pooled")
        .limit(1)
        .execute()
    )
    if getattr(existing, "data", []):
        logger.info(
            "Fact pooled embedding already exists", {"news_url_id": news_url_id}
        )
        return

    fact_ids = fetch_existing_fact_ids(client, news_url_id)
    if not fact_ids:
        logger.warning("Cannot create pooled embedding without facts", {"news_url_id": news_url_id})
        return

    embeddings: List[List[float]] = []
    for chunk in chunked(fact_ids, 200):
        response = (
            client.table("facts_embeddings")
            .select("embedding_vector")
            .in_("news_fact_id", chunk)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        for row in rows:
            vector = row.get("embedding_vector")
            if isinstance(vector, list) and vector:
                embeddings.append([float(value) for value in vector])

    if not embeddings:
        logger.warning("No fact embeddings available for pooling", {"news_url_id": news_url_id})
        return

    averaged = average_vectors(embeddings)
    if not averaged:
        logger.warning("Failed to compute pooled embedding", {"news_url_id": news_url_id})
        return

    client.table("story_embeddings").insert(
        {
            "news_url_id": news_url_id,
            "embedding_vector": averaged,
            "model_name": config.embedding_model_name,
            "embedding_type": "fact_pooled",
        }
    ).execute()


def average_vectors(vectors: Sequence[Sequence[float]]) -> List[float]:
    """Average vectors element-wise."""

    if not vectors:
        return []
    dimension = len(vectors[0])
    totals = [0.0] * dimension
    count = 0
    for vector in vectors:
        if len(vector) != dimension:
            logger.warning("Skipping vector with mismatched dimension")
            continue
        for index, value in enumerate(vector):
            totals[index] += float(value)
        count += 1
    if count == 0:
        return []
    return [value / count for value in totals]


def create_summary_from_facts(
    client,
    news_url_id: int,
    config: PipelineConfig,
) -> str:
    """Generate summary from stored facts."""

    facts = fetch_fact_texts(client, news_url_id)
    if not facts:
        logger.warning("No facts available for summary", {"news_url_id": news_url_id})
        return ""

    facts_payload = json.dumps({"facts": facts}, ensure_ascii=False)
    for attempt in range(2):
        response_json = call_llm_json(
            prompt=SUMMARY_PROMPT,
            user_content=facts_payload,
            model=config.summary_llm_model,
            config=config,
        )
        summary = parse_summary_response(response_json)
        if summary:
            return summary
        logger.warning("LLM returned invalid summary payload", {"attempt": attempt + 1})
    return ""


def fetch_fact_texts(client, news_url_id: int) -> List[str]:
    """Fetch fact text for a URL with pagination."""

    page_size = 1000
    offset = 0
    facts: List[str] = []

    while True:
        response = (
            client.table("news_facts")
            .select("fact_text")
            .eq("news_url_id", news_url_id)
            .order("id", ascending=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        for row in rows:
            fact_text = row.get("fact_text")
            if isinstance(fact_text, str) and fact_text.strip():
                facts.append(fact_text.strip())
        if len(rows) < page_size:
            break
        offset += page_size

    return facts


def parse_summary_response(payload: Dict[str, Any]) -> str:
    """Validate summary payload."""

    if not isinstance(payload, dict):
        return ""
    summary = payload.get("summary")
    if isinstance(summary, str):
        return summary.strip()
    return ""


def store_summary(
    client,
    news_url_id: int,
    summary_text: str,
    config: PipelineConfig,
) -> bool:
    """Insert summary if not already present. Returns True when inserted."""

    existing = (
        client.table("context_summaries")
        .select("id")
        .eq("news_url_id", news_url_id)
        .eq("prompt_version", SUMMARY_PROMPT_VERSION)
        .limit(1)
        .execute()
    )
    if getattr(existing, "data", []):
        logger.info("Summary already exists for URL", {"news_url_id": news_url_id})
        return False

    client.table("context_summaries").insert(
        {
            "news_url_id": news_url_id,
            "summary_text": summary_text,
            "llm_model": config.summary_llm_model,
            "prompt_version": SUMMARY_PROMPT_VERSION,
        }
    ).execute()
    return True


def create_summary_embedding(client, news_url_id: int, config: PipelineConfig) -> None:
    """Create embedding for stored summary."""

    existing = (
        client.table("story_embeddings")
        .select("id")
        .eq("news_url_id", news_url_id)
        .eq("embedding_type", "summary")
        .limit(1)
        .execute()
    )
    if getattr(existing, "data", []):
        logger.info("Summary embedding already exists", {"news_url_id": news_url_id})
        return

    summary_response = (
        client.table("context_summaries")
        .select("summary_text")
        .eq("news_url_id", news_url_id)
        .eq("prompt_version", SUMMARY_PROMPT_VERSION)
        .limit(1)
        .execute()
    )
    rows = getattr(summary_response, "data", []) or []
    if not rows:
        logger.warning("No summary available for embedding", {"news_url_id": news_url_id})
        return

    summary_text = rows[0].get("summary_text")
    if not isinstance(summary_text, str) or not summary_text.strip():
        logger.warning("Summary text missing or empty", {"news_url_id": news_url_id})
        return

    embedding = generate_embedding(summary_text, config)
    if not embedding:
        logger.warning("Failed to generate summary embedding", {"news_url_id": news_url_id})
        return

    client.table("story_embeddings").insert(
        {
            "news_url_id": news_url_id,
            "embedding_vector": embedding,
            "model_name": config.embedding_model_name,
            "embedding_type": "summary",
        }
    ).execute()


def fact_stage_completed(client, news_url_id: int) -> bool:
    """Check whether facts and pooled embedding exist for a URL."""

    facts_exists = (
        client.table("news_facts")
        .select("id")
        .eq("news_url_id", news_url_id)
        .limit(1)
        .execute()
    )
    if not getattr(facts_exists, "data", []):
        return False

    pooled_exists = (
        client.table("story_embeddings")
        .select("id")
        .eq("news_url_id", news_url_id)
        .eq("embedding_type", "fact_pooled")
        .limit(1)
        .execute()
    )
    return bool(getattr(pooled_exists, "data", []))


def summary_stage_completed(client, news_url_id: int) -> bool:
    """Check whether summary and summary embedding exist for a URL."""

    summary_exists = (
        client.table("context_summaries")
        .select("id")
        .eq("news_url_id", news_url_id)
        .eq("prompt_version", SUMMARY_PROMPT_VERSION)
        .limit(1)
        .execute()
    )
    if not getattr(summary_exists, "data", []):
        return False

    embedding_exists = (
        client.table("story_embeddings")
        .select("id")
        .eq("news_url_id", news_url_id)
        .eq("embedding_type", "summary")
        .limit(1)
        .execute()
    )
    return bool(getattr(embedding_exists, "data", []))


def mark_news_url_timestamp(client, news_url_id: int, column: str) -> None:
    """Mark a timestamp column on news_urls with current UTC time."""

    now_iso = datetime.now(timezone.utc).isoformat()
    client.table("news_urls").update({column: now_iso}).eq("id", news_url_id).execute()


def chunked(iterable: Sequence[int], size: int) -> Iterable[List[int]]:
    """Yield chunks from a sequence."""

    for index in range(0, len(iterable), size):
        yield list(iterable[index : index + size])


if __name__ == "__main__":
    main()
