"""Process summary batch outputs and persist summaries using bulk operations."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)

SUMMARY_PROMPT_VERSION = "summary-from-facts-v1"
TOPIC_SUMMARY_PROMPT_VERSION = "summary-from-facts-topic-v1"


@dataclass
class SummaryBatchResult:
    """Summary of processing a summary batch output file."""

    articles_processed: int = 0
    summaries_written: int = 0
    topic_summaries_written: int = 0
    embeddings_created: int = 0
    articles_in_output: int = 0
    articles_skipped_existing: int = 0
    articles_skipped_no_data: int = 0
    errors: List[str] = field(default_factory=list)


class SummaryBatchResultProcessor:
    """Parse batch output lines and write summaries to the database using bulk operations."""

    def __init__(
        self,
        *,
        embedding_api_key: Optional[str] = None,
        embedding_model: str = "text-embedding-3-small",
        continue_on_error: bool = True,
        chunk_size: int = 100,
    ) -> None:
        self.client = get_supabase_client()
        self.embedding_api_key = embedding_api_key
        self.embedding_model = embedding_model
        self.continue_on_error = continue_on_error
        self.chunk_size = chunk_size
        logger.info("Initialized SummaryBatchResultProcessor with bulk operations")

    def process(
        self,
        output_file: Path,
        *,
        model: str,
        dry_run: bool = False,
        skip_existing: bool = False,
        create_embeddings: bool = True,
    ) -> SummaryBatchResult:
        """Process a downloaded batch output file using bulk database operations."""

        if not output_file.exists():
            raise FileNotFoundError(f"Output file not found: {output_file}")

        result = SummaryBatchResult()
        
        # Group results by article for proper handling
        easy_summaries: Dict[str, str] = {}  # news_url_id -> summary
        hard_summaries: Dict[str, List[Dict[str, Any]]] = {}  # news_url_id -> list of topic summaries
        seen_articles: set[str] = set()

        # Phase 1: Parse all results from the output file
        logger.info("Phase 1: Parsing batch output file...")
        with output_file.open("r") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    msg = f"Invalid JSON on line {line_number}: {exc}"
                    logger.error(msg)
                    result.errors.append(msg)
                    if not self.continue_on_error:
                        raise
                    continue

                custom_id = record.get("custom_id", "")
                error = record.get("error")
                response = record.get("response") or {}

                if error:
                    msg = f"Batch request {custom_id} failed: {error}"
                    logger.error(msg)
                    result.errors.append(msg)
                    if not self.continue_on_error:
                        raise RuntimeError(msg)
                    continue

                if response.get("status_code") != 200:
                    msg = f"Non-200 response for {custom_id}: {response}"
                    logger.error(msg)
                    result.errors.append(msg)
                    if not self.continue_on_error:
                        raise RuntimeError(msg)
                    continue

                body = response.get("body") or {}
                output_text = self._extract_output_text(body)
                
                if not output_text:
                    logger.warning("No output text for %s", custom_id)
                    continue

                summary = self._parse_summary(output_text)
                if not summary:
                    logger.warning("Failed to parse summary for %s", custom_id)
                    result.articles_skipped_no_data += 1
                    continue

                # Parse custom_id to determine type and article
                parsed = self._parse_custom_id(custom_id)
                if not parsed:
                    logger.warning("Failed to parse custom_id: %s", custom_id)
                    continue

                news_url_id = parsed["news_url_id"]
                seen_articles.add(news_url_id)

                if parsed["type"] == "easy":
                    easy_summaries[news_url_id] = summary
                else:
                    if news_url_id not in hard_summaries:
                        hard_summaries[news_url_id] = []
                    hard_summaries[news_url_id].append({
                        "topic": parsed.get("topic", "general"),
                        "scope_type": parsed.get("scope_type"),
                        "scope_id": parsed.get("scope_id"),
                        "scope_label": parsed.get("scope_label"),
                        "summary": summary,
                    })

        result.articles_in_output = len(seen_articles)
        logger.info(f"Parsed {len(easy_summaries)} easy and {len(hard_summaries)} hard articles")

        if dry_run:
            result.summaries_written = len(easy_summaries)
            result.topic_summaries_written = sum(len(ts) for ts in hard_summaries.values())
            result.articles_processed = len(seen_articles)
            logger.info("[DRY RUN] Would process %d articles", len(seen_articles))
            return result

        # Phase 2: Filter out existing articles if skip_existing is set
        if skip_existing:
            easy_summaries, hard_summaries, skipped = self._filter_existing(
                easy_summaries, hard_summaries
            )
            result.articles_skipped_existing = skipped
            logger.info(f"Skipped {skipped} existing articles")

        # Phase 3: Bulk clear existing data for articles we're about to update
        all_article_ids = list(easy_summaries.keys()) + list(hard_summaries.keys())
        if all_article_ids:
            logger.info(f"Phase 2: Clearing existing data for {len(all_article_ids)} articles...")
            self._bulk_clear_existing(all_article_ids)

        # Phase 4: Bulk insert easy summaries
        if easy_summaries:
            logger.info(f"Phase 3: Inserting {len(easy_summaries)} easy summaries...")
            written = self._bulk_insert_easy_summaries(easy_summaries, model)
            result.summaries_written = written

        # Phase 5: Bulk insert topic summaries for hard articles
        if hard_summaries:
            logger.info(f"Phase 4: Inserting topic summaries for {len(hard_summaries)} hard articles...")
            written = self._bulk_insert_topic_summaries(hard_summaries, model)
            result.topic_summaries_written = written

        # Phase 6: Create embeddings (batch API call for multiple texts)
        if create_embeddings and self.embedding_api_key:
            logger.info("Phase 5: Creating embeddings...")
            embeddings_created = self._bulk_create_embeddings(easy_summaries, hard_summaries)
            result.embeddings_created = embeddings_created

        # Phase 7: Bulk mark articles as completed
        if all_article_ids:
            logger.info(f"Phase 6: Marking {len(all_article_ids)} articles as completed...")
            self._bulk_mark_completed(all_article_ids)

        result.articles_processed = len(all_article_ids)
        logger.info(f"Batch processing complete: {result.articles_processed} articles processed")

        return result

    def _filter_existing(
        self,
        easy_summaries: Dict[str, str],
        hard_summaries: Dict[str, List[Dict]],
    ) -> tuple[Dict[str, str], Dict[str, List[Dict]], int]:
        """Filter out articles that already have summaries."""
        
        all_ids = list(easy_summaries.keys()) + list(hard_summaries.keys())
        if not all_ids:
            return easy_summaries, hard_summaries, 0

        # Check which articles already have summaries
        existing_easy = set()
        existing_hard = set()

        # Check context_summaries in chunks
        for i in range(0, len(all_ids), self.chunk_size):
            chunk = all_ids[i:i + self.chunk_size]
            response = (
                self.client.table("context_summaries")
                .select("news_url_id")
                .in_("news_url_id", chunk)
                .execute()
            )
            for row in getattr(response, "data", []) or []:
                existing_easy.add(row["news_url_id"])

        # Check topic_summaries in chunks
        for i in range(0, len(all_ids), self.chunk_size):
            chunk = all_ids[i:i + self.chunk_size]
            response = (
                self.client.table("topic_summaries")
                .select("news_url_id")
                .in_("news_url_id", chunk)
                .execute()
            )
            for row in getattr(response, "data", []) or []:
                existing_hard.add(row["news_url_id"])

        # Filter out existing
        filtered_easy = {k: v for k, v in easy_summaries.items() if k not in existing_easy}
        filtered_hard = {k: v for k, v in hard_summaries.items() if k not in existing_hard}
        
        skipped = (len(easy_summaries) - len(filtered_easy)) + (len(hard_summaries) - len(filtered_hard))
        
        return filtered_easy, filtered_hard, skipped

    def _bulk_clear_existing(self, article_ids: List[str]) -> None:
        """Bulk delete existing summaries and embeddings for articles."""
        
        for i in range(0, len(article_ids), self.chunk_size):
            chunk = article_ids[i:i + self.chunk_size]
            
            # Delete from context_summaries
            self.client.table("context_summaries").delete().in_(
                "news_url_id", chunk
            ).execute()
            
            # Delete from topic_summaries
            self.client.table("topic_summaries").delete().in_(
                "news_url_id", chunk
            ).execute()
            
            # Delete summary embeddings from story_embeddings
            self.client.table("story_embeddings").delete().in_(
                "news_url_id", chunk
            ).eq("embedding_type", "summary").execute()

    def _bulk_insert_easy_summaries(
        self,
        easy_summaries: Dict[str, str],
        model: str,
    ) -> int:
        """Bulk insert article-level summaries."""
        
        records = [
            {
                "news_url_id": news_url_id,
                "summary_text": summary,
                "llm_model": model,
                "prompt_version": SUMMARY_PROMPT_VERSION,
            }
            for news_url_id, summary in easy_summaries.items()
        ]

        total_written = 0
        for i in range(0, len(records), self.chunk_size):
            chunk = records[i:i + self.chunk_size]
            response = self.client.table("context_summaries").insert(chunk).execute()
            total_written += len(getattr(response, "data", []) or chunk)

        return total_written

    def _bulk_insert_topic_summaries(
        self,
        hard_summaries: Dict[str, List[Dict]],
        model: str,
    ) -> int:
        """Bulk insert topic-level summaries."""
        
        records = []
        skipped = 0
        for news_url_id, topic_list in hard_summaries.items():
            for topic_data in topic_list:
                topic = topic_data["topic"]
                scope_type = topic_data.get("scope_type")
                scope_id = topic_data.get("scope_id")
                scope_label = topic_data.get("scope_label") or scope_id
                
                # Skip corrupted records with malformed data
                if self._is_corrupted_topic_summary(topic, scope_type, scope_id):
                    logger.warning(
                        "Skipping corrupted topic summary: topic=%s, scope_type=%s, scope_id=%s",
                        topic, scope_type, scope_id
                    )
                    skipped += 1
                    continue
                
                primary_team = scope_id if scope_type == "team" else None
                
                records.append({
                    "news_url_id": news_url_id,
                    "primary_topic": topic,
                    "primary_team": primary_team,
                    "primary_scope_type": scope_type if scope_type != "none" else None,
                    "primary_scope_id": scope_id if scope_id != "none" else None,
                    "primary_scope_label": scope_label if scope_label != "none" else None,
                    "summary_text": topic_data["summary"],
                    "llm_model": model,
                    "prompt_version": TOPIC_SUMMARY_PROMPT_VERSION,
                })

        total_written = 0
        for i in range(0, len(records), self.chunk_size):
            chunk = records[i:i + self.chunk_size]
            response = self.client.table("topic_summaries").insert(chunk).execute()
            total_written += len(getattr(response, "data", []) or chunk)

        return total_written

    def _bulk_create_embeddings(
        self,
        easy_summaries: Dict[str, str],
        hard_summaries: Dict[str, List[Dict]],
    ) -> int:
        """Create embeddings using batch API calls."""
        
        if not self.embedding_api_key:
            return 0

        # Collect all texts to embed with their metadata
        embedding_tasks: List[Dict[str, Any]] = []
        
        # Easy article summaries
        for news_url_id, summary in easy_summaries.items():
            embedding_tasks.append({
                "news_url_id": news_url_id,
                "text": summary,
                "scope": "article",
                "primary_topic": None,
                "primary_team": None,
                "primary_scope_type": None,
                "primary_scope_id": None,
            })
        
        # Hard article topic summaries
        for news_url_id, topic_list in hard_summaries.items():
            for topic_data in topic_list:
                scope_type = topic_data.get("scope_type")
                scope_id = topic_data.get("scope_id")
                primary_team = scope_id if scope_type == "team" else None
                
                embedding_tasks.append({
                    "news_url_id": news_url_id,
                    "text": topic_data["summary"],
                    "scope": "topic",
                    "primary_topic": topic_data["topic"],
                    "primary_team": primary_team,
                    "primary_scope_type": scope_type if scope_type != "none" else None,
                    "primary_scope_id": scope_id if scope_id != "none" else None,
                })

        if not embedding_tasks:
            return 0

        # Process embeddings in batches (OpenAI supports up to 2048 inputs per request)
        embedding_batch_size = 100  # Conservative batch size
        total_embeddings = 0
        
        for i in range(0, len(embedding_tasks), embedding_batch_size):
            batch = embedding_tasks[i:i + embedding_batch_size]
            texts = [task["text"] for task in batch]
            
            try:
                response = requests.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.embedding_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.embedding_model,
                        "input": texts,
                    },
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
                
                # Build embedding records
                embedding_records = []
                for idx, embedding_data in enumerate(data["data"]):
                    task = batch[idx]
                    embedding_records.append({
                        "news_url_id": task["news_url_id"],
                        "embedding_vector": embedding_data["embedding"],
                        "model_name": self.embedding_model,
                        "embedding_type": "summary",
                        "scope": task["scope"],
                        "primary_topic": task["primary_topic"],
                        "primary_team": task["primary_team"],
                        "primary_scope_type": task["primary_scope_type"],
                        "primary_scope_id": task["primary_scope_id"],
                    })
                
                # Bulk insert embeddings
                for j in range(0, len(embedding_records), self.chunk_size):
                    chunk = embedding_records[j:j + self.chunk_size]
                    self.client.table("story_embeddings").insert(chunk).execute()
                    total_embeddings += len(chunk)
                
                logger.info(f"Created {len(embedding_records)} embeddings (batch {i // embedding_batch_size + 1})")
                
            except Exception as exc:
                logger.warning(f"Failed to create embeddings for batch: {exc}")
                if not self.continue_on_error:
                    raise

        return total_embeddings

    def _bulk_mark_completed(self, article_ids: List[str]) -> None:
        """Bulk update articles to mark summary as completed."""
        
        now_iso = datetime.now(timezone.utc).isoformat()
        
        for i in range(0, len(article_ids), self.chunk_size):
            chunk = article_ids[i:i + self.chunk_size]
            self.client.table("news_urls").update({
                "summary_created_at": now_iso
            }).in_("id", chunk).execute()

    def _extract_output_text(self, body: Dict) -> str:
        """Pull the text payload from chat completion style bodies."""

        choices = body.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        return part.get("text", "")
        return ""

    def _parse_summary(self, output_text: str) -> Optional[str]:
        """Parse summary from model output."""

        try:
            data = json.loads(output_text)
            if isinstance(data, dict) and "summary" in data:
                return data["summary"].strip()
        except json.JSONDecodeError:
            # Try to extract JSON from text
            match = re.search(r'\{[^{}]*"summary"\s*:\s*"([^"]+)"[^{}]*\}', output_text, re.DOTALL)
            if match:
                return match.group(1).strip()
            
            # Try finding JSON block
            start = output_text.find("{")
            end = output_text.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    data = json.loads(output_text[start:end])
                    if isinstance(data, dict) and "summary" in data:
                        return data["summary"].strip()
                except json.JSONDecodeError:
                    pass

        return None

    def _parse_custom_id(self, custom_id: str) -> Optional[Dict[str, Any]]:
        """Parse custom_id to extract article info."""

        if custom_id.startswith("easy_"):
            # Format: easy_{news_url_id}
            news_url_id = custom_id[5:]  # Remove "easy_" prefix
            return {"type": "easy", "news_url_id": news_url_id}
        
        elif custom_id.startswith("hard_"):
            # New format: hard_{news_url_id}_{idx}|{topic}|{scope_type}|{scope_id}|{scope_label}
            # Old format: hard_{news_url_id}_{idx}_{topic}_{scope_type}_{scope_id} (deprecated)
            
            # Check for new pipe-delimited format
            if "|" in custom_id:
                # Split prefix from pipe-delimited parts
                prefix_end = custom_id.find("|")
                prefix = custom_id[:prefix_end]  # hard_{news_url_id}_{idx}
                rest = custom_id[prefix_end + 1:]  # topic|scope_type|scope_id|scope_label
                
                prefix_parts = prefix.split("_")
                if len(prefix_parts) >= 3:
                    news_url_id = prefix_parts[1]
                    idx = prefix_parts[2]
                    
                    rest_parts = rest.split("|")
                    topic = rest_parts[0] if len(rest_parts) > 0 else "general"
                    scope_type = rest_parts[1] if len(rest_parts) > 1 else None
                    scope_id = rest_parts[2] if len(rest_parts) > 2 else None
                    scope_label = rest_parts[3] if len(rest_parts) > 3 else scope_id
                    
                    return {
                        "type": "hard",
                        "news_url_id": news_url_id,
                        "index": idx,
                        "topic": topic,
                        "scope_type": scope_type,
                        "scope_id": scope_id,
                        "scope_label": scope_label,
                    }
            else:
                # Fallback: old underscore-delimited format (deprecated)
                parts = custom_id.split("_", 5)
                if len(parts) >= 5:
                    return {
                        "type": "hard",
                        "news_url_id": parts[1],
                        "index": parts[2],
                        "topic": parts[3] if len(parts) > 3 else "general",
                        "scope_type": parts[4] if len(parts) > 4 else None,
                        "scope_id": parts[5] if len(parts) > 5 else None,
                        "scope_label": parts[5] if len(parts) > 5 else None,
                    }

        return None

    def _is_corrupted_topic_summary(
        self,
        topic: Optional[str],
        scope_type: Optional[str],
        scope_id: Optional[str],
    ) -> bool:
        """Check if topic summary data appears corrupted from parsing issues."""
        
        # Check for known corruption patterns
        corruption_patterns = [
            # scope_type should be team/player/game/none, not 'topics' or '&'
            scope_type == "topics",
            scope_type == "&",
            # scope_id should not contain 'found_player', 'found_team', etc.
            scope_id and "found_player" in str(scope_id),
            scope_id and "found_team" in str(scope_id),
            scope_id and "found_none" in str(scope_id),
            # scope_id should not start with '&_'
            scope_id and str(scope_id).startswith("&_"),
            # scope_id should not contain '_&_'
            scope_id and "_&_" in str(scope_id),
            # topic 'no' is likely from parsing 'no_topics_found' incorrectly
            topic == "no",
            # UNRESOLVED markers shouldn't be stored
            scope_id and "UNRESOLVED:" in str(scope_id),
        ]
        
        return any(corruption_patterns)
