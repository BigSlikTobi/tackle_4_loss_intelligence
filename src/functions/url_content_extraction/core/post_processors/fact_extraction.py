"""Streamlined fact extraction post-processor for URL content extraction integration.

This module provides lightweight fact extraction for real-time processing (1-10 articles).
For bulk processing (1000+ articles), use backlog_processor.py instead.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from src.shared.db import get_supabase_client

logger = logging.getLogger(__name__)

# Constants from content_pipeline_cli.py
FACT_PROMPT_VERSION = "facts-v1"
DEFAULT_FACT_MODEL = "gemma-3n-e4b-it"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

FACT_PROMPT = """ASK: Extract discrete facts from the article. Closed world. No inferences.
Current Date: {current_date}

RULES
- Use only the information explicitly stated in the text.
- Do not infer motivations, causes, consequences, or relationships.
- Do not add external knowledge.
- Maintain the original order of the article.
- Keep each statement short, specific, and self-contained.
- Exactly ONE factual claim per statement. Avoid using "and" to combine different events.
- Prefer repeating full player names, team names, and entities instead of pronouns when it improves clarity.
- Preserve all numbers, dates, scores, contract amounts, and durations exactly as written.
- Ignore navigation menus, cookie banners, share buttons, and other website boilerplate. Only use the main article content.
- Include all player names, team names, dates, trades, quotes, contract references, injuries, and statements about future plans that are explicitly stated.
- If something is not in the article, do NOT mention it.

CRITICAL QUALITY RULES:
1. TIMELINESS: Ensure all temporal statements are anchored to the Current Date ({current_date}).
2. NO META-INFO: EXCLUDE facts about the author, source, publication time, or media outlet.
3. NO GENERALITIES: EXCLUDE general statements, opinions, platitudes, or vague commentary.
4. SPECIFIC SUBJECTS: ALWAYS specify the subject. Replace "The organization", "The team", or pronouns with the specific team or player name.
5. LEANNESS: Optimize for leanness. Extract only significant, concrete facts. Avoid verbose filler.

OUTPUT FORMAT (JSON only):
{{
  "facts": [
    "fact 1",
    "fact 2",
    "fact 3"
  ]
}}

