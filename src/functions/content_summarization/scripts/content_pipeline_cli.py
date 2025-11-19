"""Content summarization pipeline CLI for multi-step fact-first processing."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.knowledge_extraction.core.pipelines.extraction_pipeline import (
    ExtractionPipeline,
)

logger = logging.getLogger(__name__)

FACT_PROMPT_VERSION = "facts-v1"
SUMMARY_PROMPT_VERSION = "summary-from-facts-v1"
TOPIC_SUMMARY_PROMPT_VERSION = "summary-from-facts-topic-v1"
DEFAULT_FACT_MODEL = "gemma-3n-e4b-it"  # Use Gemini model for fact extraction
DEFAULT_SUMMARY_MODEL = "gemma-3n-e4b-it"  # Chunking strategy for large fact sets
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

TOPIC_SUMMARY_TEMPLATE = """TASK: Summarize the provided NFL facts.

FOCUS
- Topic: {topic}
- Context: {context}

RULES
- Only use content from the `facts` list.
- Stay specific to the topic/context scope above.
- Keep the summary short (2-3 sentences) and information-dense.
- Mention the context label when relevant; otherwise note league-wide scope.

OUTPUT FORMAT (JSON only):
{{
  "summary": "your concise topic summary here"
}}
"""


@dataclass
class PipelineConfig:
    """Runtime configuration for the content pipeline."""

    edge_function_base_url: str
    content_extraction_url: Optional[str]
    llm_api_url: str
    llm_api_key: str
    embedding_api_url: str
    embedding_api_key: str
    fact_llm_model: str = DEFAULT_FACT_MODEL
    summary_llm_model: str = DEFAULT_SUMMARY_MODEL
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL
    batch_limit: int = 25
    llm_timeout_seconds: int = 60
    embedding_timeout_seconds: int = 30
    content_timeout_seconds: int = 45


def build_config(env: Dict[str, str]) -> PipelineConfig:
    """Create pipeline configuration from environment variables using standard vars."""

    # Required: Supabase URL for edge functions
    supabase_url = env.get("SUPABASE_URL")
    if not supabase_url:
        raise ValueError("Missing required environment variable: SUPABASE_URL")
    
    # Build edge function URL from Supabase URL
    edge_function_base_url = f"{supabase_url.rstrip('/')}/functions/v1"
    
    # Optional: Content extraction service URL (can skip if content already extracted)
    content_extraction_url = env.get("CONTENT_EXTRACTION_URL")
    if content_extraction_url:
        content_extraction_url = content_extraction_url.strip()
        if not content_extraction_url:
            content_extraction_url = None
    
    # Use Gemini API for LLM calls (fact extraction, summarization)
    gemini_key = env.get("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("Missing required environment variable: GEMINI_API_KEY")
    
    # Use OpenAI API for embeddings
    openai_key = env.get("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("Missing required environment variable: OPENAI_API_KEY")
    
    # Google Gemini API endpoint - note: model is appended in call_llm_json
    llm_api_url = "https://generativelanguage.googleapis.com/v1beta/models"
    embedding_api_url = "https://api.openai.com/v1/embeddings"
    
    batch_limit = int(env.get("BATCH_LIMIT", "25"))
    llm_timeout = int(env.get("LLM_TIMEOUT_SECONDS", "60"))
    embedding_timeout = int(env.get("EMBEDDING_TIMEOUT_SECONDS", "30"))
    content_timeout = int(env.get("CONTENT_TIMEOUT_SECONDS", "45"))

    return PipelineConfig(
        edge_function_base_url=edge_function_base_url,
        content_extraction_url=content_extraction_url,
        llm_api_url=llm_api_url,
        llm_api_key=gemini_key,
        embedding_api_url=embedding_api_url,
        embedding_api_key=openai_key,
        fact_llm_model=env.get("FACT_LLM_MODEL", DEFAULT_FACT_MODEL),
        summary_llm_model=env.get("SUMMARY_LLM_MODEL", DEFAULT_SUMMARY_MODEL),
        embedding_model_name=env.get("OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
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
        choices=["content", "facts", "knowledge", "summary", "full"],
        default="facts",
        help="Pipeline stage to run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Override batch size limit fetched from pending URL edge function.",
    )
    parser.add_argument(
        "--batch-mode",
        action="store_true",
        help="Enable batch processing mode (loops until no more URLs).",
    )
    parser.add_argument(
        "--max-total",
        type=int,
        help="Maximum total URLs to process across all batches (e.g., 5000 for most recent 5000).",
    )
    parser.add_argument(
        "--batch-delay",
        type=int,
        default=2,
        help="Delay in seconds between batches (default: 2).",
    )

    args = parser.parse_args()

    load_env()
    setup_logging()

    env = dict(os.environ)
    config = build_config(env)
    if args.limit:
        config.batch_limit = args.limit

    logger.info(
        "Starting content pipeline",
        {
            "stage": args.stage,
            "limit": config.batch_limit,
            "batch_mode": args.batch_mode,
            "max_total": args.max_total,
        }
    )

    client = get_supabase_client()

    if args.batch_mode:
        run_batch_mode(client, config, args)
    else:
        run_single_batch(client, config, args.stage)

    logger.info("Completed content pipeline run", {"stage": args.stage})


def run_single_batch(client, config: PipelineConfig, stage: str) -> None:
    """Run a single batch of the pipeline."""
    
    if stage in {"content", "full"}:
        process_content_stage(client, config)

    if stage in {"facts", "full"}:
        process_facts_stage(client, config)

    if stage in {"knowledge", "full"}:
        process_knowledge_stage(client, config)

    if stage in {"summary", "full"}:
        process_summary_stage(client, config)


def run_batch_mode(client, config: PipelineConfig, args) -> None:
    """Run pipeline in batch mode, processing multiple batches until complete."""
    
    total_processed = 0
    batch_num = 0
    max_total = args.max_total if args.max_total else float('inf')
    
    logger.info(
        "Starting batch mode",
        {
            "stage": args.stage,
            "batch_size": config.batch_limit,
            "max_total": max_total if max_total != float('inf') else "unlimited",
            "batch_delay": args.batch_delay,
        }
    )
    
    while total_processed < max_total:
        batch_num += 1
        remaining = max_total - total_processed if max_total != float('inf') else config.batch_limit
        current_batch_limit = min(config.batch_limit, int(remaining))
        
        logger.info(
            f"=== Batch {batch_num} ===",
            {
                "batch_size": current_batch_limit,
                "total_processed": total_processed,
                "remaining": int(remaining) if max_total != float('inf') else "unlimited",
            }
        )
        
        # Temporarily adjust batch limit for this batch
        original_limit = config.batch_limit
        config.batch_limit = current_batch_limit
        
        # Check if there are any pending URLs for this stage
        stage_to_check = args.stage if args.stage != "full" else "content"
        urls = fetch_pending_urls(stage=stage_to_check, config=config)
        
        if not urls:
            logger.info("No more pending URLs, batch processing complete")
            break
        
        processed_this_batch = len(urls)
        logger.info(f"Processing {processed_this_batch} URLs in batch {batch_num}")
        
        # Run the pipeline stages
        run_single_batch(client, config, args.stage)
        
        # Restore original limit
        config.batch_limit = original_limit
        
        total_processed += processed_this_batch
        
        logger.info(
            f"Batch {batch_num} complete",
            {
                "processed_this_batch": processed_this_batch,
                "total_processed": total_processed,
                "max_total": max_total if max_total != float('inf') else "unlimited",
            }
        )
        
        # Check if we've reached the limit
        if total_processed >= max_total:
            logger.info(f"Reached max_total limit of {max_total}, stopping")
            break
        
        # Small delay between batches to avoid rate limits
        if args.batch_delay > 0:
            logger.info(f"Waiting {args.batch_delay}s before next batch...")
            time.sleep(args.batch_delay)
    
    logger.info(
        "Batch mode complete",
        {
            "total_batches": batch_num,
            "total_urls_processed": total_processed,
            "max_total": max_total if max_total != float('inf') else "unlimited",
        }
    )


def process_content_stage(client, config: PipelineConfig) -> None:
    """Fetch article content to mark content_extracted_at."""

    if not config.content_extraction_url:
        logger.warning("Content extraction URL not configured, skipping content stage")
        return

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

            filtered_facts, rejected_facts = filter_story_facts(facts)
            if rejected_facts:
                logger.info(
                    "Post-processing rejected non-story facts",
                    {
                        "news_url_id": url_id,
                        "rejected_count": len(rejected_facts),
                        "sample": rejected_facts[:3],
                    },
                )

            if not filtered_facts:
                logger.warning(
                    "All extracted facts were rejected as non-story content",
                    {"news_url_id": url_id},
                )
                removed = remove_non_story_facts_from_db(client, url_id)
                if removed:
                    logger.info(
                        "Removed previously stored non-story facts",
                        {"news_url_id": url_id, "removed": removed},
                    )
                continue

            fact_ids = store_facts(client, url_id, filtered_facts, config)
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


def process_knowledge_stage(client, config: PipelineConfig) -> None:
    """Run knowledge extraction for pending URLs."""
    
    logger.info("Processing knowledge stage")
    
    try:
        # Use the existing ExtractionPipeline which handles its own DB querying
        # We pass the batch limit from our config
        pipeline = ExtractionPipeline(continue_on_error=True)
        results = pipeline.run(
            limit=config.batch_limit,
            dry_run=False,
            retry_failed=False
        )
        
        processed = results.get("urls_processed", 0)
        errors = results.get("urls_with_errors", 0)
        
        if processed > 0:
            logger.info(
                "Knowledge extraction completed", 
                {"processed": processed, "errors": errors}
            )
        else:
            logger.info("No URLs pending knowledge extraction")
            
    except Exception:
        logger.exception("Failed to run knowledge extraction pipeline")


def process_summary_stage(client, config: PipelineConfig) -> None:
    """Generate summaries or topic bundles based on article difficulty."""

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
            difficulty_record = get_article_difficulty(client, url_id)
            difficulty = difficulty_record.get("article_difficulty") if difficulty_record else None
            if not difficulty:
                logger.info(
                    "Skipping summary until knowledge extraction completes",
                    {"news_url_id": url_id},
                )
                continue

            if difficulty == "easy":
                handle_easy_article_summary(client, url_id, config)
            else:
                handle_hard_article_summary(client, url_id, config)

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
    
    # Get Supabase key for authentication
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_key:
        logger.error("SUPABASE_KEY not found in environment")
        return []
    
    # Add authentication headers required by Supabase edge functions
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=15)
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


def get_article_difficulty(client, news_url_id: str) -> Dict[str, Any]:
    """Fetch classification metadata computed during knowledge extraction."""

    response = (
        client.table("news_urls")
        .select("facts_count,article_difficulty")
        .eq("id", news_url_id)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", []) or []
    return rows[0] if rows else {}


def fetch_article_content(url: str, config: PipelineConfig) -> str:
    """Fetch article content from the extraction service.
    
    Note: Filtering of non-story content (author bios, navigation, etc.) is handled
    by Layer 2 (enhanced fact extraction prompt) and Layer 3 (post-processing filter).
    """

    if not config.content_extraction_url:
        logger.error("Content extraction URL not configured")
        return ""

    # Content extraction service expects {"urls": [...]} format
    # Note: Filtering is handled by enhanced fact extraction prompt (Layer 2)
    # and post-processing filter (Layer 3) - extraction service uses built-in selectors
    payload = {
        "urls": [url],
    }
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
                    f"Extractor server error for URL {url} (status {response.status_code}, attempt {attempt + 1}/3). Response preview: {response.text[:500]}"
                )
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                logger.error(
                    f"Extractor returned non-200 for URL {url}. Status: {response.status_code}, Response body: {response.text[:1000]}"
                )
                return ""
            data = response.json()
            # Response format: {"articles": [{"content": "...", ...}]}
            articles = data.get("articles", [])
            if not articles or not isinstance(articles, list):
                logger.warning(f"Extractor response missing 'articles' field. Response keys: {list(data.keys())}, data preview: {str(data)[:200]}")
                return ""
            
            article = articles[0]
            if "error" in article:
                logger.warning(f"Extractor returned error for URL {url}: {article.get('error')}. Status: {article.get('status')}. Full article: {article}")
                return ""
            
            content = article.get("content")
            if isinstance(content, str):
                return content.strip()
            logger.warning(f"Extractor article missing 'content' field. URL: {url}, Article keys: {list(article.keys())}, Article preview: {str(article)[:300]}")
            return ""
        except requests.RequestException as exc:
            logger.warning(
                f"Extractor request failed for URL {url} (attempt {attempt + 1}/3). Error: {exc}. Error type: {type(exc).__name__}"
            )
            if hasattr(exc, 'response') and exc.response is not None:
                logger.warning(f"Response status: {exc.response.status_code}, Response body preview: {exc.response.text[:500]}")
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

    # Build Gemini API URL with model
    url = f"{config.llm_api_url}/{model}:generateContent?key={config.llm_api_key}"
    
    headers = {
        "Content-Type": "application/json",
    }
    
    # Gemini API format - without JSON mode since gemma-3n-e4b-it doesn't support it
    payload = {
        "contents": [{
            "parts": [{
                "text": f"{prompt}\n\nArticle:\n{user_content}"
            }]
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 32000,  # Increased significantly to handle large fact sets (109+ facts)
        }
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=config.llm_timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        status = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
        body = getattr(exc.response, "text", None) if hasattr(exc, "response") else None
        logger.error(f"LLM request failed for model {model}: {exc}. Status: {status}. Body: {body}")
        return {}

    try:
        data = response.json()
    except ValueError:
        logger.error("LLM response was not valid JSON", {"model": model})
        return {}

    # Parse Gemini API response format
    if isinstance(data, dict) and "candidates" in data:
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            
            # Remove control characters that break JSON parsing
            # Keep only tab, newline, and carriage return (valid JSON whitespace)
            text = ''.join(char for char in text if ord(char) >= 32 or char in '\t\n\r')
            
            # Try to extract JSON from the text (model might include markdown code blocks)
            import re
            
            # First try: Match code block (may be incomplete/truncated)
            # Look for ```json (optional) followed by JSON
            json_match = re.search(r'```(?:json)?\s*(\{.*)', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                # Remove trailing ``` if present
                json_str = re.sub(r'\s*```\s*$', '', json_str)
                
                # Clean control characters from JSON string
                # Keep only tab, newline, and carriage return (valid JSON whitespace)
                json_str = ''.join(char for char in json_str if ord(char) >= 32 or char in '\t\n\r')
                
                # If JSON is incomplete, try to complete it
                if json_str.count('{') > json_str.count('}'):
                    # Add missing closing braces
                    missing_braces = json_str.count('{') - json_str.count('}')
                    json_str = json_str.rstrip() + '\n' + (']' * json_str.count('[')) + ('}' * missing_braces)
                
                try:
                    return json.loads(json_str, strict=False)
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse extracted JSON from code block: {e}. Trying to fix...")
                    
                    # Extract error position from error message
                    # Error format: "Error message: line X column Y (char Z)"
                    error_msg = str(e)
                    char_match = re.search(r'\(char (\d+)\)', error_msg)
                    
                    if char_match:
                        error_pos = int(char_match.group(1))
                        # Truncate at the error position
                        json_str = json_str[:error_pos]
                        
                        # Handle unterminated string - find last opening quote and close it
                        if "unterminated string" in error_msg.lower() or json_str.count('"') % 2 != 0:
                            # Find the last opening quote
                            last_quote = json_str.rfind('"')
                            if last_quote != -1:
                                # Remove everything after the last opening quote
                                json_str = json_str[:last_quote]
                                # Remove trailing comma if present
                                json_str = json_str.rstrip().rstrip(',').rstrip()
                        
                        # Close any unclosed structures
                        json_str = json_str.rstrip()
                        if json_str.count('{') > json_str.count('}'):
                            missing_braces = json_str.count('{') - json_str.count('}')
                            json_str = json_str + '\n' + ('}' * missing_braces)
                        
                        try:
                            return json.loads(json_str, strict=False)
                        except json.JSONDecodeError:
                            pass
                    
                    # Try to find the last complete fact and truncate there
                    # Look for pattern like: "text",\n or "text"\n]
                    last_complete = re.findall(r'"[^"]*"(?:,|\s*\])', json_str)
                    if last_complete:
                        # Find position of last complete fact
                        last_pos = json_str.rfind(last_complete[-1])
                        if last_pos != -1:
                            # Truncate and close properly
                            json_str = json_str[:last_pos + len(last_complete[-1])]
                            # Ensure it ends properly
                            if not json_str.rstrip().endswith(']'):
                                json_str = json_str.rstrip().rstrip(',') + '\n  ]\n}'
                            elif not json_str.rstrip().endswith('}'):
                                json_str = json_str.rstrip() + '\n}'
                            try:
                                return json.loads(json_str, strict=False)
                            except json.JSONDecodeError:
                                pass
            
            # Second try: Look for JSON object without code blocks
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = text[start_idx:end_idx + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
            
            # Final fallback: Try parsing the entire text
            return json.loads(text.strip())
            
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            text_preview = text[:2000] if 'text' in locals() else 'N/A'
            logger.error(f"Failed to parse Gemini response: {exc}. Text preview: {text_preview}")
            return {}
            return {}

    if isinstance(data, dict):
        return data

    logger.error("LLM response had unexpected format", {"type": type(data).__name__})
    return {}


def is_valid_nfl_fact(fact_text: str) -> bool:
    """Filter out non-story facts using pattern matching.
    
    Layer 3: Post-processing filter to catch author bios, navigation, etc.
    """
    if not fact_text or not isinstance(fact_text, str):
        return False
    
    fact_lower = fact_text.lower()
    
    # Patterns that indicate non-story content
    non_story_patterns = [
        # Author/journalist titles and affiliations
        r'\b(is a|is an)\b.{0,30}\b(reporter|writer|journalist|correspondent|analyst|contributor|editor|columnist)\b.{0,20}\b(for|at|with)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)',
        r'\b(reporter|writer|journalist|correspondent|analyst|contributor|editor|columnist)\b.{0,20}\b(for|at|with)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)',
        r'\b(senior|national|lead|staff)\b.{0,20}\b(reporter|writer|journalist|correspondent|analyst)',
        
        # ESPN style: "Name covers the Team at ESPN"
        r'\b(covers|covering)\b.{0,50}\b(at espn|for espn|at nfl\.com|for nfl\.com)',
        r'\b(covers|covering)\b.{0,20}\b(beat|nfl|sports)',
        r'\bcovers\b.{0,20}\b(entire league|whole league|league-wide)',
        r'\bcovered the\b.{0,30}\b(for more than|since \d{4})',
        
        # Joining/employment statements
        r'\b(joining|joined)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)',
        r'\bassists with\b.{0,30}\b(coverage|draft|reporting)',

        # Contribution/author bio snippets
        r'\bcontributes to\b.{0,50}\b(espn|nfl live|get up|sportscenter|countdown|radio)',
        r'\bis (the )?author of\b',
        r'\bis (the )?co-author of\b',
        r'\bauthor of two published novels\b',
        
        # Professional affiliations
        r'\bmember of the\b.{0,50}\b(board of selectors|hall of fame|association)',
        
        # Contact/social media
        r'\b(follow|contact).{0,20}\b(twitter|facebook|instagram|linkedin|email)',
        
        # Social media and engagement
        r'\b(follow|subscribe|sign up|join|get).{0,30}\b(newsletter|updates|alerts)',
        r'@\w+',  # Social media handles
        r'\b(like|share|comment|retweet)\b',
        
        # Website navigation and metadata
        r'\b(click here|read more|view all|see also|related stories)',
        r'\b(photo credit|image courtesy|getty images)',
        r'\b(copyright|©|all rights reserved)',
        r'\b(terms of service|privacy policy)',
        
        # Advertisement and promotional
        r'\b(advertisement|sponsored|promoted)\b',
        r'\b(download|install) (app|application)',
        
        # Very short or generic statements (likely boilerplate)
        r'^\w{1,3}$',  # Single short words
    ]
    
    for pattern in non_story_patterns:
        if re.search(pattern, fact_lower, re.IGNORECASE):
            logger.debug(f"Filtered non-story fact: {fact_text[:100]}")
            return False
    
    # Must contain some NFL-related signal (very basic check)
    # If it's too short or has no sports context, it's suspicious
    if len(fact_text) < 15:  # Very short facts are often metadata
        return False
    
    return True


def parse_fact_response(payload: Dict[str, Any]) -> List[str]:
    """Validate and normalize facts payload structure only."""

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


def filter_story_facts(facts: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split facts into valid story facts and rejected entries."""

    valid: List[str] = []
    rejected: List[str] = []

    for fact in facts:
        if is_valid_nfl_fact(fact):
            valid.append(fact)
        else:
            rejected.append(fact)

    return valid, rejected


