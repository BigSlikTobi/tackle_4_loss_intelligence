"""Synchronous fact extraction CLI for single articles.

This tool extracts facts from one or more articles using the OpenAI API directly
(no Batch API). Use this for:
- Testing and debugging
- Processing 1-10 articles immediately
- Manual corrections

For bulk processing (100+ articles), use facts_batch_cli.py with Batch API for ~50% cost savings.

USAGE:
  # Extract facts for the 10 newest articles needing extraction
  python extract_facts_cli.py --newest 10
  
  # Extract facts for a single URL by ID
  python extract_facts_cli.py --url-id abc123
  
  # Extract facts by URL (will look up ID from database)
  python extract_facts_cli.py --url "https://espn.com/nfl/story..."
  
  # Extract from already-fetched content (skip content fetch)
  python extract_facts_cli.py --url-id abc123 --content-file article.txt
  
  # Dry run (don't save to database)
  python extract_facts_cli.py --newest 5 --dry-run --verbose
  
  # Skip embeddings (faster)
  python extract_facts_cli.py --newest 10 --no-embeddings
  
  # Force re-extraction (delete existing facts first)
  python extract_facts_cli.py --url-id abc123 --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Bootstrap path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.url_content_extraction.core.extractors.extractor_factory import get_extractor
from src.functions.url_content_extraction.core.facts import (
    FACT_PROMPT,
    FACT_PROMPT_VERSION,
    parse_fact_response,
    filter_story_facts,
    store_facts,
    fetch_existing_fact_ids,
    remove_non_story_facts_from_db,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5-nano"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# Patterns that indicate access is blocked
ACCESS_DENIED_PATTERNS = [
    "access denied",
    "you don't have permission",
    "403 forbidden",
    "blocked",
    "not available in your region",
    "geo-restricted",
    "captcha",
    "please verify you are a human",
    "rate limit",
    "too many requests",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract facts from a single article using OpenAI API"
    )
    
    # Input options (one required)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--url-id",
        help="News URL ID from database",
    )
    input_group.add_argument(
        "--url",
        help="Article URL (will look up ID from database)",
    )
    input_group.add_argument(
        "--newest",
        type=int,
        metavar="N",
        help="Process N newest articles that need fact extraction",
    )
    input_group.add_argument(
        "--high-fact-count",
        type=int,
        metavar="THRESHOLD",
        help="Re-extract all articles with facts_count > THRESHOLD (e.g., --high-fact-count 100)",
    )
    
    # Processing options
    parser.add_argument(
        "--content-file",
        type=Path,
        help="Read content from file instead of fetching (for testing)",
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
        help="Skip creating embeddings (faster)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-extraction (delete existing facts first)",
    )
    parser.add_argument(
        "--force-playwright",
        action="store_true",
        help="Force using Playwright browser (for sites that block HTTP requests)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract facts but don't save to database",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write extracted facts to JSON file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show extracted facts in console",
    )
    
    return parser.parse_args()


def is_access_denied_content(content: str, title: str = "") -> bool:
    """Check if the extracted content indicates access was denied."""
    check_text = f"{title} {content}".lower()
    
    for pattern in ACCESS_DENIED_PATTERNS:
        if pattern in check_text:
            return True
    
    # Also check for very short content with error-like titles
    if len(content) < 200 and any(word in check_text for word in ["error", "denied", "blocked", "forbidden"]):
        return True
    
    return False


def mark_url_blocked(client, url_id: str, reason: str) -> None:
    """Mark a URL as blocked/inaccessible in the database.
    
    Also clears/resets extraction-related columns to indicate no valid data.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    client.table("news_urls").update({
        "extraction_error": reason,
        "extraction_error_at": now_iso,
        # Clear extraction timestamps and counts since data is invalid
        "facts_extracted_at": None,
        "facts_count": 0,
        "article_difficulty": None,
        "summary_created_at": None,
        "knowledge_extracted_at": None,
        "knowledge_error_count": 0,
    }).eq("id", url_id).execute()
    logger.warning(f"Marked URL {url_id} as blocked: {reason}")


