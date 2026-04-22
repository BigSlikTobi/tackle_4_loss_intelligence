"""Generate OpenAI batch requests for fact extraction."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from src.shared.db.connection import get_supabase_client
from ..db import EphemeralContentReader
from ..facts.prompts import FACT_PROMPT, get_formatted_prompt
from ..extractors.extractor_factory import get_extractor

logger = logging.getLogger(__name__)


@dataclass
class GeneratedBatch:
    """Container describing the generated batch request file."""

    file_path: Path
    total_requests: int
    total_articles: int
    metadata_path: Path
    metadata: Dict[str, Any]


class FactsBatchRequestGenerator:
    """Create JSONL payloads for the OpenAI Batch API for fact extraction.

    Each request contains article content for a single news URL, and the
    response will contain extracted facts.
    
    Example:
        generator = FactsBatchRequestGenerator(model="gpt-5-nano")
        batch = generator.generate(limit=500)
        print(f"Generated {batch.total_requests} requests to {batch.file_path}")
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5-nano",
        output_dir: Optional[Path] = None,
        page_size: int = 100,
        max_workers: int = 10,
        use_ephemeral_content: Optional[bool] = None,
    ) -> None:
        """Initialize request generator.

        Args:
            model: LLM model for fact extraction
            output_dir: Directory for batch files
            page_size: Page size for database queries
            max_workers: Number of parallel workers for content fetching
            use_ephemeral_content: If True, try news_url_content_ephemeral
                before re-fetching from the source. If False, always live-fetch
                (legacy behavior). Defaults to the EPHEMERAL_CONTENT_ENABLED
                env var (off when unset).
        """
        self.client = get_supabase_client()
        self.model = model
        self.output_dir = output_dir or Path("./batch_files")
        self.output_dir.mkdir(exist_ok=True)
        self.page_size = page_size
        self.max_workers = max_workers
        if use_ephemeral_content is None:
            env_flag = os.getenv("EPHEMERAL_CONTENT_ENABLED", "").strip().lower()
            use_ephemeral_content = env_flag in {"1", "true", "yes", "y"}
        self.use_ephemeral_content = bool(use_ephemeral_content)
        self._ephemeral_reader: Optional[EphemeralContentReader] = (
            EphemeralContentReader(self.client) if self.use_ephemeral_content else None
        )
        # Per-generate-call counters; reset in generate().
        self._counter_lock = Lock()
        self._ephemeral_hits = 0
        self._ephemeral_misses = 0
        self._live_fetches = 0

        # Check if this is a reasoning model (gpt-5-nano, o1, o3)
        self.is_reasoning_model = (
            "nano" in model
            or model.startswith("o1")
            or model.startswith("o3")
            or "o1" in model
            or "o3" in model
        )

        logger.info(
            "Initialized FactsBatchRequestGenerator",
            extra={
                "model": model,
                "is_reasoning_model": self.is_reasoning_model,
                "page_size": page_size,
                "max_workers": max_workers,
            },
        )

    def generate(
        self,
        *,
        limit: Optional[int] = None,
        skip_existing: bool = True,
        high_fact_count_threshold: Optional[int] = None,
        include_unextracted: bool = True,
        max_age_hours: Optional[int] = None,
    ) -> GeneratedBatch:
        """Generate a JSONL file for fact extraction batch processing.
        
        Args:
            limit: Maximum number of articles to include
            skip_existing: Skip articles that already have facts
            high_fact_count_threshold: If set, only include articles with facts_count > threshold
                                      (for re-extraction of bloated articles)
            include_unextracted: Include articles without content_extracted_at set.
                                 When True (default), processes any article directly.
                                 When False, only processes pre-validated articles.
            
        Returns:
            GeneratedBatch with file paths and metadata
            
        Raises:
            ValueError: If no eligible articles found
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"facts_batch_{timestamp}.jsonl"
        file_path = self.output_dir / filename

        # Reset per-call counters so metadata reflects only this generate().
        with self._counter_lock:
            self._ephemeral_hits = 0
            self._ephemeral_misses = 0
            self._live_fetches = 0

        # Fetch pending articles
        if high_fact_count_threshold is not None:
            articles = self._fetch_high_fact_count_articles(
                threshold=high_fact_count_threshold,
                limit=limit,
            )
        else:
            articles = self._fetch_pending_articles(
                limit=limit,
                skip_existing=skip_existing,
                include_unextracted=include_unextracted,
                max_age_hours=max_age_hours,
            )

        if not articles:
            raise ValueError("No eligible articles found for batch generation")

        # Deduplicate articles
        seen_ids: set = set()
        unique_articles: List[Dict[str, Any]] = []
        skipped_duplicate = 0
        
        for article in articles:
            news_url_id = article["id"]
            if news_url_id in seen_ids:
                skipped_duplicate += 1
                logger.debug(f"Skipping duplicate article ID: {news_url_id}")
                continue
            seen_ids.add(news_url_id)
            if article.get("url"):
                unique_articles.append(article)

        if skipped_duplicate > 0:
            logger.warning(f"Skipped {skipped_duplicate} duplicate article IDs")

        # Get formatted prompt with current date
        prompt = get_formatted_prompt()

        # Parallel content fetching with overall timeout protection
        CONTENT_FETCH_TIMEOUT = 600  # 10 minutes max for all fetching
        fetched_contents: Dict[str, str] = {}
        failed_fetches = 0

        # Split into heavy (Playwright-required) and light pools. Light URLs
        # parallelize cheaply over HTTP; heavy URLs each spin up Chromium and
        # can OOM a 2-CPU Cloud Function if too many run at once. Capping the
        # heavy pool at 2 keeps memory bounded while letting the light pool
        # use the full `max_workers`.
        from ..extractors.extractor_factory import is_heavy_url

        heavy_articles = [a for a in unique_articles if is_heavy_url(a.get("url", ""))]
        light_articles = [a for a in unique_articles if not is_heavy_url(a.get("url", ""))]
        heavy_workers = min(2, max(1, len(heavy_articles)))

        logger.info(
            "Fetching content for %d articles (%d heavy @ %d workers, %d light @ %d workers, timeout: %ds)...",
            len(unique_articles),
            len(heavy_articles),
            heavy_workers,
            len(light_articles),
            self.max_workers,
            CONTENT_FETCH_TIMEOUT,
        )

        def fetch_article_content(article: Dict[str, Any]) -> Tuple[str, str, bool]:
            """Fetch content for a single article. Returns (id, content, success).

            Read order: ephemeral table (when enabled) -> live extractor.
            Counter increments are thread-safe so the metadata block reflects
            the true hit/miss/fallback distribution for the run.
            """
            news_url_id = article["id"]
            url = article["url"]
            if self._ephemeral_reader is not None:
                try:
                    cached = self._ephemeral_reader.fetch_content(news_url_id)
                except Exception as exc:  # pragma: no cover - defensive
                    cached = None
                    logger.warning(
                        "Ephemeral lookup raised for %s: %s", news_url_id, exc
                    )
                if cached:
                    with self._counter_lock:
                        self._ephemeral_hits += 1
                    return (news_url_id, cached, True)
                with self._counter_lock:
                    self._ephemeral_misses += 1
            try:
                content = self._fetch_content_from_url(url)
                with self._counter_lock:
                    self._live_fetches += 1
                return (news_url_id, content, bool(content and content.strip()))
            except Exception as e:
                logger.warning(f"Failed to fetch {url[:60]}: {e}")
                return (news_url_id, "", False)

        def run_pool(articles: List[Dict[str, Any]], workers: int) -> None:
            nonlocal failed_fetches
            if not articles:
                return
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(fetch_article_content, a): a for a in articles}
                completed = 0
                for future in as_completed(futures, timeout=CONTENT_FETCH_TIMEOUT):
                    completed += 1
                    try:
                        news_url_id, content, success = future.result(timeout=5)
                        if success:
                            fetched_contents[news_url_id] = content
                        else:
                            failed_fetches += 1
                    except Exception as e:
                        logger.warning(f"Failed to get result for article: {e}")
                        failed_fetches += 1
                    if completed % 50 == 0 or completed == len(articles):
                        logger.info(
                            "Content fetch progress: %d/%d (%d successful)",
                            completed,
                            len(articles),
                            len(fetched_contents),
                        )

        run_pool(light_articles, self.max_workers)
        run_pool(heavy_articles, heavy_workers)

        logger.info(f"Content fetching complete: {len(fetched_contents)} successful, {failed_fetches} failed")

        # Write batch file
        total_requests = 0
        article_ids: List[str] = []

        with file_path.open("w") as handle:
            for article in unique_articles:
                news_url_id = article["id"]
                content = fetched_contents.get(news_url_id, "")
                
                if not content:
                    continue

                request = self._build_request(
                    custom_id=f"facts_{news_url_id}",
                    prompt=prompt,
                    article_content=content,
                )

                handle.write(json.dumps(request) + "\n")
                total_requests += 1
                article_ids.append(news_url_id)

        if total_requests == 0:
            raise ValueError("No requests generated - articles may have no content")

        metadata = {
            "timestamp": timestamp,
            "model": self.model,
            "is_reasoning_model": self.is_reasoning_model,
            "articles_included": total_requests,
            "articles_skipped_no_content": failed_fetches,
            "requests": total_requests,
            "article_ids": article_ids,
            "limit": limit,
            "skip_existing": skip_existing,
            "include_unextracted": include_unextracted,
            "max_workers": self.max_workers,
            "max_age_hours": max_age_hours,
            "ephemeral_enabled": self.use_ephemeral_content,
            "ephemeral_hits": self._ephemeral_hits,
            "ephemeral_misses": self._ephemeral_misses,
            "live_fetches": self._live_fetches,
        }

        metadata_path = self.output_dir / f"facts_batch_{timestamp}_metadata.json"
        with metadata_path.open("w") as handle:
            json.dump(metadata, handle, indent=2)

        logger.info(
            "Generated facts batch",
            extra={
                "requests": total_requests,
                "articles": total_requests,
                "skipped_no_content": failed_fetches,
            },
        )

        return GeneratedBatch(
            file_path=file_path,
            total_requests=total_requests,
            total_articles=total_requests,
            metadata_path=metadata_path,
            metadata=metadata,
        )

    def _fetch_pending_articles(
        self,
        *,
        limit: Optional[int] = None,
        skip_existing: bool = True,
        include_unextracted: bool = True,
        max_age_hours: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch articles pending fact extraction (newest first).

        Content is fetched from URLs at generation time (not stored for legal reasons).
        Failed URLs are automatically skipped during content fetching.
        
        Args:
            limit: Maximum articles to fetch
            skip_existing: Skip articles that already have facts
            include_unextracted: Include articles without content_extracted_at set
                                 (enables direct processing without pre-validation)
            
        Returns:
            List of article dicts with id and url
        """
        effective_limit = limit if limit is not None else 500

        if effective_limit <= 1:
            articles = self._query_pending_articles(
                limit=effective_limit,
                include_unextracted=include_unextracted,
                max_age_hours=max_age_hours,
                newest_first=False,
            )
        else:
            newest_limit = max(1, effective_limit // 2)
            oldest_limit = effective_limit - newest_limit

            newest = self._query_pending_articles(
                limit=newest_limit,
                include_unextracted=include_unextracted,
                max_age_hours=max_age_hours,
                newest_first=True,
            )
            oldest = self._query_pending_articles(
                limit=oldest_limit,
                include_unextracted=include_unextracted,
                max_age_hours=max_age_hours,
                newest_first=False,
            )
            articles = self._interleave_pending_articles(newest=newest, oldest=oldest, limit=effective_limit)

        logger.info(
            "Fetched pending articles for facts batch",
            extra={
                "requested_limit": limit,
                "effective_limit": effective_limit,
                "include_unextracted": include_unextracted,
                "articles_found": len(articles),
                "selection_strategy": "balanced-newest-oldest",
            },
        )

        return articles

    def _query_pending_articles(
        self,
        *,
        limit: int,
        include_unextracted: bool,
        max_age_hours: Optional[int],
        newest_first: bool,
    ) -> List[Dict[str, Any]]:
        """Fetch one side of the pending queue.

        Pages through Supabase in `page_size` chunks to respect the 1000-row
        default cap; stops once `limit` rows are collected or a partial page
        signals the end of the result set.
        """
        cutoff_iso: Optional[str] = None
        if max_age_hours is not None:
            cutoff_iso = (
                datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            ).isoformat()

        def _new_query():
            query = (
                self.client.table("news_urls")
                .select("id,url,created_at")
                .is_("facts_extracted_at", "null")
                .order("created_at", desc=newest_first)
            )
            if not include_unextracted:
                query = query.not_.is_("content_extracted_at", "null")
            if cutoff_iso is not None:
                query = query.gte("created_at", cutoff_iso)
            return query

        collected: List[Dict[str, Any]] = []
        offset = 0
        while len(collected) < limit:
            remaining = limit - len(collected)
            fetch_size = min(self.page_size, remaining)
            response = (
                _new_query()
                .range(offset, offset + fetch_size - 1)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            if not rows:
                break
            collected.extend(rows)
            if len(rows) < fetch_size:
                break
            offset += fetch_size
        return collected

    def _interleave_pending_articles(
        self,
        *,
        newest: List[Dict[str, Any]],
        oldest: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Mix fresh and old backlog items so neither side starves."""
        selected: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        for fresh_article, backlog_article in zip_longest(newest, oldest):
            for article in (fresh_article, backlog_article):
                if not article:
                    continue
                article_id = article.get("id")
                if not article_id or article_id in seen_ids:
                    continue
                seen_ids.add(article_id)
                selected.append(article)
                if len(selected) >= limit:
                    return selected

        return selected

    def _fetch_high_fact_count_articles(
        self,
        *,
        threshold: int,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch articles with high fact counts for re-extraction.
        
        Note: This only fetches id, url, and facts_count. Content must be
        re-fetched from the URL since we don't store extracted content.
        
        Args:
            threshold: Minimum facts_count to include (articles with > threshold)
            limit: Maximum articles to fetch
            
        Returns:
            List of article dicts with id, url, and facts_count
        """
        all_articles: List[Dict[str, Any]] = []
        page_size = self.page_size
        offset = 0
        effective_limit = limit if limit is not None else 10000

        while len(all_articles) < effective_limit:
            remaining = effective_limit - len(all_articles)
            fetch_size = min(page_size, remaining)

            response = (
                self.client.table("news_urls")
                .select("id,url,facts_count")
                .gt("facts_count", threshold)
                .not_.is_("content_extracted_at", "null")  # Must have been extracted before
                .order("facts_count", desc=True)  # Highest counts first
                .range(offset, offset + fetch_size - 1)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            if not rows:
                break
            all_articles.extend(rows)
            if len(rows) < fetch_size:
                break
            offset += fetch_size

        logger.info(
            "Fetched high fact count articles for re-extraction batch",
            extra={
                "threshold": threshold,
                "requested_limit": limit,
                "articles_found": len(all_articles),
                "total_old_facts": sum(a.get("facts_count", 0) for a in all_articles),
            },
        )

        return all_articles

    def _fetch_content_from_url(self, url: str, timeout: int = 45) -> str:
        """Fetch article content from URL using full escalation strategy.
        
        Escalation order:
        1. Check for AMP version of the URL first
        2. Try light extractor (for simple pages)
        3. Escalate to Playwright for heavy hosts or insufficient content
        4. Retry with Playwright on 403 errors
        
        Args:
            url: Article URL
            timeout: Request timeout in seconds
            
        Returns:
            Extracted article content, or empty string on failure
        """
        from ..utils.amp_detector import probe_for_amp
        
        try:
            # Step 1: Probe for AMP version first (faster, cleaner markup)
            amp_url, is_amp = probe_for_amp(url, timeout=8.0, logger=logger)
            if is_amp and amp_url != url:
                logger.debug(f"Using AMP version: {amp_url}")
            
            target_url = amp_url if is_amp else url
            
            # Step 2: Get appropriate extractor (auto-selects Playwright for heavy hosts)
            extractor = get_extractor(target_url)
            result = extractor.extract(target_url, timeout=timeout)
            
            # Step 3: Check if we have content
            if result.paragraphs:
                content = "\n\n".join(result.paragraphs)
                if content.strip():
                    return content.strip()
            
            # Step 4: Escalate to Playwright if light extractor failed
            if result.error or not result.paragraphs:
                error_msg = result.error or "No paragraphs extracted"
                
                # Check if it's a 403 or insufficient content error
                needs_playwright = (
                    "403" in str(error_msg) or
                    "Insufficient" in str(error_msg) or
                    not result.paragraphs
                )
                
                if needs_playwright:
                    logger.debug(f"Escalating to Playwright for {url}: {error_msg}")
                    extractor = get_extractor(url, force_playwright=True)
                    result = extractor.extract(url, timeout=timeout)
                    
                    if result.paragraphs:
                        content = "\n\n".join(result.paragraphs)
                        if content.strip():
                            return content.strip()
            
            # Final check - log what went wrong
            if result.error:
                logger.warning(f"Extraction error for {url}: {result.error}")
            else:
                logger.warning(f"No content extracted for {url}")
            
            return ""
            
        except Exception as e:
            logger.warning(f"Failed to fetch content from {url}: {e}")
            return ""

    def _build_request(
        self,
        *,
        custom_id: str,
        prompt: str,
        article_content: str,
    ) -> Dict[str, Any]:
        """Build a single batch request.
        
        Args:
            custom_id: Unique ID for this request (facts_{news_url_id})
            prompt: Fact extraction prompt
            article_content: Article text to extract facts from
            
        Returns:
            Batch API request dict
        """
        if self.is_reasoning_model:
            # Reasoning models: no temperature, no system message, use max_completion_tokens
            return {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"{prompt}\n\nArticle:\n{article_content}",
                        }
                    ],
                    "max_completion_tokens": 16000,
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
                    "temperature": 0,
                    "max_completion_tokens": 16000,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Article:\n{article_content}"},
                    ],
                },
            }