def store_facts(
    client,
    news_url_id: str,
    facts: Sequence[str],
    config: PipelineConfig,
) -> List[str]:
    """Insert extracted facts into news_facts table."""

    if not facts:
        return []

    removed = remove_non_story_facts_from_db(client, news_url_id)
    if removed:
        logger.info(
            "Deleted existing non-story facts before insert",
            {"news_url_id": news_url_id, "removed": removed},
        )

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

    response = client.table("news_facts").insert(records).execute()
    data = getattr(response, "data", []) or []
    return [row.get("id") for row in data if isinstance(row, dict) and row.get("id")]


def remove_non_story_facts_from_db(client, news_url_id: str) -> int:
    """Delete persisted facts (and embeddings) that fail validation."""

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

    client.table("facts_embeddings").delete().in_("news_fact_id", invalid_ids).execute()
    client.table("news_facts").delete().in_("id", invalid_ids).execute()

    logger.info(
        "Removed persisted non-story facts",
        {"news_url_id": news_url_id, "removed": len(invalid_ids)},
    )

    return len(invalid_ids)


def fetch_existing_fact_ids(client, news_url_id: str) -> List[str]:
    """Fetch existing fact IDs for a URL."""

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


def create_fact_embeddings(client, fact_ids: Sequence[str], config: PipelineConfig) -> None:
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
            .order("id")
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
            
            # Debug logging
            logger.debug(
                "Generated embedding",
                {
                    "news_fact_id": fact_id,
                    "embedding_length": len(embedding),
                    "embedding_type": type(embedding).__name__,
                    "first_3_values": embedding[:3] if len(embedding) >= 3 else embedding,
                }
            )
            
            insert_result = client.table("facts_embeddings").insert(
                {
                    "news_fact_id": fact_id,
                    "embedding_vector": embedding,
                    "model_name": config.embedding_model_name,
                }
            ).execute()
            
            # Verify insertion
            logger.debug(
                "Inserted embedding",
                {
                    "news_fact_id": fact_id,
                    "insert_status": "success" if getattr(insert_result, "data", None) else "failed",
                }
            )


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

    # Debug log the response structure
    logger.debug(
        "Embedding API response",
        {
            "response_keys": list(data.keys()) if isinstance(data, dict) else "not_a_dict",
            "has_data_key": "data" in data if isinstance(data, dict) else False,
            "has_embedding_key": "embedding" in data if isinstance(data, dict) else False,
        }
    )

    if isinstance(data, dict):
        if "data" in data:
            try:
                embedding_list = list(data["data"][0]["embedding"])
                logger.debug(
                    "Extracted embedding from OpenAI format",
                    {
                        "embedding_length": len(embedding_list),
                        "first_3_values": embedding_list[:3] if len(embedding_list) >= 3 else embedding_list,
                    }
                )
                return embedding_list
            except (KeyError, IndexError, TypeError):
                logger.error("Unexpected embedding payload structure with 'data'")
                return []
        if "embedding" in data:
            embedding = data.get("embedding")
            if isinstance(embedding, list):
                return [float(value) for value in embedding]

    logger.error("Embedding response had unexpected format", {"payload": data})
    return []