def fetch_article_content(
    url: str, 
    timeout: int = 45, 
    force_playwright: bool = False,
    debug_html: Optional[Path] = None,
) -> tuple[str, Optional[str]]:
    """Fetch article content using the extractor.
    
    Args:
        url: Article URL
        timeout: Request timeout in seconds
        force_playwright: Use Playwright browser for sites that block HTTP requests
        debug_html: If set, save raw HTML to this path for debugging
        
    Returns:
        Tuple of (content, error_reason). error_reason is None if successful,
        or a string describing the blocking reason.
    """
    
    logger.info(f"Fetching content from: {url}")
    
    extractor = get_extractor(url, force_playwright=force_playwright)
    result = extractor.extract(url, timeout=timeout)
    
    if result.error:
        # If lightweight extractor got 403, retry with Playwright
        if "403" in str(result.error) and not force_playwright:
            logger.info("Got 403, retrying with Playwright browser...")
            return fetch_article_content(url, timeout=timeout, force_playwright=True, debug_html=debug_html)
        
        logger.warning(f"Extraction error: {result.error}")
        return "", f"extraction_error: {result.error}"
    
    if result.paragraphs:
        content = "\n\n".join(result.paragraphs)
        logger.info(f"Extracted {len(result.paragraphs)} paragraphs ({len(content)} chars)")
        
        # Check for access denied content
        title = result.title or ""
        if is_access_denied_content(content, title):
            logger.warning(f"Detected access denied page. Title: {title}")
            return "", f"access_denied: {title[:100]}"
        
        # If content is suspiciously short, might still be blocked
        if len(content) < 300:
            logger.warning(f"Content seems too short ({len(content)} chars). Site may be blocking.")
            if result.title:
                logger.info(f"Page title: {result.title}")
            # Check if it looks like an error page
            if is_access_denied_content(content, title):
                return "", f"access_denied_short_content: {len(content)} chars"
        
        return content.strip(), None
    
    logger.warning("Extractor returned no paragraphs")
    return "", "no_content_extracted"


def extract_facts_from_content(
    content: str,
    model: str,
    api_key: str,
) -> List[str]:
    """Extract facts from article content using OpenAI API.
    
    Args:
        content: Article text
        model: OpenAI model name
        api_key: OpenAI API key
        
    Returns:
        List of extracted fact strings
    """
    import openai
    
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    formatted_prompt = FACT_PROMPT.format(current_date=current_date)
    
    # GPT-5-nano is a reasoning model - special parameters
    is_reasoning_model = (
        "nano" in model or 
        model.startswith("o1") or 
        model.startswith("o3")
    )
    
    logger.info(f"Calling {model} for fact extraction...")
    
    openai.api_key = api_key
    
    if is_reasoning_model:
        # Reasoning models: no temperature, use max_completion_tokens, reasoning_effort
        response = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": f"{formatted_prompt}\n\n{content}"}
            ],
            max_completion_tokens=16000,
            reasoning_effort="low",
        )
    else:
        # Standard models
        response = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": formatted_prompt},
                {"role": "user", "content": content}
            ],
            temperature=0,
            max_tokens=16000,
            response_format={"type": "json_object"},
        )
    
    # Parse response
    response_text = response.choices[0].message.content
    
    try:
        data = json.loads(response_text)
        facts = parse_fact_response(data)
        logger.info(f"Extracted {len(facts)} raw facts")
        return facts
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.debug(f"Response text: {response_text[:500]}")
        return []


