"""Process completed batch outputs for fact extraction."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from openai import OpenAI

from src.shared.db.connection import get_supabase_client
from ..facts.parser import parse_fact_response, extract_json_from_text
from ..facts.filter import filter_story_facts
from ..facts.prompts import FACT_PROMPT_VERSION

logger = logging.getLogger(__name__)

MAX_FACTS_PER_ARTICLE = 25


@dataclass
class ProcessingResult:
    """Summary of batch processing results."""

    articles_in_output: int = 0
    articles_processed: int = 0
    articles_skipped_existing: int = 0
    articles_skipped_no_facts: int = 0
    articles_with_errors: int = 0
    facts_extracted: int = 0
    facts_filtered: int = 0
    facts_written: int = 0
    embeddings_created: int = 0
    errors: List[str] = field(default_factory=list)


class FactsBatchResultProcessor:
    """Process completed OpenAI batch outputs for fact extraction.

    Parses batch output JSONL, extracts and filters facts, stores to database,
    and optionally creates embeddings.
    
    Example:
        processor = FactsBatchResultProcessor()
        result = processor.process(
            output_file=Path("./batch_files/output.jsonl"),
            model="gpt-5-nano",
        )
        print(f"Processed {result.articles_processed} articles")
    """

    def __init__(
        self,
        *,
        embedding_api_key: Optional[str] = None,
        embedding_model: str = "text-embedding-3-small",
        chunk_size: int = 100,
    ) -> None:
        """Initialize result processor.
        
        Args:
            embedding_api_key: API key for creating embeddings
            embedding_model: Model for embeddings
            chunk_size: Chunk size for bulk operations
        """
        self.client = get_supabase_client()
        self.embedding_api_key = embedding_api_key
        self.embedding_model = embedding_model
        self.chunk_size = chunk_size
        # Instantiate a request-scoped OpenAI client instead of mutating the
        # `openai.api_key` module global (unsafe in warm Cloud Function
        # containers serving multiple tenants).
        self._openai: Optional[OpenAI] = (
            OpenAI(api_key=embedding_api_key) if embedding_api_key else None
        )

    def process(
        self,
        output_file: Path,
        model: str,
        *,
        dry_run: bool = False,
        skip_existing: bool = True,
        create_embeddings: bool = True,
        force_delete: bool = False,
    ) -> ProcessingResult:
        """Process a completed batch output file.
        
        Args:
            output_file: Path to the JSONL output file
            model: Model used for extraction (for metadata)
            dry_run: If True, don't write to database
            skip_existing: Skip articles that already have facts
            create_embeddings: Create embeddings for new facts
            force_delete: Delete existing facts before inserting (for re-extraction)
            
        Returns:
            ProcessingResult with statistics
        """
        result = ProcessingResult()

        # Phase 1: Parse all responses
        parsed_responses = self._parse_output_file(output_file, result)
        result.articles_in_output = len(parsed_responses)

        if not parsed_responses:
            logger.warning("No valid responses found in batch output")
            return result

        # Phase 2: Handle existing facts
        article_ids = list(parsed_responses.keys())
        if force_delete:
            # Delete existing facts for all articles in the batch
            if not dry_run:
                self._bulk_delete_existing_data(article_ids)
                logger.info(f"Deleted existing data for {len(article_ids)} articles (force_delete mode)")
        elif skip_existing:
            existing = self._check_existing_facts(article_ids)
            for article_id in existing:
                del parsed_responses[article_id]
                result.articles_skipped_existing += 1

        if not parsed_responses:
            logger.info("All articles already have facts, nothing to process")
            return result

        # Phase 3: Extract and filter facts
        facts_by_article: Dict[str, List[str]] = {}
        for article_id, response_data in parsed_responses.items():
            raw_facts = self._extract_facts_from_response(response_data)
            
            if not raw_facts:
                result.articles_skipped_no_facts += 1
                continue

            valid_facts, rejected = filter_story_facts(raw_facts)
            result.facts_extracted += len(raw_facts)
            result.facts_filtered += len(rejected)

            # Enforce cap to avoid runaway fact counts per article
            if len(valid_facts) > MAX_FACTS_PER_ARTICLE:
                trimmed = len(valid_facts) - MAX_FACTS_PER_ARTICLE
                valid_facts = valid_facts[:MAX_FACTS_PER_ARTICLE]
                result.facts_filtered += trimmed
                logger.debug(
                    "Trimmed %d facts over cap for article %s", trimmed, article_id
                )

            if valid_facts:
                facts_by_article[article_id] = valid_facts
            else:
                result.articles_skipped_no_facts += 1

        if not facts_by_article:
            logger.warning("No valid facts extracted from any article")
            return result

        if dry_run:
            logger.info(
                "DRY RUN: Would write facts for %d articles",
                len(facts_by_article),
            )
            result.articles_processed = len(facts_by_article)
            result.facts_written = sum(len(f) for f in facts_by_article.values())
            return result

        # Phase 4: Bulk insert facts (returns text map so embeddings can skip
        # a redundant SELECT against the rows we just wrote).
        fact_ids_by_article, texts_by_id = self._bulk_insert_facts(
            facts_by_article, model
        )
        result.articles_processed = len(fact_ids_by_article)
        result.facts_written = sum(len(ids) for ids in fact_ids_by_article.values())

        # Phase 5: Create embeddings
        if create_embeddings and self.embedding_api_key:
            all_fact_ids = [
                fid for ids in fact_ids_by_article.values() for fid in ids
            ]
            if all_fact_ids:
                result.embeddings_created = self._bulk_create_embeddings(
                    all_fact_ids, texts_by_id=texts_by_id
                )

        # Phase 6: Mark facts_extracted_at and update stats
        if fact_ids_by_article:
            self._bulk_mark_completed(facts_by_article)

        logger.info(
            "Batch processing complete",
            extra={
                "articles_processed": result.articles_processed,
                "facts_written": result.facts_written,
                "embeddings_created": result.embeddings_created,
            },
        )

        return result

    def _parse_output_file(
        self,
        output_file: Path,
        result: ProcessingResult,
    ) -> Dict[str, Dict[str, Any]]:
        """Parse the JSONL output file.
        
        Returns:
            Dict mapping article_id to response data
        """
        parsed: Dict[str, Dict[str, Any]] = {}

        with output_file.open("r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    result.errors.append(f"Line {line_num}: JSON decode error: {e}")
                    result.articles_with_errors += 1
                    continue

                custom_id = data.get("custom_id", "")
                
                # Extract article ID from custom_id (format: facts_{news_url_id})
                if not custom_id.startswith("facts_"):
                    result.errors.append(f"Line {line_num}: Invalid custom_id: {custom_id}")
                    result.articles_with_errors += 1
                    continue

                article_id = custom_id[6:]  # Remove "facts_" prefix

                # Check for API errors
                error = data.get("error")
                if error:
                    result.errors.append(f"Article {article_id}: API error: {error}")
                    result.articles_with_errors += 1
                    continue

                # Extract response body
                response = data.get("response", {})
                body = response.get("body", {})
                
                if not body:
                    result.errors.append(f"Article {article_id}: Empty response body")
                    result.articles_with_errors += 1
                    continue

                parsed[article_id] = body

        return parsed

    def _extract_facts_from_response(self, response_body: Dict[str, Any]) -> List[str]:
        """Extract facts from a chat completion response.
        
        Args:
            response_body: The response body from the API
            
        Returns:
            List of fact strings
        """
        try:
            choices = response_body.get("choices", [])
            if not choices:
                return []

            message = choices[0].get("message", {})
            content = message.get("content", "")

            if not content:
                return []

            # Try to parse as JSON directly
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from text
                payload = extract_json_from_text(content)

            return parse_fact_response(payload)

        except Exception as e:
            logger.warning("Failed to extract facts from response: %s", e)
            return []

    def _check_existing_facts(self, article_ids: List[str]) -> Set[str]:
        """Check which articles already have facts.
        
        Returns:
            Set of article IDs that have existing facts
        """
        existing: Set[str] = set()

        # Page through all matching rows per chunk. The prior `.limit(len(chunk))`
        # silently truncated if some articles had many existing facts, letting
        # already-extracted articles re-enter the insert path.
        page_size = 1000
        for i in range(0, len(article_ids), self.chunk_size):
            chunk = article_ids[i:i + self.chunk_size]
            offset = 0
            while True:
                response = (
                    self.client.table("news_facts")
                    .select("news_url_id")
                    .in_("news_url_id", chunk)
                    .eq("prompt_version", FACT_PROMPT_VERSION)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                rows = getattr(response, "data", []) or []
                if not rows:
                    break
                existing.update(
                    row.get("news_url_id") for row in rows if row.get("news_url_id")
                )
                # Once every article in the chunk is known-existing we can stop.
                if set(chunk).issubset(existing):
                    break
                if len(rows) < page_size:
                    break
                offset += page_size

        return existing

    def _bulk_delete_existing_data(self, article_ids: List[str]) -> None:
        """Delete all existing facts and downstream data for articles.
        
        This is used for force re-extraction mode.
        """
        # First get all fact IDs for these articles
        all_fact_ids: List[str] = []
        
        for i in range(0, len(article_ids), self.chunk_size):
            chunk = article_ids[i:i + self.chunk_size]
            response = (
                self.client.table("news_facts")
                .select("id")
                .in_("news_url_id", chunk)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            all_fact_ids.extend(row.get("id") for row in rows if row.get("id"))
        
        if not all_fact_ids:
            logger.debug("No existing facts to delete")
            return
        
        logger.info(f"Deleting {len(all_fact_ids)} existing facts and downstream data...")
        
        # Delete in chunks to avoid URL length limits
        for i in range(0, len(all_fact_ids), self.chunk_size):
            chunk = all_fact_ids[i:i + self.chunk_size]
            # 1. Delete fact embeddings
            self.client.table("facts_embeddings").delete().in_("news_fact_id", chunk).execute()
            # 2. Delete entity links
            self.client.table("news_fact_entities").delete().in_("news_fact_id", chunk).execute()
            # 3. Delete topic links
            self.client.table("news_fact_topics").delete().in_("news_fact_id", chunk).execute()
            # 4. Delete the facts themselves
            self.client.table("news_facts").delete().in_("id", chunk).execute()
        
        # Delete story-level embeddings for these articles
        for i in range(0, len(article_ids), self.chunk_size):
            chunk = article_ids[i:i + self.chunk_size]
            self.client.table("story_embeddings").delete().in_("news_url_id", chunk).execute()
        
        # Reset timestamps on news_urls
        for i in range(0, len(article_ids), self.chunk_size):
            chunk = article_ids[i:i + self.chunk_size]
            self.client.table("news_urls").update({
                "facts_extracted_at": None,
                "facts_count": None,
                "article_difficulty": None,
                "knowledge_extracted_at": None,
                "knowledge_error_count": 0,
                "summary_created_at": None,
            }).in_("id", chunk).execute()
        
        logger.info(f"Deleted {len(all_fact_ids)} facts from {len(article_ids)} articles")

    def _bulk_insert_facts(
        self,
        facts_by_article: Dict[str, List[str]],
        model: str,
    ) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
        """Bulk insert facts for all articles.

        Returns:
            ``(result_ids, texts_by_id)`` where ``result_ids`` maps article_id
            to the list of created fact IDs, and ``texts_by_id`` maps each
            created fact ID back to its fact_text. The text map lets downstream
            stages (embeddings, pooling) skip a redundant ``SELECT`` against
            the rows we just wrote.
        """
        # Build all records with tracking
        all_records = []
        record_to_article: List[str] = []
        record_texts: List[str] = []

        for article_id, facts in facts_by_article.items():
            for fact in facts:
                all_records.append({
                    "news_url_id": article_id,
                    "fact_text": fact,
                    "llm_model": model,
                    "prompt_version": FACT_PROMPT_VERSION,
                })
                record_to_article.append(article_id)
                record_texts.append(fact)

        if not all_records:
            return {}, {}

        # Insert in chunks
        result_ids: Dict[str, List[str]] = {aid: [] for aid in facts_by_article}
        texts_by_id: Dict[str, str] = {}
        record_idx = 0

        for i in range(0, len(all_records), self.chunk_size):
            chunk = all_records[i:i + self.chunk_size]
            try:
                response = self.client.table("news_facts").insert(chunk).execute()
                data = getattr(response, "data", []) or []

                # PostgREST insert returns one row per inserted record in input
                # order. If the count diverges we cannot safely attribute IDs to
                # articles — skip mapping this chunk rather than corrupt the
                # downstream result map.
                if len(data) != len(chunk):
                    logger.error(
                        "Insert returned %d rows for chunk of %d; skipping ID "
                        "attribution for this chunk to avoid desync",
                        len(data),
                        len(chunk),
                    )
                else:
                    for offset, row in enumerate(data):
                        if isinstance(row, dict) and row.get("id"):
                            article_id = record_to_article[record_idx + offset]
                            result_ids[article_id].append(row["id"])
                            texts_by_id[row["id"]] = record_texts[record_idx + offset]

                record_idx += len(chunk)

                logger.debug(
                    "Inserted facts batch %d/%d",
                    i // self.chunk_size + 1,
                    (len(all_records) + self.chunk_size - 1) // self.chunk_size,
                )

            except Exception as e:
                logger.error("Failed to insert facts batch: %s", e)
                record_idx += len(chunk)

        return result_ids, texts_by_id

    def _bulk_create_embeddings(
        self,
        fact_ids: List[str],
        *,
        texts_by_id: Optional[Dict[str, str]] = None,
    ) -> int:
        """Create embeddings for facts in bulk.

        ``texts_by_id`` (optional): text already known from the insert step.
        When provided, skips the ``SELECT fact_text`` round-trip. Missing
        entries are filled by a fallback fetch so legacy callers keep working.
        """
        texts: Dict[str, str] = dict(texts_by_id or {})

        missing = [fid for fid in fact_ids if fid not in texts]
        for i in range(0, len(missing), self.chunk_size):
            chunk = missing[i:i + self.chunk_size]
            response = (
                self.client.table("news_facts")
                .select("id,fact_text")
                .in_("id", chunk)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            for row in rows:
                if row.get("id") and row.get("fact_text"):
                    texts[row["id"]] = row["fact_text"]

        texts_by_id = {fid: texts[fid] for fid in fact_ids if fid in texts}
        if not texts_by_id:
            return 0

        # Generate embeddings in batches
        total_created = 0
        ids_list = list(texts_by_id.keys())
        
        if self._openai is None:
            logger.error(
                "Embedding creation requested but no embedding_api_key was provided"
            )
            return 0

        for i in range(0, len(ids_list), self.chunk_size):
            chunk_ids = ids_list[i:i + self.chunk_size]
            chunk_texts = [texts_by_id[fid] for fid in chunk_ids]

            try:
                embed_response = self._openai.embeddings.create(
                    model=self.embedding_model,
                    input=chunk_texts,
                )

                records = []
                for idx, embedding_data in enumerate(embed_response.data):
                    records.append({
                        "news_fact_id": chunk_ids[idx],
                        "embedding_vector": embedding_data.embedding,
                        "model_name": self.embedding_model,
                    })

                if records:
                    self.client.table("facts_embeddings").insert(records).execute()
                    total_created += len(records)

            except Exception as e:
                logger.error("Failed to create embeddings batch: %s", e)

        return total_created

    def _bulk_mark_completed(self, facts_by_article: Dict[str, List[str]]) -> None:
        """Mark articles as having facts extracted and update stats.

        Updates facts_extracted_at, facts_count, and article_difficulty. To
        avoid N sequential UPDATEs (~50-100ms each → 25-50s for a 500-batch)
        we bucket articles by (difficulty, facts_count) and emit one UPDATE
        per bucket via ``in_("id", [...])``. ``facts_count`` collapses into
        relatively few buckets per batch (usually < 30), so this reduces DB
        round-trips by ~10-100x for typical inputs.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        buckets: Dict[Tuple[int, str], List[str]] = {}
        for article_id, facts in facts_by_article.items():
            facts_count = len(facts)
            difficulty = self._calculate_difficulty_from_facts(facts_count)
            buckets.setdefault((facts_count, difficulty), []).append(article_id)

        for (facts_count, difficulty), article_ids in buckets.items():
            # Split into chunks to respect PostgREST URL length limits.
            for i in range(0, len(article_ids), self.chunk_size):
                chunk = article_ids[i:i + self.chunk_size]
                try:
                    self.client.table("news_urls").update({
                        "facts_extracted_at": now_iso,
                        "facts_count": facts_count,
                        "article_difficulty": difficulty,
                    }).in_("id", chunk).execute()
                except Exception as e:
                    logger.error(
                        "Failed to mark facts_extracted_at for bucket "
                        "(count=%d, difficulty=%s, %d articles): %s",
                        facts_count,
                        difficulty,
                        len(chunk),
                        e,
                    )

    def _calculate_difficulty_from_facts(self, facts_count: int) -> str:
        """Calculate article difficulty based on facts count.
        
        Simple heuristic when content is not available:
        - < 10 facts: easy
        - 10-30 facts: medium  
        - > 30 facts: hard
        """
        if facts_count < 10:
            return "easy"
        elif facts_count <= 30:
            return "medium"
        else:
            return "hard"