def create_fact_pooled_embedding(client, news_url_id: str, config: PipelineConfig) -> None:
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
    total_rows_returned = 0
    for chunk in chunked(fact_ids, 200):
        response = (
            client.table("facts_embeddings")
            .select("embedding_vector")
            .in_("news_fact_id", chunk)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        total_rows_returned += len(rows)
        
        # Debug logging
        logger.debug(
            "Fetched embeddings for pooling",
            {
                "news_url_id": news_url_id,
                "fact_ids_count": len(chunk),
                "rows_returned": len(rows),
            }
        )
        
        for idx, row in enumerate(rows):
            vector = row.get("embedding_vector")
            
            # Supabase returns VECTOR column as string, need to parse it
            if isinstance(vector, str):
                try:
                    # Remove brackets and split by commas
                    vector_str = vector.strip("[]")
                    vector = [float(x) for x in vector_str.split(",")]
                except (ValueError, AttributeError) as e:
                    logger.warning(
                        f"Failed to parse embedding vector from string: {str(e)[:100]}"
                    )
                    continue
            
            if isinstance(vector, list) and vector:
                embeddings.append([float(value) for value in vector])

    if not embeddings:
        logger.warning(
            "No fact embeddings available for pooling",
            {
                "news_url_id": news_url_id,
                "fact_ids_count": len(fact_ids),
                "rows_fetched": total_rows_returned,
            }
        )
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
            "scope": "article",
            "primary_topic": None,
            "primary_team": None,
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
    news_url_id: str,
    config: PipelineConfig,
) -> str:
    """Generate summary from stored facts using chunking strategy."""

    facts = fetch_fact_texts(client, news_url_id)
    if not facts:
        logger.warning("No facts available for summary", {"news_url_id": news_url_id})
        return ""

    # If facts count is reasonable, process all at once
    if len(facts) <= 30:
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
    
    # For large fact sets, use chunking strategy
    logger.info(f"Using chunking strategy for {len(facts)} facts", {"news_url_id": news_url_id})
    
    # Step 1: Generate partial summaries for chunks
    chunk_size = 30  # Process 30 facts at a time
    partial_summaries = []
    
    for i in range(0, len(facts), chunk_size):
        chunk = facts[i:i + chunk_size]
        chunk_payload = json.dumps({"facts": chunk}, ensure_ascii=False)
        
        for attempt in range(2):
            response_json = call_llm_json(
                prompt=SUMMARY_PROMPT,
                user_content=chunk_payload,
                model=config.summary_llm_model,
                config=config,
            )
            summary = parse_summary_response(response_json)
            if summary:
                partial_summaries.append(summary)
                logger.debug(f"Generated partial summary for chunk {i//chunk_size + 1}/{(len(facts) + chunk_size - 1)//chunk_size}")
                break
            if attempt == 1:
                logger.warning(f"Failed to generate partial summary for chunk {i//chunk_size + 1}")
    
    if not partial_summaries:
        logger.warning("No partial summaries generated", {"news_url_id": news_url_id})
        return ""
    
    # Step 2: If we have multiple partial summaries, combine them
    if len(partial_summaries) == 1:
        return partial_summaries[0]
    
    # Combine partial summaries into final summary
    logger.info(f"Combining {len(partial_summaries)} partial summaries", {"news_url_id": news_url_id})
    combine_prompt = """You are an expert at synthesizing information. You will receive multiple partial summaries of NFL news content.

Your task: Combine these partial summaries into one comprehensive, coherent summary that:
1. Preserves all key information from each partial summary
2. Eliminates redundancy and repetition
3. Maintains a logical flow
4. Stays focused on NFL-related content

Return your response as JSON: {"summary": "your combined summary here"}"""
    
    combine_payload = json.dumps({"partial_summaries": partial_summaries}, ensure_ascii=False)
    
    for attempt in range(2):
        response_json = call_llm_json(
            prompt=combine_prompt,
            user_content=combine_payload,
            model=config.summary_llm_model,
            config=config,
        )
        final_summary = parse_summary_response(response_json)
        if final_summary:
            logger.info("Successfully combined partial summaries", {"news_url_id": news_url_id})
            return final_summary
        logger.warning("Failed to combine partial summaries", {"attempt": attempt + 1})
    
    # Fallback: concatenate partial summaries
    logger.warning("Using fallback concatenation for partial summaries", {"news_url_id": news_url_id})
    return " ".join(partial_summaries)


