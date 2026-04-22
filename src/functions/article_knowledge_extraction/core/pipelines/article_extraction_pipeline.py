"""End-to-end in-process pipeline: article text in, JobResult out.

Used by both the worker (job_runner) and the local CLI. Accepts injected
extractors/resolver for testability.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from ..config import ArticleInput, ExtractionOptions, LLMConfig, SupabaseConfig
from ..contracts.job import (
    ExtractedEntityOut,
    ExtractedTopicOut,
    JobResult,
)
from ..db.job_store import build_client
from ..extraction.article_entity_extractor import ArticleEntityExtractor
from ..extraction.article_topic_extractor import ArticleTopicExtractor
from ..resolution.resolver_adapter import ArticleEntityResolver

logger = logging.getLogger(__name__)


@dataclass
class PipelineDeps:
    topic_extractor: ArticleTopicExtractor
    entity_extractor: ArticleEntityExtractor
    resolver: Optional[ArticleEntityResolver]


class ArticleExtractionPipeline:
    def __init__(self, deps: PipelineDeps):
        self._deps = deps

    @classmethod
    def from_llm_config(
        cls,
        llm: LLMConfig,
        options: ExtractionOptions,
        supabase: Optional[SupabaseConfig] = None,
    ) -> "ArticleExtractionPipeline":
        topic = ArticleTopicExtractor(
            api_key=llm.api_key,
            model=llm.model,
            timeout=llm.timeout_seconds,
            max_retries=llm.max_retries,
        )
        entity = ArticleEntityExtractor(
            api_key=llm.api_key,
            model=llm.model,
            timeout=llm.timeout_seconds,
            max_retries=llm.max_retries,
        )
        resolver = None
        if options.resolve_entities:
            supabase_client = build_client(supabase) if supabase is not None else None
            resolver = ArticleEntityResolver(
                confidence_threshold=options.confidence_threshold,
                supabase_client=supabase_client,
            )
        return cls(PipelineDeps(topic_extractor=topic, entity_extractor=entity, resolver=resolver))

    def run(
        self,
        article: ArticleInput,
        options: ExtractionOptions,
    ) -> JobResult:
        logger.info(
            "Running article extraction (article_id=%s, length=%d)",
            article.article_id,
            len(article.text),
        )

        t0 = time.time()
        topics_raw = self._deps.topic_extractor.extract(article.text, options.max_topics)
        topic_ms = int((time.time() - t0) * 1000)

        t1 = time.time()
        entities_raw = self._deps.entity_extractor.extract(article.text, options.max_entities)
        entity_ms = int((time.time() - t1) * 1000)

        resolution_ms = 0
        if self._deps.resolver is not None:
            t2 = time.time()
            resolved, unresolved = self._deps.resolver.resolve_all(entities_raw)
            resolution_ms = int((time.time() - t2) * 1000)
            entity_out = [
                ExtractedEntityOut(
                    entity_type=r.entity_type,
                    mention_text=r.mention_text,
                    confidence=r.confidence,
                    rank=r.rank,
                    entity_id=r.entity_id,
                    matched_name=r.matched_name,
                    position=r.position,
                    team_abbr=r.team_abbr,
                    team_name=r.team_name,
                )
                for r in resolved
            ]
            unresolved_out = [
                ExtractedEntityOut(
                    entity_type=e.entity_type,
                    mention_text=e.mention_text,
                    confidence=e.confidence,
                    rank=e.rank,
                    position=e.position,
                    team_abbr=e.team_abbr,
                    team_name=e.team_name,
                )
                for e in unresolved
            ]
        else:
            entity_out = [
                ExtractedEntityOut(
                    entity_type=e.entity_type,
                    mention_text=e.mention_text,
                    confidence=e.confidence,
                    rank=e.rank,
                    position=e.position,
                    team_abbr=e.team_abbr,
                    team_name=e.team_name,
                )
                for e in entities_raw
            ]
            unresolved_out = []

        topic_out = [
            ExtractedTopicOut(topic=t.topic, confidence=t.confidence, rank=t.rank)
            for t in topics_raw
        ]

        total_ms = int((time.time() - t0) * 1000)
        return JobResult(
            article_id=article.article_id,
            topics=topic_out,
            entities=entity_out,
            unresolved_entities=unresolved_out,
            metrics={
                "topic_extraction_ms": topic_ms,
                "entity_extraction_ms": entity_ms,
                "resolution_ms": resolution_ms,
                "total_ms": total_ms,
                "model": self._deps.topic_extractor.model,
                "topics_count": len(topic_out),
                "entities_count": len(entity_out),
                "unresolved_count": len(unresolved_out),
            },
        )