def create_fact_embeddings_sync(
    client,
    fact_ids: List[str],
    api_key: str,
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> int:
    """Create embeddings for facts synchronously.
    
    Args:
        client: Supabase client
        fact_ids: List of fact IDs
        api_key: OpenAI API key
        model: Embedding model
        
    Returns:
        Number of embeddings created
    """
    import openai
    
    if not fact_ids:
        return 0
    
    # Fetch fact texts
    response = (
        client.table("news_facts")
        .select("id,fact_text")
        .in_("id", fact_ids)
        .execute()
    )
    rows = getattr(response, "data", []) or []
    
    if not rows:
        return 0
    
    texts = [row.get("fact_text", "") for row in rows]
    ids = [row.get("id") for row in rows]
    
    logger.info(f"Creating embeddings for {len(texts)} facts...")
    
    openai.api_key = api_key
    embed_response = openai.embeddings.create(
        model=model,
        input=texts,
    )
    
    records = []
    for idx, embedding_data in enumerate(embed_response.data):
        records.append({
            "news_fact_id": ids[idx],
            "embedding_vector": embedding_data.embedding,
            "model_name": model,
        })
    
    if records:
        client.table("facts_embeddings").insert(records).execute()
        logger.info(f"Created {len(records)} embeddings")
        return len(records)
    
    return 0


def create_pooled_embedding(
    client,
    news_url_id: str,
    api_key: str,
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> bool:
    """Create pooled (averaged) embedding for all facts of an article.
    
    Args:
        client: Supabase client
        news_url_id: News URL ID
        api_key: OpenAI API key
        model: Embedding model
        
    Returns:
        True if created successfully
    """
    # Check if already exists
    existing = (
        client.table("story_embeddings")
        .select("id")
        .eq("news_url_id", news_url_id)
        .eq("embedding_type", "fact_pooled")
        .limit(1)
        .execute()
    )
    if getattr(existing, "data", []):
        logger.info("Pooled embedding already exists")
        return True
    
    # Fetch all fact embeddings
    fact_ids = fetch_existing_fact_ids(client, news_url_id)
    if not fact_ids:
        logger.warning("No facts found for pooling")
        return False
    
    embeddings = []
    for chunk_start in range(0, len(fact_ids), 200):
        chunk = fact_ids[chunk_start:chunk_start + 200]
        response = (
            client.table("facts_embeddings")
            .select("embedding_vector")
            .in_("news_fact_id", chunk)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        
        for row in rows:
            vector = row.get("embedding_vector")
            if isinstance(vector, str):
                # Parse string representation
                vector = [float(x) for x in vector.strip("[]").split(",")]
            if isinstance(vector, list) and vector:
                embeddings.append(vector)
    
    if not embeddings:
        logger.warning("No fact embeddings found for pooling")
        return False
    
    # Average the embeddings
    dimension = len(embeddings[0])
    pooled = [sum(e[i] for e in embeddings) / len(embeddings) for i in range(dimension)]
    
    # Store pooled embedding
    client.table("story_embeddings").insert({
        "news_url_id": news_url_id,
        "embedding_vector": pooled,
        "model_name": model,
        "embedding_type": "fact_pooled",
        "scope": "article",
    }).execute()
    
    logger.info(f"Created pooled embedding from {len(embeddings)} fact embeddings")
    return True


def calculate_article_difficulty(content: str, facts_count: int) -> str:
    """Calculate article difficulty based on content complexity.
    
    Uses a simple heuristic based on:
    - Average sentence length
    - Content length per fact
    - Total content length
    
    Returns: 'easy', 'medium', or 'hard'
    """
    if not content or facts_count == 0:
        return "medium"
    
    # Count sentences (rough approximation)
    sentences = len([s for s in content.replace("!", ".").replace("?", ".").split(".") if s.strip()])
    if sentences == 0:
        sentences = 1
    
    avg_sentence_length = len(content) / sentences
    content_per_fact = len(content) / facts_count
    
    # Scoring
    score = 0
    
    # Long sentences = harder
    if avg_sentence_length > 150:
        score += 2
    elif avg_sentence_length > 100:
        score += 1
    
    # More content per fact = more complex article
    if content_per_fact > 500:
        score += 2
    elif content_per_fact > 300:
        score += 1
    
    # Very long articles tend to be more complex
    if len(content) > 5000:
        score += 1
    
    if score >= 3:
        return "hard"
    elif score >= 1:
        return "medium"
    else:
        return "easy"


def mark_facts_extracted(client, news_url_id: str, facts_count: int, article_difficulty: str) -> None:
    """Mark facts_extracted_at timestamp and update stats on news_urls."""
    now_iso = datetime.now(timezone.utc).isoformat()
    client.table("news_urls").update({
        "facts_extracted_at": now_iso,
        "facts_count": facts_count,
        "article_difficulty": article_difficulty,
    }).eq("id", news_url_id).execute()
    logger.info(f"Updated {news_url_id}: facts_count={facts_count}, difficulty={article_difficulty}")


def process_single_article(
    client,
    url_id: str,
    article_url: str,
    args,
    api_key: str,
) -> bool:
    """Process a single article for fact extraction.
    
    Returns:
        True if successful
    """
    logger.info(f"Processing article: {url_id}")
    logger.info(f"URL: {article_url}")
    
    # Check for existing facts
    existing_facts = fetch_existing_fact_ids(client, url_id)
    if existing_facts and not args.force:
        logger.info(f"Article already has {len(existing_facts)} facts. Use --force to re-extract.")
        return True
    
    if existing_facts and args.force:
        logger.info(f"Deleting {len(existing_facts)} existing facts and all downstream data...")
        if not args.dry_run:
            # Delete in chunks to avoid URL length limits
            chunk_size = 100
            for i in range(0, len(existing_facts), chunk_size):
                chunk = existing_facts[i:i + chunk_size]
                # Delete all downstream data first (order matters for foreign keys)
                # 1. Delete fact embeddings
                client.table("facts_embeddings").delete().in_("news_fact_id", chunk).execute()
                # 2. Delete entity links
                client.table("news_fact_entities").delete().in_("news_fact_id", chunk).execute()
                # 3. Delete topic links
                client.table("news_fact_topics").delete().in_("news_fact_id", chunk).execute()
                # 4. Finally delete the facts themselves
                client.table("news_facts").delete().in_("id", chunk).execute()
            
            # Delete story-level data that depends on facts
            # 5. Delete pooled embeddings (all types for this article)
            client.table("story_embeddings").delete().eq("news_url_id", url_id).execute()
            
            # 6. Reset timestamps and counts so downstream processes know to re-run
            client.table("news_urls").update({
                "facts_extracted_at": None,
                "facts_count": None,
                "article_difficulty": None,
                "knowledge_extracted_at": None,  # Knowledge depends on facts
                "knowledge_error_count": 0,      # Reset error count
                "summary_created_at": None,      # Summary depends on facts
            }).eq("id", url_id).execute()
            
            logger.info(f"Deleted {len(existing_facts)} facts + embeddings, entities, topics in {(len(existing_facts) + chunk_size - 1) // chunk_size} batches")
    
    # Get content
    if args.content_file:
        logger.info(f"Reading content from: {args.content_file}")
        content = args.content_file.read_text(encoding="utf-8")
        block_reason = None
    else:
        content, block_reason = fetch_article_content(
            article_url, 
            force_playwright=getattr(args, 'force_playwright', False)
        )
    
    if not content:
        if block_reason and not args.dry_run:
            # Mark URL as blocked so we skip it in future
            mark_url_blocked(client, url_id, block_reason)
            logger.error(f"No content extracted - URL marked as blocked: {block_reason}")
        else:
            logger.error("No content extracted")
        return False
    
    logger.info(f"Content length: {len(content)} characters")
    
    # Extract facts
    facts = extract_facts_from_content(content, args.model, api_key)
    
    if not facts:
        logger.error("No facts extracted")
        return False
    
    # Filter facts
    filtered_facts, rejected_facts = filter_story_facts(facts)
    
    logger.info(f"Extracted {len(facts)} facts, filtered to {len(filtered_facts)} ({len(rejected_facts)} rejected)")
    
    if rejected_facts and args.verbose:
        logger.info("Rejected facts:")
        for fact in rejected_facts[:5]:
            logger.info(f"  - {fact[:100]}...")
    
    if not filtered_facts:
        logger.warning("All facts were filtered out!")
        return False
    
    # Output facts
    if args.verbose:
        print("\n" + "=" * 60)
        print(f"EXTRACTED FACTS ({len(filtered_facts)}):")
        print("=" * 60)
        for i, fact in enumerate(filtered_facts, 1):
            print(f"{i:3}. {fact}")
        print("=" * 60 + "\n")
    
    if args.output:
        output_data = {
            "news_url_id": url_id,
            "url": article_url,
            "model": args.model,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "facts_count": len(filtered_facts),
            "rejected_count": len(rejected_facts),
            "facts": filtered_facts,
            "rejected_facts": rejected_facts,
        }
        args.output.write_text(json.dumps(output_data, indent=2, ensure_ascii=False))
        logger.info(f"Wrote facts to: {args.output}")
    
    if args.dry_run:
        logger.info("Dry run - not saving to database")
        print(f"\nDRY RUN: Would save {len(filtered_facts)} facts for {url_id}")
        return True
    
    # Store facts
    fact_ids = store_facts(client, url_id, filtered_facts, args.model)
    
    if not fact_ids:
        # Facts may already exist, fetch them
        fact_ids = fetch_existing_fact_ids(client, url_id)
    
    logger.info(f"Stored {len(fact_ids)} facts")
    
    # Create embeddings
    if not args.no_embeddings and fact_ids:
        try:
            create_fact_embeddings_sync(client, fact_ids, api_key, args.embedding_model)
            create_pooled_embedding(client, url_id, api_key, args.embedding_model)
        except Exception as e:
            logger.error(f"Failed to create embeddings: {e}")
    
    # Calculate difficulty and mark extraction complete
    difficulty = calculate_article_difficulty(content, len(filtered_facts))
    mark_facts_extracted(client, url_id, len(filtered_facts), difficulty)
    
    print(f"✓ Successfully extracted {len(filtered_facts)} facts for {url_id} (difficulty: {difficulty})")
    return True


def main() -> None:
    args = parse_args()
    setup_logging()
    load_env()
    
    # Get API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not found in environment")
        sys.exit(1)
    
    client = get_supabase_client()
    
    # Handle --high-fact-count flag (redirect to batch mode)
    if args.high_fact_count:
        print("\n" + "=" * 60)
        print("USE BATCH MODE FOR HIGH FACT COUNT RE-EXTRACTION")
        print("=" * 60)
        print(f"\nFor processing articles with facts_count > {args.high_fact_count},")
        print("use the batch CLI for 50% cost savings:\n")
        print(f"  # Step 1: Create batch job")
        print(f"  python facts_batch_cli.py --task create --high-fact-count {args.high_fact_count}")
        print(f"\n  # Step 2: Check status (batch completes within 24h)")
        print(f"  python facts_batch_cli.py --task status --batch-id <BATCH_ID>")
        print(f"\n  # Step 3: Process results (deletes old facts, inserts new)")
        print(f"  python facts_batch_cli.py --task process --batch-id <BATCH_ID> --force-delete")
        print("=" * 60)
        sys.exit(0)
    
    # Handle --newest flag
    if args.newest:
        logger.info(f"Fetching {args.newest} newest articles needing fact extraction...")
        
        # Get articles with content but no facts, excluding blocked URLs
        response = (
            client.table("news_urls")
            .select("id,url")
            .not_.is_("content_extracted_at", "null")
            .is_("facts_extracted_at", "null")
            .is_("extraction_error", "null")  # Skip blocked URLs
            .order("created_at", desc=True)
            .limit(args.newest)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        
        if not rows:
            logger.info("No articles found needing fact extraction")
            sys.exit(0)
        
        logger.info(f"Found {len(rows)} articles to process")
        
        success_count = 0
        for row in rows:
            url_id = row["id"]
            article_url = row["url"]
            try:
                if process_single_article(client, url_id, article_url, args, api_key):
                    success_count += 1
            except Exception as e:
                logger.error(f"Failed to process {url_id}: {e}")
        
        print(f"\n✓ Processed {success_count}/{len(rows)} articles successfully")
        sys.exit(0)
    
    # Resolve URL ID for single article
    if args.url:
        # Look up ID from URL
        response = (
            client.table("news_urls")
            .select("id,url")
            .eq("url", args.url)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        if not rows:
            logger.error(f"URL not found in database: {args.url}")
            sys.exit(1)
        url_id = rows[0]["id"]
        article_url = rows[0]["url"]
    else:
        url_id = args.url_id
        # Fetch URL for content extraction
        response = (
            client.table("news_urls")
            .select("url")
            .eq("id", url_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        if not rows:
            logger.error(f"URL ID not found: {url_id}")
            sys.exit(1)
        article_url = rows[0]["url"]
    
    # Process single article
    success = process_single_article(client, url_id, article_url, args, api_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