def fetch_fact_texts(client, news_url_id: str) -> List[str]:
    """Fetch fact text for a URL with pagination."""

    page_size = 1000
    offset = 0
    facts: List[str] = []

    while True:
        response = (
            client.table("news_facts")
            .select("fact_text")
            .eq("news_url_id", news_url_id)
            .order("id")
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
    news_url_id: str,
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


def create_summary_embedding(client, news_url_id: str, config: PipelineConfig) -> None:
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

    try:
        client.table("story_embeddings").insert(
            {
                "news_url_id": news_url_id,
                "embedding_vector": embedding,
                "model_name": config.embedding_model_name,
                "embedding_type": "summary",
                "scope": "article",
                "primary_topic": None,
                "primary_team": None,
            }
        ).execute()
    except Exception as e:
        # Handle duplicate key gracefully (can happen if check race condition)
        if "duplicate key" in str(e).lower() or "23505" in str(e):
            logger.info("Summary embedding already exists (duplicate)", {"news_url_id": news_url_id})
            return
        raise


def handle_easy_article_summary(client, news_url_id: str, config: PipelineConfig) -> None:
    """Generate single summary and embedding for easy articles."""

    summary_text = create_summary_from_facts(client, news_url_id, config)
    if not summary_text:
        logger.warning("Easy article summary was empty", {"news_url_id": news_url_id})
        return

    clear_topic_artifacts(client, news_url_id)

    client.table("context_summaries").delete().eq("news_url_id", news_url_id).eq(
        "prompt_version", SUMMARY_PROMPT_VERSION
    ).execute()
    delete_story_embeddings(client, news_url_id, embedding_type="summary")

    stored_summary = store_summary(client, news_url_id, summary_text, config)
    if stored_summary:
        logger.info("Stored easy-article summary", {"news_url_id": news_url_id})

    create_summary_embedding(client, news_url_id, config)


def handle_hard_article_summary(client, news_url_id: str, config: PipelineConfig) -> None:
    """Create topic/team summaries and embeddings for hard articles."""

    client.table("context_summaries").delete().eq("news_url_id", news_url_id).eq(
        "prompt_version", SUMMARY_PROMPT_VERSION
    ).execute()
    delete_story_embeddings(client, news_url_id, embedding_type="summary")

    clear_topic_artifacts(client, news_url_id)

    grouped_facts = group_facts_by_topic_and_scope(client, news_url_id)
    if not grouped_facts:
        logger.warning("No fact groups available for hard article", {"news_url_id": news_url_id})
        return

    for group in grouped_facts:
        topic = group["topic"]
        scope = group["scope"]
        facts = group["facts"]
        summary_text = create_topic_summary_from_facts(facts, topic, scope, config)
        if not summary_text:
            continue
        store_topic_summary(client, news_url_id, topic, scope, summary_text, config)
        create_topic_summary_embedding(client, news_url_id, topic, scope, summary_text, config)
        logger.info(
            "Stored topic summary",
            {
                "news_url_id": news_url_id,
                "topic": topic,
                "scope": scope,
                "facts": len(facts),
            },
        )


def clear_topic_artifacts(client, news_url_id: str) -> None:
    """Remove topic-level summaries and embeddings for a URL."""

    client.table("topic_summaries").delete().eq("news_url_id", news_url_id).execute()
    delete_story_embeddings(client, news_url_id, scope="topic")


def delete_story_embeddings(
    client,
    news_url_id: str,
    *,
    scope: Optional[str] = None,
    embedding_type: Optional[str] = None,
) -> None:
    """Delete story embeddings filtered by scope and/or type."""

    query = client.table("story_embeddings").delete().eq("news_url_id", news_url_id)
    if scope is not None:
        query = query.eq("scope", scope)
    if embedding_type is not None:
        query = query.eq("embedding_type", embedding_type)
    query.execute()


def group_facts_by_topic_and_scope(client, news_url_id: str) -> List[Dict[str, Any]]:
    """Return topic groups with associated scope metadata."""

    metadata = fetch_fact_metadata(client, news_url_id)
    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for record in metadata:
        topic = record.get("canonical_topic") or "general"
        scope = record.get("primary_scope") or {}
        scope_type = scope.get("type") or "unscoped"
        scope_key = scope.get("id") or scope.get("label") or "unscoped"
        fact_text = record.get("fact_text")
        if not fact_text:
            continue

        key = (topic, scope_type, scope_key)
        group = groups.setdefault(
            key,
            {
                "topic": topic,
                "scope": scope,
                "facts": [],
            },
        )
        group["facts"].append(fact_text)

    return [group for group in groups.values() if group["facts"]]


def fetch_fact_metadata(client, news_url_id: str) -> List[Dict[str, Any]]:
    """Collect facts with their primary topics and teams."""

    facts_response = (
        client.table("news_facts")
        .select("id,fact_text")
        .eq("news_url_id", news_url_id)
        .execute()
    )
    fact_rows = getattr(facts_response, "data", []) or []
    facts: Dict[str, Dict[str, Any]] = {}
    for row in fact_rows:
        fact_id = row.get("id")
        fact_text = row.get("fact_text")
        if fact_id and isinstance(fact_text, str):
            facts[fact_id] = {"fact_text": fact_text.strip()}

    if not facts:
        return []

    fact_ids = list(facts.keys())

    topics_response = (
        client.table("news_fact_topics")
        .select("news_fact_id,topic,canonical_topic,is_primary,rank")
        .in_("news_fact_id", fact_ids)
        .execute()
    )
    topics_by_fact: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in getattr(topics_response, "data", []) or []:
        fact_id = row.get("news_fact_id")
        if fact_id in facts:
            topics_by_fact[fact_id].append(row)

    entities_response = (
        client.table("news_fact_entities")
        .select(
            "news_fact_id,entity_type,entity_id,team_abbr,is_primary,rank,matched_name,mention_text"
        )
        .in_("news_fact_id", fact_ids)
        .execute()
    )
    entities_by_fact: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in getattr(entities_response, "data", []) or []:
        fact_id = row.get("news_fact_id")
        if fact_id in facts:
            entities_by_fact[fact_id].append(row)

    metadata: List[Dict[str, Any]] = []
    for fact_id, data in facts.items():
        topics = topics_by_fact.get(fact_id, [])
        selected_topic = select_primary_topic(topics)
        entities = entities_by_fact.get(fact_id, [])
        primary_scope = select_primary_scope(entities)
        metadata.append(
            {
                "fact_id": fact_id,
                "fact_text": data.get("fact_text"),
                "canonical_topic": selected_topic.get("canonical_topic") if selected_topic else None,
                "primary_topic": selected_topic.get("topic") if selected_topic else None,
                "primary_team": primary_scope.get("team") if primary_scope else None,
                "primary_scope": primary_scope,
            }
        )

    return metadata


def select_primary_topic(topics: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Choose the primary topic record for a fact."""

    if not topics:
        return None

    sorted_topics = sorted(
        topics,
        key=lambda row: (
            0 if row.get("is_primary") else 1,
            row.get("rank") or 99,
        ),
    )
    return sorted_topics[0]


def select_primary_scope(entities: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Determine the primary contextual scope (team/player/game) for a fact."""

    if not entities:
        return {}

    def sort_key(row: Dict[str, Any]) -> Tuple[int, int]:
        return (0 if row.get("is_primary") else 1, row.get("rank") or 99)

    team_candidates = [row for row in entities if row.get("entity_type") == "team"]
    if team_candidates:
        best = sorted(team_candidates, key=sort_key)[0]
        identifier = best.get("entity_id") or best.get("team_abbr")
        label = best.get("matched_name") or identifier or best.get("team_abbr")
        return {
            "type": "team",
            "id": identifier,
            "label": label,
            "team": identifier or best.get("team_abbr"),
        }

    player_candidates = [row for row in entities if row.get("entity_type") == "player"]
    if player_candidates:
        best = sorted(player_candidates, key=sort_key)[0]
        identifier = best.get("entity_id") or best.get("mention_text")
        label = best.get("matched_name") or best.get("mention_text") or identifier
        return {
            "type": "player",
            "id": identifier,
            "label": label,
            "team": best.get("team_abbr"),
        }

    game_candidates = [row for row in entities if row.get("entity_type") == "game"]
    if game_candidates:
        best = sorted(game_candidates, key=sort_key)[0]
        identifier = best.get("entity_id") or best.get("mention_text")
        label = best.get("matched_name") or best.get("mention_text") or identifier
        return {
            "type": "game",
            "id": identifier,
            "label": label,
        }

    return {}


def normalize_scope(scope: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Normalize scope metadata for storage and prompt construction."""

    if not scope:
        return {"type": None, "id": None, "label": "League-wide", "team": None}

    normalized = {
        "type": scope.get("type"),
        "id": scope.get("id"),
        "label": scope.get("label"),
        "team": scope.get("team"),
    }

    if not normalized["label"]:
        if normalized["type"] == "team":
            normalized["label"] = normalized.get("id") or normalized.get("team") or "Team context"
        elif normalized["type"] == "player":
            normalized["label"] = "Player context"
        elif normalized["type"] == "game":
            normalized["label"] = "Game context"
    if normalized["label"] is None:
        normalized["label"] = "League-wide"

    return normalized


def build_scope_label(scope: Dict[str, Optional[str]]) -> str:
    """Create human-readable label for a scope."""

    label = scope.get("label") or "League-wide"
    scope_type = scope.get("type")
    if not scope_type or scope_type == "team":
        return label
    return f"{label} ({scope_type})"


def create_topic_summary_from_facts(
    facts: List[str],
    topic: str,
    scope: Optional[Dict[str, Any]],
    config: PipelineConfig,
) -> str:
    """Run topic-specific summarization for fact subset."""

    if not facts:
        return ""

    scope_info = normalize_scope(scope)
    context_label = build_scope_label(scope_info)
    prompt = TOPIC_SUMMARY_TEMPLATE.format(topic=topic, context=context_label)
    payload = json.dumps({"facts": facts}, ensure_ascii=False)

    for attempt in range(2):
        response_json = call_llm_json(
            prompt=prompt,
            user_content=payload,
            model=config.summary_llm_model,
            config=config,
        )
        summary = parse_summary_response(response_json)
        if summary:
            return summary
        logger.warning(
            "Topic summary generation failed",
            {"topic": topic, "scope": scope_info, "attempt": attempt + 1},
        )

    return ""


def store_topic_summary(
    client,
    news_url_id: str,
    topic: str,
    scope: Optional[Dict[str, Any]],
    summary_text: str,
    config: PipelineConfig,
) -> None:
    """Insert topic-level summary record."""

    scope_info = normalize_scope(scope)
    primary_team = scope_info.get("team") if scope_info.get("type") != "team" else scope_info.get("id")
    client.table("topic_summaries").insert(
        {
            "news_url_id": news_url_id,
            "primary_topic": topic,
            "primary_team": primary_team,
            "primary_scope_type": scope_info.get("type"),
            "primary_scope_id": scope_info.get("id"),
            "primary_scope_label": scope_info.get("label"),
            "summary_text": summary_text,
            "llm_model": config.summary_llm_model,
            "prompt_version": TOPIC_SUMMARY_PROMPT_VERSION,
        }
    ).execute()


def create_topic_summary_embedding(
    client,
    news_url_id: str,
    topic: str,
    scope: Optional[Dict[str, Any]],
    summary_text: str,
    config: PipelineConfig,
) -> None:
    """Create embedding for topic-level summary."""

    embedding = generate_embedding(summary_text, config)
    if not embedding:
        logger.warning(
            "Failed to generate topic summary embedding",
            {"news_url_id": news_url_id, "topic": topic, "scope": scope},
        )
        return

    scope_info = normalize_scope(scope)
    primary_team = scope_info.get("team") if scope_info.get("type") != "team" else scope_info.get("id")
    client.table("story_embeddings").insert(
        {
            "news_url_id": news_url_id,
            "embedding_vector": embedding,
            "model_name": config.embedding_model_name,
            "embedding_type": "summary",
            "scope": "topic",
            "primary_topic": topic,
            "primary_team": primary_team,
            "primary_scope_type": scope_info.get("type"),
            "primary_scope_id": scope_info.get("id"),
            "primary_scope_label": scope_info.get("label"),
        }
    ).execute()


def fact_stage_completed(client, news_url_id: str) -> bool:
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


def summary_stage_completed(client, news_url_id: str) -> bool:
    """Check whether summary and summary embedding exist for a URL."""

    difficulty = get_article_difficulty(client, news_url_id).get("article_difficulty")

    if difficulty == "hard":
        summary_exists = (
            client.table("topic_summaries")
            .select("id")
            .eq("news_url_id", news_url_id)
            .limit(1)
            .execute()
        )
        if not getattr(summary_exists, "data", []):
            return False

        embedding_exists = (
            client.table("story_embeddings")
            .select("id")
            .eq("news_url_id", news_url_id)
            .eq("scope", "topic")
            .limit(1)
            .execute()
        )
        return bool(getattr(embedding_exists, "data", []))

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
        .eq("scope", "article")
        .limit(1)
        .execute()
    )
    return bool(getattr(embedding_exists, "data", []))


def mark_news_url_timestamp(client, news_url_id: str, column: str) -> None:
    """Mark a timestamp column on news_urls with current UTC time."""

    now_iso = datetime.now(timezone.utc).isoformat()
    client.table("news_urls").update({column: now_iso}).eq("id", news_url_id).execute()


def chunked(iterable: Sequence[str], size: int) -> Iterable[List[str]]:
    """Yield chunks from a sequence."""

    for index in range(0, len(iterable), size):
        yield list(iterable[index : index + size])


if __name__ == "__main__":
    main()
