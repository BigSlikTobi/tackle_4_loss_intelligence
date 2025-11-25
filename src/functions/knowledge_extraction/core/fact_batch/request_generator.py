"""Generate OpenAI batch requests for fact-level knowledge creation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional

from ..extraction.topic_extractor import TOPIC_CATEGORIES
from ..db.fact_reader import NewsFactReader

logger = logging.getLogger(__name__)

KnowledgeTask = Literal["topics", "entities"]


@dataclass
class GeneratedBatch:
    """Container describing the generated batch request file."""

    file_path: Path
    total_requests: int
    total_facts: int
    metadata_path: Path
    metadata: Dict


class FactBatchRequestGenerator:
    """Create jsonl payloads for the OpenAI batch API.

    Each request aggregates up to `chunk_size` news facts so the model
    can return knowledge lists for multiple facts in a single call.
    """

    def __init__(
        self,
        *,
        reader: Optional[NewsFactReader] = None,
        model: str = "gpt-4.1-nano-2025-04-14",
        temperature: float = 0.1,
        chunk_size: int = 25,
        output_dir: Optional[Path] = None,
        page_size: int = 200,
        skip_errors: bool = False,
        pending_urls_only: bool = True,
    ) -> None:
        self.reader = reader or NewsFactReader()
        self.model = model
        self.temperature = temperature
        self.chunk_size = chunk_size
        self.output_dir = output_dir or Path("./batch_files")
        self.output_dir.mkdir(exist_ok=True)
        self.page_size = page_size
        self.skip_errors = skip_errors
        self.pending_urls_only = pending_urls_only

        logger.info(
            "Initialized FactBatchRequestGenerator",
            extra={
                "model": model,
                "temperature": temperature,
                "chunk_size": chunk_size,
                "page_size": page_size,
                "skip_errors": skip_errors,
                "pending_urls_only": pending_urls_only,
            },
        )

    def generate(
        self,
        *,
        task: KnowledgeTask,
        limit: Optional[int] = None,
    ) -> GeneratedBatch:
        """Generate a jsonl file for the given knowledge task."""

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"fact_knowledge_{task}_batch_{timestamp}.jsonl"
        file_path = self.output_dir / filename

        facts_iter = self.reader.stream_facts(
            limit=limit,
            page_size=self.page_size,
            require_topics=task == "topics",
            require_entities=task == "entities",
            skip_on_error=self.skip_errors,
            pending_urls_only=self.pending_urls_only,
        )

        total_requests = 0
        total_facts = 0

        with file_path.open("w") as handle:
            for index, chunk in enumerate(self._chunk_facts(facts_iter), start=1):
                request = self._build_request(task=task, chunk=chunk, index=index)
                handle.write(json.dumps(request) + "\n")
                total_requests += 1
                total_facts += len(chunk)

        if total_requests == 0:
            raise ValueError("No eligible facts found for batch generation")

        metadata = {
            "task": task,
            "timestamp": timestamp,
            "model": self.model,
            "temperature": self.temperature,
            "chunk_size": self.chunk_size,
            "facts_included": total_facts,
            "requests": total_requests,
            "limit": limit,
        }

        metadata_path = self.output_dir / f"fact_knowledge_{task}_batch_{timestamp}_metadata.json"
        with metadata_path.open("w") as handle:
            json.dump(metadata, handle, indent=2)

        logger.info(
            "Generated fact knowledge batch",
            extra={"requests": total_requests, "facts": total_facts, "task": task},
        )

        return GeneratedBatch(
            file_path=file_path,
            total_requests=total_requests,
            total_facts=total_facts,
            metadata_path=metadata_path,
            metadata=metadata,
        )

    def _build_request(self, *, task: KnowledgeTask, chunk: List[Dict], index: int) -> Dict:
        prompt = self._build_prompt(task=task, chunk=chunk)

        return {
            "custom_id": f"{task}_{index}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": self.model,
                "temperature": self.temperature,
                "messages": prompt,
            },
        }

    def _build_prompt(self, *, task: KnowledgeTask, chunk: List[Dict]) -> List[Dict]:
        facts_payload = [
            {"news_fact_id": row["id"], "fact_text": row["fact_text"]}
            for row in chunk
        ]

        if task == "topics":
            instruction = (
                "Return ONLY a JSON array. Each element must contain `news_fact_id` and a `topics` array. "
                "For each fact, select 1-3 items from the allowed topic categories list only. "
                "Do not return player names, team names, stats, or prose—only the closest matching categories."
            )
            task_details = {
                "task": "topics",
                "facts": facts_payload,
                "allowed_topics": TOPIC_CATEGORIES,
                "output_format": [
                    {
                        "news_fact_id": "<uuid>",
                        "topics": [
                            {
                                "topic": "<one of allowed topic categories>",
                                "confidence": 0.0,
                                "rank": 1,
                            }
                        ],
                    }
                ],
            }
        else:
            instruction = (
                "Return ONLY a JSON array. Each element must contain `news_fact_id` and an `entities` array. "
                "Entities must be limited to one of: player, team, game. Exclude topics, stats, odds, or dates. "
                "Use canonical player names and team names only (no prefixes like 'player:', 'team:', 'players:', 'teams:'), include team_abbr when known for disambiguation."
            )
            task_details = {
                "task": "entities",
                "facts": facts_payload,
                "allowed_entity_types": ["player", "team", "game"],
                "output_format": [
                    {
                        "news_fact_id": "<uuid>",
                        "entities": [
                            {
                                "entity_type": "player|team|game",
                                "mention_text": "<name only>",
                            }
                        ],
                    }
                ],
            }

            # Tighten instruction to reduce token usage
            instruction = (
                "Return ONLY a JSON array. Each element must contain `news_fact_id` and an `entities` array. "
                "Entities must be limited to: player, team, or game. Exclude topics, stats, odds, dates, commentary. "
                "For each entity include ONLY `entity_type` and `mention_text` fields (no confidence, rank, team_abbr, etc.). "
                "Use canonical player names and team names only; no prefixes like 'player:' or 'team:'."
            )

        user_content = json.dumps(task_details, ensure_ascii=False)

        return [
            {
                "role": "system",
                "content": (
                    "You extract knowledge for NFL news facts. "
                    "Respond strictly with JSON and preserve the provided fact order."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "text", "text": user_content},
                ],
            },
        ]

    def _chunk_facts(self, facts: Iterable[Dict]) -> Iterable[List[Dict]]:
        chunk: List[Dict] = []
        for fact in facts:
            chunk.append(fact)
            if len(chunk) == self.chunk_size:
                yield chunk
                chunk = []

        if chunk:
            yield chunk