Output ONLY valid JSON. No extra text, no comments, no explanations.
"""


def extract_and_store_facts(
    article_content: str,
    news_url_id: str,
    supabase_config: Dict[str, str],
    llm_config: Dict[str, str],
    embedding_config: Dict[str, str],
) -> Dict[str, Any]:
    """Extract facts from article content and store to database.
    
    This is a streamlined version for real-time processing with the url_extraction
    Cloud Function. It processes a single article without checkpoint or retry logic.
    
    Args:
        article_content: Extracted article text
        news_url_id: News URL ID from database
        supabase_config: Dict with 'url' and 'key'
        llm_config: Dict with 'api_url', 'api_key', 'model'
        embedding_config: Dict with 'api_url', 'api_key', 'model'
        
    Returns:
        Dict with:
            - facts_count: Number of facts extracted
            - facts_extracted: Boolean success flag
            - embedding_count: Number of embeddings created
            - error: Error message if failed, else None
    """
    try:
        # Initialize Supabase client
        from supabase import create_client
        client = create_client(
            supabase_config["url"],
            supabase_config["key"]
        )
        
        # Extract facts using LLM
        facts = _extract_facts_llm(
            article_content,
            llm_config["api_url"],
            llm_config["api_key"],
            llm_config.get("model", DEFAULT_FACT_MODEL)
        )
        
        if not facts:
            return {
                "facts_count": 0,
                "facts_extracted": False,
                "embedding_count": 0,
                "error": "No facts extracted from article"
            }
        
        # Filter non-story facts
        filtered_facts = _filter_story_facts(facts)
        
        if not filtered_facts:
            return {
                "facts_count": 0,
                "facts_extracted": False,
                "embedding_count": 0,
                "error": "All extracted facts were filtered as non-story content"
            }
        
        # Store facts in database
        fact_ids = _store_facts(
            client,
            news_url_id,
            filtered_facts,
            llm_config.get("model", DEFAULT_FACT_MODEL)
        )
        
        if not fact_ids:
            return {
                "facts_count": len(filtered_facts),
                "facts_extracted": True,
                "embedding_count": 0,
                "error": "Facts already exist or storage failed"
            }
        
        # Generate and store embeddings
        embedding_count = _create_embeddings(
            client,
            fact_ids,
            embedding_config["api_url"],
            embedding_config["api_key"],
            embedding_config.get("model", DEFAULT_EMBEDDING_MODEL)
        )
        
        # Create pooled embedding for article
        _create_pooled_embedding(
            client,
            news_url_id,
            embedding_config.get("model", DEFAULT_EMBEDDING_MODEL)
        )
        
        # Mark timestamps
        now_iso = datetime.now(timezone.utc).isoformat()
        client.table("news_urls").update({
            "content_extracted_at": now_iso,
            "facts_extracted_at": now_iso
        }).eq("id", news_url_id).execute()
        
        return {
            "facts_count": len(fact_ids),
            "facts_extracted": True,
            "embedding_count": embedding_count,
            "error": None
        }
        
    except Exception as e:
        logger.error(f"Fact extraction failed for {news_url_id}: {e}", exc_info=True)
        return {
            "facts_count": 0,
            "facts_extracted": False,
            "embedding_count": 0,
            "error": str(e)
        }


def _extract_facts_llm(
    article_content: str,
    llm_api_url: str,
    llm_api_key: str,
    model: str
) -> List[str]:
    """Call LLM to extract facts from article.
    
    Args:
        article_content: Article text
        llm_api_url: Gemini API base URL
        llm_api_key: API key
        model: Model name
        
    Returns:
        List of extracted fact strings
    """
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    formatted_prompt = FACT_PROMPT.format(current_date=current_date)
    
    # Build Gemini API URL
    url = f"{llm_api_url}/{model}:generateContent?key={llm_api_key}"
    
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [{
            "parts": [{
                "text": f"{formatted_prompt}\n\nArticle:\n{article_content}"
            }]
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 32000,
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        # Parse Gemini response
        if isinstance(data, dict) and "candidates" in data:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            
            # Clean control characters
            text = ''.join(char for char in text if ord(char) >= 32 or char in '\t\n\r')
            
            # Extract JSON
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*)', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                json_str = re.sub(r'\s*```\s*$', '', json_str)
                json_str = ''.join(char for char in json_str if ord(char) >= 32 or char in '\t\n\r')
                
                try:
                    parsed = json.loads(json_str)
                    facts = parsed.get("facts", [])
                    if isinstance(facts, list):
                        return [f.strip() for f in facts if isinstance(f, str) and f.strip()]
                except json.JSONDecodeError:
                    pass
            
            # Try parsing entire text
            try:
                parsed = json.loads(text.strip())
                facts = parsed.get("facts", [])
                if isinstance(facts, list):
                    return [f.strip() for f in facts if isinstance(f, str) and f.strip()]
            except json.JSONDecodeError:
                pass
        
        logger.warning("Failed to parse LLM response for facts")
        return []
        
    except Exception as e:
        logger.error(f"LLM fact extraction failed: {e}")
        return []


def _filter_story_facts(facts: List[str]) -> List[str]:
    """Filter out non-story facts (author bios, navigation, etc.).
    
    Args:
        facts: List of fact strings
        
    Returns:
        Filtered list of story facts
    """
    import re
    
    filtered = []
    
    non_story_patterns = [
        r'\b(is a|is an)\b.{0,30}\b(reporter|writer|journalist|correspondent|analyst|contributor|editor|columnist)\b',
        r'\b(covers|covering)\b.{0,50}\b(at espn|for espn|at nfl\.com)',
        r'\b(joining|joined)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)',
        r'\bcontributes to\b.{0,50}\b(espn|nfl live|get up|sportscenter)',
        r'\bis (the )?author of\b',
        r'\bmember of the\b.{0,50}\b(board of selectors|hall of fame)',
        r'\b(follow|contact).{0,20}\b(twitter|facebook|instagram)',
        r'@\w+',
        r'\b(advertisement|sponsored|promoted)\b',
    ]
    
    for fact in facts:
        if not fact or len(fact) < 15:
            continue
        
        fact_lower = fact.lower()
        is_valid = True
        
        for pattern in non_story_patterns:
            if re.search(pattern, fact_lower, re.IGNORECASE):
                is_valid = False
                break
        
        if is_valid:
            filtered.append(fact)
    
    return filtered


def _store_facts(
    client,
    news_url_id: str,
    facts: List[str],
    model: str
) -> List[str]:
    """Store facts in database.
    
    Args:
        client: Supabase client
        news_url_id: News URL ID
        facts: List of fact strings
        model: LLM model name
        
    Returns:
        List of created fact IDs
    """
    if not facts:
        return []
    
    # Check if facts already exist
    existing = client.table("news_facts").select("id").eq(
        "news_url_id", news_url_id
    ).eq("prompt_version", FACT_PROMPT_VERSION).limit(1).execute()
    
    if getattr(existing, "data", []):
        logger.info(f"Facts already exist for {news_url_id}")
        return []
    
    # Prepare records
    records = [
        {
            "news_url_id": news_url_id,
            "fact_text": fact,
            "llm_model": model,
            "prompt_version": FACT_PROMPT_VERSION,
        }
        for fact in facts
    ]
    
    # Insert
    try:
        response = client.table("news_facts").insert(records).execute()
        data = getattr(response, "data", []) or []
        fact_ids = [row.get("id") for row in data if row.get("id")]
        logger.info(f"Stored {len(fact_ids)} facts for {news_url_id}")
        return fact_ids
    except Exception as e:
        logger.error(f"Failed to store facts: {e}")
        return []


def _create_embeddings(
    client,
    fact_ids: List[str],
    embedding_api_url: str,
    embedding_api_key: str,
    model: str
) -> int:
    """Generate and store embeddings for facts.
    
    Args:
        client: Supabase client
        fact_ids: List of fact IDs
        embedding_api_url: OpenAI API URL
        embedding_api_key: API key
        model: Embedding model name
        
    Returns:
        Number of embeddings created
    """
    if not fact_ids:
        return 0
    
    # Check existing embeddings
    existing = client.table("facts_embeddings").select("news_fact_id").in_(
        "news_fact_id", fact_ids
    ).execute()
    existing_ids = {row.get("news_fact_id") for row in (getattr(existing, "data", []) or [])}
    
    facts_to_embed = [fid for fid in fact_ids if fid not in existing_ids]
    if not facts_to_embed:
        return 0
    
    # Fetch fact texts
    facts_response = client.table("news_facts").select("id,fact_text").in_(
        "id", facts_to_embed
    ).execute()
    fact_rows = getattr(facts_response, "data", []) or []
    
    if not fact_rows:
        return 0
    
    # Generate embeddings (batch up to 100)
    texts = [row.get("fact_text", "") for row in fact_rows]
    embeddings = _generate_embeddings_batch(
        texts,
        embedding_api_url,
        embedding_api_key,
        model
    )
    
    if not embeddings or len(embeddings) != len(fact_rows):
        logger.error(f"Embedding generation failed or count mismatch")
        return 0
    
    # Prepare embedding records
    embedding_records = []
    for idx, row in enumerate(fact_rows):
        if idx < len(embeddings) and embeddings[idx]:
            embedding_records.append({
                "news_fact_id": row.get("id"),
                "embedding_vector": embeddings[idx],
                "model_name": model,
            })
    
    # Insert embeddings
    if embedding_records:
        try:
            response = client.table("facts_embeddings").insert(embedding_records).execute()
            inserted = len(getattr(response, "data", []) or [])
            logger.info(f"Created {inserted} embeddings")
            return inserted
        except Exception as e:
            logger.error(f"Failed to insert embeddings: {e}")
            return 0
    
    return 0


def _generate_embeddings_batch(
    texts: List[str],
    api_url: str,
    api_key: str,
    model: str
) -> List[List[float]]:
    """Generate embeddings for batch of texts.
    
    Args:
        texts: List of text strings
        api_url: OpenAI API URL
        api_key: API key
        model: Model name
        
    Returns:
        List of embedding vectors
    """
    if not texts:
        return []
    
    # Process in batches of 100
    BATCH_SIZE = 100
    all_embeddings = []
    
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model,
                "input": batch,
            }
            
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Extract embeddings in order
            batch_embeddings = []
            for item in data.get("data", []):
                embedding = item.get("embedding", [])
                if isinstance(embedding, list):
                    batch_embeddings.append(embedding)
            
            all_embeddings.extend(batch_embeddings)
            
        except Exception as e:
            logger.error(f"Embedding batch failed: {e}")
            # Return empty for failed batch
            all_embeddings.extend([[] for _ in batch])
    
    return all_embeddings


def _create_pooled_embedding(
    client,
    news_url_id: str,
    model: str
) -> None:
    """Create article-level pooled embedding by averaging fact embeddings.
    
    Args:
        client: Supabase client
        news_url_id: News URL ID
        model: Embedding model name
    """
    # Check if already exists
    existing = client.table("story_embeddings").select("id").eq(
        "news_url_id", news_url_id
    ).eq("embedding_type", "fact_pooled").limit(1).execute()
    
    if getattr(existing, "data", []):
        return
    
    # Get fact IDs
    facts_response = client.table("news_facts").select("id").eq(
        "news_url_id", news_url_id
    ).execute()
    fact_rows = getattr(facts_response, "data", []) or []
    fact_ids = [row.get("id") for row in fact_rows if row.get("id")]
    
    if not fact_ids:
        return
    
    # Get embeddings
    embeddings_response = client.table("facts_embeddings").select(
        "embedding_vector"
    ).in_("news_fact_id", fact_ids).execute()
    embedding_rows = getattr(embeddings_response, "data", []) or []
    
    vectors = []
    for row in embedding_rows:
        vector = row.get("embedding_vector")
        
        # Parse if string (Supabase VECTOR returns as string)
        if isinstance(vector, str):
            try:
                import re
                vector = json.loads(vector.strip('[]'))
            except:
                pass
        
        if isinstance(vector, list) and vector:
            vectors.append(vector)
    
    if not vectors:
        return
    
    # Average vectors
    dimension = len(vectors[0])
    totals = [0.0] * dimension
    
    for vector in vectors:
        if len(vector) != dimension:
            continue
        for idx, val in enumerate(vector):
            totals[idx] += float(val)
    
    averaged = [val / len(vectors) for val in totals]
    
    # Insert pooled embedding
    try:
        client.table("story_embeddings").insert({
            "news_url_id": news_url_id,
            "embedding_vector": averaged,
            "model_name": model,
            "embedding_type": "fact_pooled",
            "scope": "article",
            "primary_topic": None,
            "primary_team": None,
        }).execute()
        logger.info(f"Created pooled embedding for {news_url_id}")
    except Exception as e:
        logger.error(f"Failed to create pooled embedding: {e}")
