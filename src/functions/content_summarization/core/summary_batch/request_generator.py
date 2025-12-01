"""Generate OpenAI batch requests for topic summary creation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)

SummaryTask = Literal["easy", "hard", "all"]

# Prompt for easy articles (single summary from all facts)
EASY_SUMMARY_PROMPT = """TASK: Summarize using ONLY the provided "facts". Closed world.

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

# Template for hard articles (topic-scoped summaries)
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
class GeneratedBatch:
    """Container describing the generated batch request file."""

    file_path: Path
    total_requests: int
    total_articles: int
    metadata_path: Path
    metadata: Dict


@dataclass
class PrefetchedArticleData:
    """Container for pre-fetched article data used during batch generation."""

    facts_by_article: Dict[str, List[str]]
    topic_groups_by_article: Dict[str, List[Dict[str, Any]]]


class SummaryBatchRequestGenerator:
    """Create JSONL payloads for the OpenAI Batch API for summary generation.

    Each request contains all facts for a single article (easy) or
    a topic-scoped subset of facts (hard articles).
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5-nano",
        output_dir: Optional[Path] = None,
        page_size: int = 25,
        skip_errors: bool = False,
    ) -> None:
        self.client = get_supabase_client()
        self.model = model
        self.output_dir = output_dir or Path("./batch_files")
        self.output_dir.mkdir(exist_ok=True)
        self.page_size = page_size
        self.skip_errors = skip_errors

        # Check if this is a reasoning model (gpt-5-nano, o1, o3)
        self.is_reasoning_model = (
            "nano" in model or
            model.startswith("o1") or
            model.startswith("o3") or
            "o1" in model or
            "o3" in model
        )

        logger.info(
            "Initialized SummaryBatchRequestGenerator",
            extra={
                "model": model,
                "is_reasoning_model": self.is_reasoning_model,
                "page_size": page_size,
                "skip_errors": skip_errors,
            },
        )

    def generate(
        self,
        *,
        task: SummaryTask = "all",
        limit: Optional[int] = None,
        max_age_hours: Optional[int] = None,
    ) -> GeneratedBatch:
        """Generate a JSONL file for summary batch processing."""

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"summary_batch_{task}_{timestamp}.jsonl"
        file_path = self.output_dir / filename

        # Fetch pending articles
        articles = self._fetch_pending_articles(task=task, limit=limit, max_age_hours=max_age_hours)

        prefetched_data = self._prefetch_article_data(articles)
        
        if not articles:
            raise ValueError("No eligible articles found for batch generation")

        total_requests = 0
        total_articles = 0
        article_ids: List[str] = []

        with file_path.open("w") as handle:
            for article in articles:
                news_url_id = article["id"]
                difficulty = article.get("article_difficulty", "easy")
                
                if difficulty == "easy":
                    facts = prefetched_data.facts_by_article.get(news_url_id, [])
                    requests = self._build_easy_article_requests(news_url_id, facts=facts)
                else:
                    groups = prefetched_data.topic_groups_by_article.get(news_url_id, [])
                    requests = self._build_hard_article_requests(news_url_id, groups=groups)
                
                for request in requests:
                    handle.write(json.dumps(request) + "\n")
                    total_requests += 1
                
                if requests:
                    total_articles += 1
                    article_ids.append(news_url_id)

        if total_requests == 0:
            raise ValueError("No requests generated - articles may have no facts")

        metadata = {
            "task": task,
            "timestamp": timestamp,
            "model": self.model,
            "is_reasoning_model": self.is_reasoning_model,
            "articles_included": total_articles,
            "requests": total_requests,
            "article_ids": article_ids,
            "limit": limit,
            "max_age_hours": max_age_hours,
        }

        metadata_path = self.output_dir / f"summary_batch_{task}_{timestamp}_metadata.json"
        with metadata_path.open("w") as handle:
            json.dump(metadata, handle, indent=2)

        logger.info(
            "Generated summary batch",
            extra={"requests": total_requests, "articles": total_articles, "task": task},
        )

        return GeneratedBatch(
            file_path=file_path,
            total_requests=total_requests,
            total_articles=total_articles,
            metadata_path=metadata_path,
            metadata=metadata,
        )

    def _fetch_pending_articles(
        self,
        *,
        task: SummaryTask,
        limit: Optional[int] = None,
        max_age_hours: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch articles pending summary generation (newest first).
        
        Articles are ordered by created_at DESC to prioritize the most recent content.
        Default limit is 500 articles if not specified.
        """

        # Default to 500 youngest articles if no limit specified
        effective_limit = limit if limit is not None else 500

        query = (
            self.client.table("news_urls")
            .select("id,article_difficulty,created_at")
            .is_("summary_created_at", "null")
            .not_.is_("knowledge_extracted_at", "null")  # Must have knowledge extracted
        )

        if task == "easy":
            query = query.eq("article_difficulty", "easy")
        elif task == "hard":
            query = query.eq("article_difficulty", "hard")
        # "all" includes both

        # Order by created_at DESC to get youngest/newest articles first
        query = query.order("created_at", desc=True)

        if max_age_hours is not None:
            cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
            query = query.gte("created_at", cutoff.isoformat())

        query = query.limit(effective_limit)

        response = query.execute()
        articles = getattr(response, "data", []) or []
        
        logger.info(
            "Fetched pending articles for summary batch",
            extra={
                "task": task,
                "requested_limit": limit,
                "effective_limit": effective_limit,
                "articles_found": len(articles),
            }
        )
        
        return articles

    def _prefetch_article_data(self, articles: List[Dict[str, Any]]) -> PrefetchedArticleData:
        """Preload facts, topics, and entities for the provided articles."""

        article_ids = [article.get("id") for article in articles if article.get("id")]
        if not article_ids:
            return PrefetchedArticleData(facts_by_article={}, topic_groups_by_article={})

        facts_by_id, facts_by_article = self._fetch_facts_for_articles(article_ids)
        logger.info(
            "Prefetched facts for articles",
            extra={"articles": len(article_ids), "facts": len(facts_by_id)},
        )

        if not facts_by_id:
            return PrefetchedArticleData(
                facts_by_article=facts_by_article,
                topic_groups_by_article={},
            )

        fact_ids = list(facts_by_id.keys())
        topics_by_fact = self._fetch_topics_for_facts(fact_ids)
        scope_by_fact = self._fetch_entities_for_facts(fact_ids)

        topic_groups_by_article = self._group_facts_by_topic_and_scope(
            facts_by_id=facts_by_id,
            topics_by_fact=topics_by_fact,
            scope_by_fact=scope_by_fact,
        )

        logger.info(
            "Built topic groups for articles",
            extra={
                "articles": len(topic_groups_by_article),
                "facts": len(facts_by_id),
                "topics": len(topics_by_fact),
                "entities": len(scope_by_fact),
            },
        )

        return PrefetchedArticleData(
            facts_by_article=facts_by_article,
            topic_groups_by_article=topic_groups_by_article,
        )

    def _chunked_ids(self, values: List[str]) -> Iterable[List[str]]:
        """Yield ID lists in chunks to avoid oversized queries."""

        for idx in range(0, len(values), self.page_size):
            yield values[idx: idx + self.page_size]

    def _fetch_facts_for_articles(
        self,
        article_ids: List[str],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
        """Fetch facts for many articles in batches."""

        facts_by_id: Dict[str, Dict[str, Any]] = {}
        facts_by_article: Dict[str, List[str]] = {article_id: [] for article_id in article_ids}

        for article_chunk in self._chunked_ids(article_ids):
            offset = 0
            while True:
                response = (
                    self.client.table("news_facts")
                    .select("id,news_url_id,fact_text")
                    .in_("news_url_id", article_chunk)
                    .order("id")
                    .range(offset, offset + self.page_size - 1)
                    .execute()
                )
                rows = getattr(response, "data", []) or []

                for row in rows:
                    fact_id = row.get("id")
                    article_id = row.get("news_url_id")
                    fact_text = row.get("fact_text")
                    if not fact_id or not article_id or not isinstance(fact_text, str):
                        continue
                    cleaned_text = fact_text.strip()
                    if not cleaned_text:
                        continue
                    facts_by_id[fact_id] = {
                        "news_url_id": article_id,
                        "fact_text": cleaned_text,
                    }
                    facts_by_article.setdefault(article_id, []).append(cleaned_text)

                if len(rows) < self.page_size:
                    break
                offset += self.page_size

        return facts_by_id, facts_by_article

    def _fetch_topics_for_facts(self, fact_ids: List[str]) -> Dict[str, str]:
        """Fetch topics for all supplied fact IDs with pagination."""

        topics_by_fact: Dict[str, str] = {}

        for fact_chunk in self._chunked_ids(fact_ids):
            offset = 0
            while True:
                response = (
                    self.client.table("news_fact_topics")
                    .select("news_fact_id,canonical_topic,is_primary")
                    .in_("news_fact_id", fact_chunk)
                    .order("news_fact_id")
                    .range(offset, offset + self.page_size - 1)
                    .execute()
                )
                rows = getattr(response, "data", []) or []
                for row in rows:
                    fact_id = row.get("news_fact_id")
                    topic = row.get("canonical_topic") or "general"
                    if topic == "NO_TOPICS_FOUND":
                        topic = "general"
                    if fact_id and (fact_id not in topics_by_fact or row.get("is_primary")):
                        topics_by_fact[fact_id] = topic

                if len(rows) < self.page_size:
                    break
                offset += self.page_size

        return topics_by_fact

    def _fetch_entities_for_facts(self, fact_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch entity scopes for all supplied fact IDs with pagination."""

        scope_by_fact: Dict[str, Dict[str, Any]] = {}

        for fact_chunk in self._chunked_ids(fact_ids):
            offset = 0
            while True:
                response = (
                    self.client.table("news_fact_entities")
                    .select("news_fact_id,entity_type,entity_id,team_abbr,matched_name,is_primary")
                    .in_("news_fact_id", fact_chunk)
                    .order("news_fact_id")
                    .range(offset, offset + self.page_size - 1)
                    .execute()
                )
                rows = getattr(response, "data", []) or []
                for row in rows:
                    fact_id = row.get("news_fact_id")
                    if not fact_id:
                        continue
                    entity_type = row.get("entity_type")
                    if entity_type == "team":
                        scope_by_fact[fact_id] = {
                            "type": "team",
                            "id": row.get("entity_id") or row.get("team_abbr"),
                            "label": row.get("matched_name") or row.get("team_abbr"),
                        }
                    elif entity_type == "player" and fact_id not in scope_by_fact:
                        scope_by_fact[fact_id] = {
                            "type": "player",
                            "id": row.get("entity_id"),
                            "label": row.get("matched_name"),
                            "team": row.get("team_abbr"),
                        }

                if len(rows) < self.page_size:
                    break
                offset += self.page_size

        return scope_by_fact

    def _group_facts_by_topic_and_scope(
        self,
        *,
        facts_by_id: Dict[str, Dict[str, Any]],
        topics_by_fact: Dict[str, str],
        scope_by_fact: Dict[str, Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group facts by topic/scope for each article."""

        groups_by_article: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for fact_id, fact_data in facts_by_id.items():
            article_id = fact_data["news_url_id"]
            fact_text = fact_data["fact_text"]
            topic = topics_by_fact.get(fact_id, "general")
            scope = scope_by_fact.get(fact_id, {})
            scope_key = f"{scope.get('type', 'none')}:{scope.get('id', 'none')}"
            group_key = f"{topic}|{scope_key}"

            article_groups = groups_by_article.setdefault(article_id, {})
            if group_key not in article_groups:
                article_groups[group_key] = {
                    "topic": topic,
                    "scope": scope,
                    "facts": [],
                }
            article_groups[group_key]["facts"].append(fact_text)

        return {article_id: list(group_map.values()) for article_id, group_map in groups_by_article.items()}

    def _fetch_facts_for_article(self, news_url_id: str) -> List[str]:
        """Fetch all fact texts for an article."""

        _, facts_by_article = self._fetch_facts_for_articles([news_url_id])
        return facts_by_article.get(news_url_id, [])

    def _fetch_topic_groups_for_article(self, news_url_id: str) -> List[Dict[str, Any]]:
        """Fetch topic-grouped facts for a hard article."""

        facts_by_id, _ = self._fetch_facts_for_articles([news_url_id])
        if not facts_by_id:
            return []

        fact_ids = list(facts_by_id.keys())
        topics_by_fact = self._fetch_topics_for_facts(fact_ids)
        scope_by_fact = self._fetch_entities_for_facts(fact_ids)

        groups_by_article = self._group_facts_by_topic_and_scope(
            facts_by_id=facts_by_id,
            topics_by_fact=topics_by_fact,
            scope_by_fact=scope_by_fact,
        )

        return groups_by_article.get(news_url_id, [])

    def _build_easy_article_requests(
        self,
        news_url_id: str,
        *,
        facts: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Build batch request(s) for an easy article (single summary)."""

        facts = facts if facts is not None else self._fetch_facts_for_article(news_url_id)
        if not facts:
            logger.warning("No facts for easy article %s", news_url_id)
            return []

        # For large fact sets, we may need to chunk - but let's try all at once first
        # OpenAI models can handle large context
        facts_payload = json.dumps({"facts": facts}, ensure_ascii=False)

        return [self._build_request(
            custom_id=f"easy_{news_url_id}",
            prompt=EASY_SUMMARY_PROMPT,
            user_content=facts_payload,
        )]

    def _build_hard_article_requests(
        self,
        news_url_id: str,
        *,
        groups: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        """Build batch requests for a hard article (multiple topic summaries)."""

        groups = groups if groups is not None else self._fetch_topic_groups_for_article(news_url_id)
        if not groups:
            logger.warning("No topic groups for hard article %s", news_url_id)
            return []

        requests = []
        for idx, group in enumerate(groups):
            topic = group["topic"]
            scope = group.get("scope") or {}
            facts = group["facts"]

            if not facts:
                continue

            context_label = self._build_scope_label(scope)
            prompt = TOPIC_SUMMARY_TEMPLATE.format(topic=topic, context=context_label)
            facts_payload = json.dumps({"facts": facts}, ensure_ascii=False)

            # Encode scope info in custom_id for processing
            # Use pipe delimiter for topic/scope to avoid conflicts with underscores in values
            scope_type = scope.get("type", "none")
            scope_id = scope.get("id", "none")
            scope_label = scope.get("label") or scope_id
            # Format: hard_{news_url_id}_{idx}|{topic}|{scope_type}|{scope_id}|{scope_label}
            custom_id = f"hard_{news_url_id}_{idx}|{topic}|{scope_type}|{scope_id}|{scope_label}"

            requests.append(self._build_request(
                custom_id=custom_id,
                prompt=prompt,
                user_content=facts_payload,
            ))

        return requests

    def _build_request(self, *, custom_id: str, prompt: str, user_content: str) -> Dict:
        """Build a single batch request."""

        if self.is_reasoning_model:
            # Reasoning models: no temperature, no system message, use max_completion_tokens
            return {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": f"{prompt}\n\n{user_content}"}
                    ],
                    "max_completion_tokens": 4000,
                    "reasoning_effort": "low",
                },
            }
        else:
            # Standard models: temperature, system message
            return {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": self.model,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_content}
                    ],
                },
            }

    def _build_scope_label(self, scope: Optional[Dict[str, Any]]) -> str:
        """Create human-readable label for a scope."""

        if not scope:
            return "League-wide"

        label = scope.get("label") or scope.get("id") or "Unknown"
        scope_type = scope.get("type")

        if scope_type == "team":
            return label
        elif scope_type == "player":
            team = scope.get("team")
            if team:
                return f"{label} ({team})"
            return label
        elif scope_type == "game":
            return f"Game: {label}"

        return label
