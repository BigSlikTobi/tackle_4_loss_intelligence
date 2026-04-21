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
from ..db import FactsReader, FactsWriter
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
        # Unified DB layer (single source of truth for facts schema I/O).
        self._reader = FactsReader(self.client)
        self._writer = FactsWriter(self.client)

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

    # ------------------------------------------------------------------
    # DB operations — thin wrappers over FactsReader / FactsWriter so the
    # batch path shares a single source of truth with the realtime path.
    # ------------------------------------------------------------------

    def _check_existing_facts(self, article_ids: List[str]) -> Set[str]:
        return self._reader.check_existing_facts(
            article_ids, chunk_size=self.chunk_size
        )

    def _bulk_delete_existing_data(self, article_ids: List[str]) -> None:
        deleted = self._writer.delete_fact_data(
            article_ids, chunk_size=self.chunk_size
        )
        if deleted:
            logger.info(
                "Deleted %d facts from %d articles", deleted, len(article_ids)
            )

    def _bulk_insert_facts(
        self,
        facts_by_article: Dict[str, List[str]],
        model: str,
    ) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
        return self._writer.insert_facts(
            facts_by_article, model, chunk_size=self.chunk_size
        )

    def _bulk_create_embeddings(
        self,
        fact_ids: List[str],
        *,
        texts_by_id: Optional[Dict[str, str]] = None,
    ) -> int:
        """Generate embeddings for ``fact_ids`` and persist them.

        ``texts_by_id`` (optional) avoids a ``SELECT`` against rows we just
        inserted; missing entries are filled via ``FactsReader`` so legacy
        callers continue to work.
        """
        if self._openai is None:
            logger.error(
                "Embedding creation requested but no embedding_api_key was provided"
            )
            return 0

        texts: Dict[str, str] = dict(texts_by_id or {})
        missing = [fid for fid in fact_ids if fid not in texts]
        if missing:
            texts.update(
                self._reader.fetch_fact_texts(missing, chunk_size=self.chunk_size)
            )

        ordered_ids = [fid for fid in fact_ids if fid in texts]
        if not ordered_ids:
            return 0

        records: List[Dict[str, Any]] = []
        for i in range(0, len(ordered_ids), self.chunk_size):
            chunk_ids = ordered_ids[i : i + self.chunk_size]
            chunk_texts = [texts[fid] for fid in chunk_ids]
            try:
                embed_response = self._openai.embeddings.create(
                    model=self.embedding_model,
                    input=chunk_texts,
                )
                for idx, embedding_data in enumerate(embed_response.data):
                    records.append(
                        {
                            "news_fact_id": chunk_ids[idx],
                            "embedding_vector": embedding_data.embedding,
                            "model_name": self.embedding_model,
                        }
                    )
            except Exception as exc:
                logger.error("Failed to create embeddings batch: %s", exc)

        return self._writer.insert_fact_embeddings(
            records, chunk_size=self.chunk_size
        )

    def _bulk_mark_completed(self, facts_by_article: Dict[str, List[str]]) -> None:
        self._writer.mark_facts_extracted(
            facts_by_article, chunk_size=self.chunk_size
        )
