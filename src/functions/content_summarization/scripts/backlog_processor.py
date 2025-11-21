"""Backlog processor for high-throughput content pipeline processing.

This tool is optimized for one-time bulk processing of large article backlogs (1000+ articles).
For small batch corrections (10-100 articles), use content_pipeline_cli.py.
For real-time processing (1-10 articles), use url_extraction Cloud Function with enable_fact_extraction.

Features:
- Concurrent processing with ThreadPoolExecutor (15 workers default)
- Adaptive memory monitoring with automatic worker scaling
- Per-stage checkpoint system with resume support
- Rate limiting with exponential backoff (30 req/min for Gemini)
- Lazy-initialized browser pool (max 5 Playwright instances)
- Batch embedding generation (100 texts per API call)
- Bulk database operations
- Comprehensive progress tracking and failure recovery
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import threading
import time
import traceback
from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import psutil
import requests

# Ensure repository root is importable when executing from the scripts directory
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.url_content_extraction.core.extractors.extractor_factory import (
    get_extractor,
)
from src.functions.content_summarization.scripts.content_pipeline_cli import (
    extract_facts,
    filter_story_facts,
    remove_non_story_facts_from_db,
    store_facts,
    fetch_existing_fact_ids,
    create_fact_pooled_embedding,
    fact_stage_completed,
    get_article_difficulty,
    handle_easy_article_summary,
    handle_hard_article_summary,
    summary_stage_completed,
    fetch_article_content as fetch_article_content_service,
)

logger = logging.getLogger(__name__)

DEFAULT_FACT_MODEL = "gemma-3n-e4b-it"
DEFAULT_SUMMARY_MODEL = "gemma-3n-e4b-it"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
MAX_FAILURE_ATTEMPTS_PER_URL = 3
MAX_EDGE_FETCH_LIMIT = 20_000


@dataclass
class PipelineConfig:
    """Runtime configuration for the backlog processor."""

    edge_function_base_url: str
    content_extraction_url: Optional[str]
    llm_api_url: str
    llm_api_key: str
    embedding_api_url: str
    embedding_api_key: str
    fact_llm_model: str = DEFAULT_FACT_MODEL
    summary_llm_model: str = DEFAULT_SUMMARY_MODEL
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL
    batch_limit: int = 100
    llm_timeout_seconds: int = 60
    embedding_timeout_seconds: int = 30
    content_timeout_seconds: int = 45


def build_config(env: Dict[str, str], *, fact_llm_override: Optional[str] = None) -> PipelineConfig:
    """Create pipeline configuration from environment variables."""

    supabase_url = env.get("SUPABASE_URL")
    if not supabase_url:
        raise ValueError("Missing required environment variable: SUPABASE_URL")

    edge_function_base_url = f"{supabase_url.rstrip('/')}/functions/v1"

    content_extraction_url = env.get("CONTENT_EXTRACTION_URL")
    if content_extraction_url:
        content_extraction_url = content_extraction_url.strip() or None

    gemini_key = env.get("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("Missing required environment variable: GEMINI_API_KEY")

    openai_key = env.get("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("Missing required environment variable: OPENAI_API_KEY")

    llm_api_url = "https://generativelanguage.googleapis.com/v1beta/models"
    embedding_api_url = "https://api.openai.com/v1/embeddings"

    batch_limit = int(env.get("BATCH_LIMIT", "100"))
    llm_timeout = int(env.get("LLM_TIMEOUT_SECONDS", "60"))
    embedding_timeout = int(env.get("EMBEDDING_TIMEOUT_SECONDS", "30"))
    content_timeout = int(env.get("CONTENT_TIMEOUT_SECONDS", "45"))

    fact_llm_model = fact_llm_override or env.get("FACT_LLM_MODEL", DEFAULT_FACT_MODEL)

    return PipelineConfig(
        edge_function_base_url=edge_function_base_url,
        content_extraction_url=content_extraction_url if content_extraction_url else None,
        llm_api_url=llm_api_url,
        llm_api_key=gemini_key,
        embedding_api_url=embedding_api_url,
        embedding_api_key=openai_key,
        fact_llm_model=fact_llm_model,
        summary_llm_model=env.get("SUMMARY_LLM_MODEL", DEFAULT_SUMMARY_MODEL),
        embedding_model_name=env.get("OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        batch_limit=batch_limit,
        llm_timeout_seconds=llm_timeout,
        embedding_timeout_seconds=embedding_timeout,
        content_timeout_seconds=content_timeout,
    )


class RateLimiter:
    """Simple sliding-window rate limiter with backoff tracking."""

    def __init__(self, rate_per_minute: int):
        self.rate_per_minute = rate_per_minute
        self._lock = threading.Lock()
        self._request_times: deque[float] = deque()
        self._rate_limit_hits = 0
        self._total_requests = 0

    def acquire(self) -> None:
        """Block until a slot within the per-minute window is available."""
        wait_time = 0.0
        with self._lock:
            now = time.time()
            window = 60.0
            while self._request_times and now - self._request_times[0] >= window:
                self._request_times.popleft()

            if len(self._request_times) >= self.rate_per_minute:
                wait_time = window - (now - self._request_times[0])

        if wait_time > 0:
            time.sleep(wait_time)

        with self._lock:
            self._request_times.append(time.time())
            self._total_requests += 1

    def handle_429(self, attempt: int) -> float:
        """Record a rate-limit response and return exponential backoff delay."""
        with self._lock:
            self._rate_limit_hits += 1
        return min(30.0, 2 ** attempt)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            window = 60.0
            now = time.time()
            while self._request_times and now - self._request_times[0] >= window:
                self._request_times.popleft()

            return {
                "rate_per_minute": self.rate_per_minute,
                "requests_in_window": len(self._request_times),
                "total_requests": self._total_requests,
                "rate_limit_hits": self._rate_limit_hits,
                "hit_rate": (
                    (self._rate_limit_hits / self._total_requests * 100)
                    if self._total_requests
                    else 0.0
                ),
            }


class MemoryMonitor(threading.Thread):
    """Watches system memory usage and trims browser pool under pressure."""

    def __init__(self, max_percent: int = 80, check_interval: int = 5):
        super().__init__(daemon=True)
        self.max_percent = max_percent
        self.check_interval = check_interval
        self.running = False
        self.peak_memory_percent = 0.0
        self.browser_pool: Optional[BrowserPool] = None

    def set_browser_pool(self, browser_pool: "BrowserPool") -> None:
        self.browser_pool = browser_pool

    def run(self) -> None:
        self.running = True
        logger.info(
            "Memory monitor started",
            {"max_percent": self.max_percent, "check_interval": self.check_interval},
        )

        while self.running:
            try:
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                self.peak_memory_percent = max(self.peak_memory_percent, memory_percent)

                if memory_percent > self.max_percent:
                    logger.warning(
                        "High memory usage detected: %.1f%% (Limit: %s%%) | Used: %.1fGB / %.1fGB",
                        memory_percent,
                        self.max_percent,
                        memory.used / (1024 ** 3),
                        memory.total / (1024 ** 3),
                    )
                    self._close_idle_browsers()

                for _ in range(self.check_interval):
                    if not self.running:
                        break
                    time.sleep(1)
            except Exception as exc:
                logger.error("Memory monitor error: %s", exc)
                time.sleep(1)

    def _close_idle_browsers(self) -> None:
        if self.browser_pool:
            logger.info("Closing idle browsers due to memory pressure")
            self.browser_pool.close_idle_browsers(keep=0)

    def stop(self) -> None:
        self.running = False

    def get_stats(self) -> Dict[str, float]:
        memory = psutil.virtual_memory()
        return {
            "peak_memory_percent": self.peak_memory_percent,
            "current_memory_percent": memory.percent,
            "memory_used_gb": memory.used / (1024 ** 3),
            "memory_total_gb": memory.total / (1024 ** 3),
        }


class BrowserPool:
    """Thread-safe pool of Playwright browsers with lazy initialization."""

    def __init__(self, max_browsers: int = 5):
        self.max_browsers = max_browsers
        self.browsers: Queue = Queue(maxsize=max_browsers)
        self.initialized = 0
        self.lock = threading.Lock()
        self.closed = False
        logger.info("Browser pool created", {"max": max_browsers})

    def acquire(self):
        if self.closed:
            raise RuntimeError("Browser pool is closed")

        try:
            browser = self.browsers.get(block=False)
            logger.debug("Reused existing browser from pool")
            return browser
        except Empty:
            pass

        with self.lock:
            if self.initialized < self.max_browsers:
                self.initialized += 1
                logger.info(
                    "Creating new browser instance (%s/%s)",
                    self.initialized,
                    self.max_browsers,
                )
                return "BROWSER_TOKEN"

        logger.debug("Waiting for available browser from pool")
        return self.browsers.get(block=True)

    def release(self, browser) -> None:
        if self.closed or browser is None:
            return
        try:
            self.browsers.put(browser, block=False)
            logger.debug("Released browser back to pool")
        except Exception as exc:
            logger.warning("Failed to release browser to pool: %s", exc)

    def close_idle_browsers(self, keep: int) -> None:
        with self.lock:
            closed_count = 0
            browsers_to_keep = []

            while not self.browsers.empty():
                try:
                    browser = self.browsers.get(block=False)
                    if len(browsers_to_keep) < keep:
                        browsers_to_keep.append(browser)
                    else:
                        try:
                            if hasattr(browser, "close"):
                                browser.close()
                            closed_count += 1
                        except Exception as exc:
                            logger.warning("Error closing browser: %s", exc)
                except Empty:
                    break

            for browser in browsers_to_keep:
                try:
                    self.browsers.put(browser, block=False)
                except Exception:
                    pass

            self.initialized = len(browsers_to_keep)
            if closed_count:
                logger.info("Closed %s idle browsers (keeping %s)", closed_count, keep)

    def shutdown(self) -> None:
        with self.lock:
            self.closed = True
            closed_count = 0

            while not self.browsers.empty():
                try:
                    browser = self.browsers.get(block=False)
                    if hasattr(browser, "close"):
                        try:
                            browser.close()
                        except Exception as exc:
                            logger.warning("Error closing browser: %s", exc)
                    closed_count += 1
                except Empty:
                    break
                except Exception as exc:
                    logger.warning("Error during browser shutdown: %s", exc)

            logger.info("Browser pool shutdown complete", {"closed": closed_count})

    def get_stats(self) -> Dict[str, int]:
        return {
            "max_browsers": self.max_browsers,
            "initialized": self.initialized,
            "available": self.browsers.qsize(),
            "in_use": self.initialized - self.browsers.qsize(),
        }


# ============================================================================
# CHECKPOINT MANAGER WITH PER-STAGE TRACKING
# ============================================================================

class CheckpointManager:
    """Manages per-article, per-stage checkpoint with atomic writes and validation."""
    
    CHECKPOINT_VERSION = "1.0"
    STAGES = ["content", "facts", "knowledge", "summary"]
    
    def __init__(self, filepath: str):
        """Initialize checkpoint manager.
        
        Args:
            filepath: Path to checkpoint JSON file
        """
        self.filepath = Path(filepath)
        self.data: Dict[str, Any] = {
            "version": self.CHECKPOINT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "articles": {}
        }
        self.lock = threading.Lock()
        self._load()
    
    def _load(self) -> None:
        """Load checkpoint from file if exists."""
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r') as f:
                    loaded = json.load(f)
                    if loaded.get("version") == self.CHECKPOINT_VERSION:
                        self.data = loaded
                        logger.info(f"Loaded checkpoint from {self.filepath}", {
                            "articles": len(self.data.get("articles", {})),
                            "created_at": self.data.get("created_at"),
                        })
                    else:
                        logger.warning(f"Checkpoint version mismatch, starting fresh")
            except Exception as e:
                logger.error(f"Failed to load checkpoint: {e}")
    
    def is_stage_complete(self, article_id: str, stage: str) -> bool:
        """Check if a stage is complete for an article.
        
        Args:
            article_id: Article ID
            stage: Stage name
            
        Returns:
            True if stage is complete
        """
        with self.lock:
            article = self.data["articles"].get(article_id, {})
            return article.get(stage) is not None
    
    def mark_stage_complete(self, article_id: str, stage: str) -> None:
        """Mark a stage as complete for an article.
        
        Args:
            article_id: Article ID
            stage: Stage name
        """
        with self.lock:
            if article_id not in self.data["articles"]:
                self.data["articles"][article_id] = {s: None for s in self.STAGES}
            
            self.data["articles"][article_id][stage] = datetime.now(timezone.utc).isoformat()
            self.data["last_updated"] = datetime.now(timezone.utc).isoformat()
    
    def get_incomplete_articles(self, stage: str, candidate_ids: List[str]) -> List[str]:
        """Get list of article IDs that haven't completed a stage.
        
        Args:
            stage: Stage name
            candidate_ids: List of candidate article IDs to check
            
        Returns:
            List of article IDs that haven't completed the stage
        """
        with self.lock:
            return [
                article_id for article_id in candidate_ids
                if not self.is_stage_complete(article_id, stage)
            ]
    
    def flush(self) -> None:
        """Atomically write checkpoint to disk."""
        with self.lock:
            try:
                # Write to temp file first
                temp_path = self.filepath.with_suffix('.tmp')
                with open(temp_path, 'w') as f:
                    json.dump(self.data, f, indent=2)
                
                # Atomic rename
                temp_path.replace(self.filepath)
                logger.debug(f"Checkpoint flushed to {self.filepath}")
            except Exception as e:
                logger.error(f"Failed to flush checkpoint: {e}")
    
    def validate_integrity(self, client, sample_rate: float = 0.1) -> dict:
        """Validate checkpoint integrity by sampling database.
        
        Args:
            client: Supabase client
            sample_rate: Percentage of articles to validate (0.0-1.0)
            
        Returns:
            Validation results dict
        """
        with self.lock:
            articles = list(self.data["articles"].items())
        
        if not articles:
            return {"validated": 0, "invalid": [], "valid_rate": 100.0}
        
        sample_size = max(1, int(len(articles) * sample_rate))
        sample = random.sample(articles, sample_size)
        
        invalid = []
        
        for article_id, stages in sample:
            # Check facts stage
            if stages.get("facts"):
                response = client.table("news_facts").select("id").eq(
                    "news_url_id", article_id
                ).limit(1).execute()
                if not getattr(response, "data", []):
                    invalid.append(f"{article_id}:facts")
            
            # Check knowledge stage
            if stages.get("knowledge"):
                response = client.table("news_fact_entities").select("id").eq(
                    "news_url_id", article_id
                ).limit(1).execute()
                if not getattr(response, "data", []):
                    invalid.append(f"{article_id}:knowledge")
            
            # Check summary stage
            if stages.get("summary"):
                difficulty = get_article_difficulty(client, article_id).get("article_difficulty")
                if difficulty == "hard":
                    response = client.table("topic_summaries").select("id").eq(
                        "news_url_id", article_id
                    ).limit(1).execute()
                else:
                    response = client.table("context_summaries").select("id").eq(
                        "news_url_id", article_id
                    ).limit(1).execute()
                if not getattr(response, "data", []):
                    invalid.append(f"{article_id}:summary")
        
        valid_rate = ((sample_size - len(invalid)) / sample_size * 100) if sample_size > 0 else 100.0
        
        return {
            "validated": sample_size,
            "invalid": invalid,
            "valid_rate": valid_rate,
        }
    
    def archive(self, timestamp: str) -> Path:
        """Create timestamped backup of checkpoint.
        
        Args:
            timestamp: Timestamp string for archive filename
            
        Returns:
            Path to archive file
        """
        if not self.filepath.exists():
            return None
        
        archive_path = self.filepath.with_name(
            f"{self.filepath.stem}_{timestamp}{self.filepath.suffix}"
        )
        
        try:
            import shutil
            shutil.copy2(self.filepath, archive_path)
            logger.info(f"Checkpoint archived to {archive_path}")
            return archive_path
        except Exception as e:
            logger.error(f"Failed to archive checkpoint: {e}")
            return None


# ============================================================================
# PROGRESS TRACKER
# ============================================================================

class ProgressTracker:
    """Tracks processing progress and calculates metrics."""
    
    def __init__(self, total_articles: int, stage: str):
        """Initialize progress tracker.
        
        Args:
            total_articles: Total number of articles to process
            stage: Current stage name
        """
        self.total_articles = total_articles
        self.stage = stage
        self.start_time = time.time()
        self.processed_count = 0
        self.error_count = 0
        self.lock = threading.Lock()
        self.last_log_time = self.start_time
        self.last_log_count = 0
    
    def increment(self, success: bool = True) -> None:
        """Increment counters.
        
        Args:
            success: Whether processing succeeded
        """
        with self.lock:
            self.processed_count += 1
            if not success:
                self.error_count += 1
    
    def should_log(self, interval: int = 10) -> bool:
        """Check if progress should be logged.
        
        Args:
            interval: Number of articles between logs
            
        Returns:
            True if should log now
        """
        with self.lock:
            count_trigger = self.processed_count - self.last_log_count >= interval
            time_trigger = time.time() - self.last_log_time >= 30  # Log at least every 30s
            return count_trigger or time_trigger
    
    def log_progress(
        self,
        memory_monitor: MemoryMonitor,
        rate_limiter: RateLimiter,
        browser_pool: BrowserPool
    ) -> None:
        """Log current progress with all metrics.
        
        Args:
            memory_monitor: Memory monitor instance
            rate_limiter: Rate limiter instance
            browser_pool: Browser pool instance
        """
        with self.lock:
            elapsed_hours = (time.time() - self.start_time) / 3600
            rate = self.processed_count / elapsed_hours if elapsed_hours > 0 else 0
            
            remaining = self.total_articles - self.processed_count
            eta_hours = remaining / rate if rate > 0 else 0
            
            memory = psutil.virtual_memory()
            memory_stats = memory_monitor.get_stats()
            rate_stats = rate_limiter.get_stats()
            browser_stats = browser_pool.get_stats()
            
            percent = (self.processed_count / self.total_articles * 100) if self.total_articles > 0 else 0
            
            logger.info(
                f"Progress: {self.processed_count:,}/{self.total_articles:,} ({percent:.1f}%) | "
                f"Rate: {rate:.0f} art/h | "
                f"Memory: {memory.percent:.0f}% ({memory.used / (1024**3):.1f}/{memory.total / (1024**3):.1f}GB) | "
                f"Browsers: {browser_stats['in_use']}/{browser_stats['max_browsers']} | "
                f"Rate limit: {rate_stats['rate_limit_hits']} hits ({rate_stats['hit_rate']:.1f}%) | "
                f"ETA: {eta_hours:.1f}h | "
                f"Stage: {self.stage}"
            )
            
            self.last_log_time = time.time()
            self.last_log_count = self.processed_count
    
    def log_summary(self, memory_monitor: MemoryMonitor) -> None:
        """Log final summary.
        
        Args:
            memory_monitor: Memory monitor instance
        """
        elapsed_hours = (time.time() - self.start_time) / 3600
        rate = self.processed_count / elapsed_hours if elapsed_hours > 0 else 0
        memory_stats = memory_monitor.get_stats()
        
        logger.info(
            f"Backlog Processing Complete:\n"
            f"  Total processed: {self.processed_count:,}\n"
            f"  Errors: {self.error_count:,}\n"
            f"  Time: {elapsed_hours:.1f}h\n"
            f"  Avg rate: {rate:.0f} art/h\n"
            f"  Peak memory: {memory_stats['peak_memory_percent']:.0f}%\n"
            f"  Stage: {self.stage}"
        )


# ============================================================================
# FAILURE TRACKER
# ============================================================================

class FailureTracker:
    """Tracks failed articles for retry and analysis."""
    
    def __init__(self):
        """Initialize failure tracker."""
        self.failures: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.lock = threading.Lock()
        self.attempt_counts: defaultdict[str, Dict[str, int]] = defaultdict(dict)
        self.skipped_articles: defaultdict[str, Set[str]] = defaultdict(set)
    
    def _increment_attempt(self, stage: str, article_id: str) -> int:
        """Increment and return attempt count for an article/stage pair."""
        stage_attempts = self.attempt_counts[stage]
        stage_attempts[article_id] = stage_attempts.get(article_id, 0) + 1
        return stage_attempts[article_id]
    
    def mark_skipped(self, stage: str, article_id: str) -> None:
        """Record that an article should be skipped for the remainder of this run."""
        with self.lock:
            self.skipped_articles[stage].add(article_id)
    
    def is_skipped(self, stage: str, article_id: str) -> bool:
        """Check if an article is marked as skipped for the current run."""
        with self.lock:
            return article_id in self.skipped_articles.get(stage, set())
    
    def get_attempts(self, stage: str, article_id: str) -> int:
        """Return the attempt count for an article/stage pair."""
        with self.lock:
            return self.attempt_counts.get(stage, {}).get(article_id, 0)
    
    def record_failure(
        self,
        stage: str,
        article_id: str,
        url: str,
        error: str,
        tb: str
    ) -> int:
        """Record a processing failure.
        
        Args:
            stage: Stage name
            article_id: Article ID
            url: Article URL
            error: Error message
            tb: Traceback string
        """
        with self.lock:
            attempt_count = self._increment_attempt(stage, article_id)
            self.failures[stage].append({
                "article_id": article_id,
                "url": url,
                "error": str(error),
                "traceback": tb,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return attempt_count
    
    def save(self, filepath: Path) -> None:
        """Atomically save failures to JSON file.
        
        Args:
            filepath: Path to save failures
        """
        with self.lock:
            if not self.failures:
                logger.info("No failures to save")
                return
            
            try:
                temp_path = filepath.with_suffix('.tmp')
                with open(temp_path, 'w') as f:
                    json.dump(dict(self.failures), f, indent=2)
                temp_path.replace(filepath)
                
                total_failures = sum(len(v) for v in self.failures.values())
                logger.info(f"Saved {total_failures} failures to {filepath}")
            except Exception as e:
                logger.error(f"Failed to save failures: {e}")
    
    def load(self, filepath: Path) -> Dict[str, List[str]]:
        """Load failures from JSON file and extract article IDs by stage.
        
        Args:
            filepath: Path to failures file
            
        Returns:
            Dict mapping stage to list of article IDs
        """
        if not filepath.exists():
            logger.warning(f"Failures file not found: {filepath}")
            return {}
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            article_ids_by_stage = {}
            for stage, failures in data.items():
                article_ids_by_stage[stage] = [f["article_id"] for f in failures]
            
            total_failures = sum(len(v) for v in article_ids_by_stage.values())
            logger.info(f"Loaded {total_failures} failures from {filepath}")
            return article_ids_by_stage
        except Exception as e:
            logger.error(f"Failed to load failures: {e}")
            return {}
    
    def get_summary(self) -> Dict[str, int]:
        """Get failure counts by stage.
        
        Returns:
            Dict mapping stage to failure count
        """
        with self.lock:
            summary = {stage: len(failures) for stage, failures in self.failures.items()}
            for stage, skipped in self.skipped_articles.items():
                if skipped:
                    summary[f"{stage}_skipped"] = len(skipped)
            return summary


def register_stage_failure(
    stage: str,
    article_id: str,
    article_url: str,
    message: str,
    failure_tracker: FailureTracker,
    tb: str = ""
) -> None:
    """Record a failure and skip the article after MAX_FAILURE_ATTEMPTS_PER_URL attempts."""
    article_id = str(article_id)
    attempts = failure_tracker.record_failure(stage, article_id, article_url, message, tb)
    if attempts >= MAX_FAILURE_ATTEMPTS_PER_URL:
        failure_tracker.mark_skipped(stage, article_id)
        logger.warning(
            f"[{article_id}] {stage} stage failed ({message}). "
            f"Reached {attempts} attempts — skipping for the rest of this run."
        )
    else:
        remaining = MAX_FAILURE_ATTEMPTS_PER_URL - attempts
        logger.info(
            f"[{article_id}] {stage} stage failed ({message}). "
            f"{remaining} retry(s) remaining this run."
        )


# ============================================================================
# PENDING URL CACHE
# ============================================================================


class PendingUrlCache:
    """Caches pending URLs locally so failed IDs do not starve later batches."""

    def __init__(self, stage: str, config: PipelineConfig, fetch_window: int):
        self.stage = stage
        self.config = config
        self.fetch_window = max(1, fetch_window)
        self.queue: deque[dict] = deque()
        self.seen_ids: Set[str] = set()
        self.depleted = False
        self.fetch_round = 0

    def next_batch(
        self,
        batch_size: int,
        *,
        limit_remaining: Optional[int] = None,
        skip_predicate: Optional[Callable[[dict], bool]] = None,
    ) -> List[dict]:
        """Return the next batch of cached URLs, fetching more when needed."""

        if limit_remaining is not None and limit_remaining <= 0:
            return []

        target_size = batch_size
        if limit_remaining is not None:
            target_size = min(batch_size, max(limit_remaining, 0))
        if target_size <= 0:
            return []

        batch: List[dict] = []

        while len(batch) < target_size:
            self._ensure_capacity(target_size - len(batch), limit_remaining)
            if not self.queue:
                break

            item = self.queue.popleft()
            article_id = item.get("id")
            if not article_id:
                continue

            if skip_predicate and skip_predicate(item):
                continue

            batch.append(item)

        return batch

    def _ensure_capacity(self, min_size: int, limit_remaining: Optional[int]) -> None:
        if len(self.queue) >= min_size or self.depleted:
            return

        while len(self.queue) < min_size and not self.depleted:
            request_limit = self._compute_request_limit(min_size, limit_remaining)
            if request_limit <= 0:
                self.depleted = True
                break

            urls = fetch_pending_urls_from_edge(
                self.stage,
                self.config,
                limit=request_limit,
            )
            self.fetch_round += 1
            added = self._add_urls(urls)

            if added == 0:
                if not urls or len(urls) < request_limit:
                    # Supabase returned fewer rows, so no more pending items exist.
                    self.depleted = True
                    break

                # No new IDs were discovered because duplicates dominated the window.
                self._expand_window()
            else:
                logger.debug(
                    "Pending cache fetched %s new URLs (round %s)",
                    added,
                    self.fetch_round,
                )

    def _compute_request_limit(self, min_size: int, limit_remaining: Optional[int]) -> int:
        limit = max(self.fetch_window, min_size)
        limit = min(limit, MAX_EDGE_FETCH_LIMIT)
        if limit_remaining is not None:
            limit = min(limit, max(limit_remaining, 0))
        return limit

    def _add_urls(self, urls: List[dict]) -> int:
        added = 0
        for item in urls:
            raw_id = item.get("id")
            if raw_id is None:
                continue

            article_id = str(raw_id)
            if article_id in self.seen_ids:
                continue

            self.seen_ids.add(article_id)
            self.queue.append({"id": article_id, "url": item.get("url")})
            added += 1

        if not self.queue and urls:
            # All rows were duplicates; fetch window will expand on next ensure.
            logger.debug(
                "Pending cache skipped %s duplicate URLs for stage %s",
                len(urls),
                self.stage,
            )

        return added

    def _expand_window(self) -> None:
        if self.fetch_window >= MAX_EDGE_FETCH_LIMIT:
            logger.warning(
                "Pending cache reached max fetch limit (%s) for stage %s without new rows",
                MAX_EDGE_FETCH_LIMIT,
                self.stage,
            )
            self.depleted = True
            return

        previous_window = self.fetch_window
        self.fetch_window = min(MAX_EDGE_FETCH_LIMIT, self.fetch_window * 2)
        logger.info(
            "Expanding pending cache fetch window from %s to %s for stage %s",
            previous_window,
            self.fetch_window,
            self.stage,
        )


# ============================================================================
# TASK PING / WATCHDOG
# ============================================================================


class TaskPingHandle:
    """Per-task heartbeat tracker that emits periodic ping logs."""

    PING_LOG_INTERVAL = 15  # seconds

    def __init__(self, stage: str, article_id: str, article_url: str):
        self.stage = stage
        self.article_id = article_id
        self.article_url = article_url
        self.last_ping = time.time()
        self.last_message = "initialized"
        self._timed_out = False
        self._lock = threading.Lock()
        self._last_log = 0.0
        self._last_logged_message = ""

    def ping(self, message: Optional[str] = None) -> None:
        """Update the heartbeat timestamp and optionally log a status message."""
        now = time.time()
        should_log = False

        with self._lock:
            self.last_ping = now
            if message:
                self.last_message = message

            if message:
                if (message != self._last_logged_message) or (now - self._last_log >= self.PING_LOG_INTERVAL):
                    should_log = True
            else:
                should_log = (now - self._last_log) >= self.PING_LOG_INTERVAL

            if should_log:
                self._last_log = now
                if message:
                    self._last_logged_message = message
                log_message = message or "heartbeat"

        if should_log:
            logger.info(f"🔁 Ping [{self.stage}:{self.article_id}]: {log_message}")

    @contextmanager
    def keepalive(self, message: str, interval: float = 5.0):
        """Emit periodic pings while a long-running block is executing."""
        stop_event = threading.Event()

        def _runner() -> None:
            while not stop_event.wait(interval):
                self.ping(message)

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()

        try:
            self.ping(f"{message} (start)")
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)
            self.ping(f"{message} (done)")

    def mark_timed_out(self) -> None:
        with self._lock:
            self._timed_out = True

    def is_timed_out(self) -> bool:
        with self._lock:
            return self._timed_out

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "article_id": self.article_id,
                "stage": self.stage,
                "article_url": self.article_url,
                "last_ping": self.last_ping,
                "last_message": self.last_message,
            }


class TaskPingManager:
    """Manages TaskPingHandle instances and detects stalled work."""

    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds
        self._handles: Dict[Any, TaskPingHandle] = {}
        self._lock = threading.Lock()

    def create_handle(self, stage: str, article_id: str, article_url: str) -> TaskPingHandle:
        return TaskPingHandle(stage, article_id, article_url)

    def track(self, future, handle: TaskPingHandle) -> None:
        with self._lock:
            self._handles[future] = handle

    def release(self, future) -> Optional[TaskPingHandle]:
        with self._lock:
            return self._handles.pop(future, None)

    def collect_timeouts(self) -> List[Tuple[Any, TaskPingHandle]]:
        now = time.time()
        timed_out: List[Tuple[Any, TaskPingHandle]] = []
        with self._lock:
            for future, handle in list(self._handles.items()):
                if handle.is_timed_out():
                    continue
                if now - handle.last_ping >= self.timeout_seconds:
                    handle.mark_timed_out()
                    timed_out.append((future, handle))
        return timed_out


def send_ping(ping_handle: Optional[TaskPingHandle], message: str) -> None:
    """Helper to guard ping calls when handle is optional."""
    if ping_handle:
        ping_handle.ping(message)


@contextmanager
def ping_keepalive(
    ping_handle: Optional[TaskPingHandle],
    message: str,
    interval: float = 5.0,
):
    """Context manager that keeps pinging while a block executes."""
    if ping_handle:
        with ping_handle.keepalive(message, interval):
            yield
    else:
        yield


# ============================================================================
# BATCH EMBEDDING GENERATION
# ============================================================================

def generate_embeddings_batch(
    texts: List[str],
    config: PipelineConfig,
    rate_limiter: Optional[RateLimiter] = None
) -> List[List[float]]:
    """Generate embeddings for multiple texts in batches.
    
    Args:
        texts: List of text strings to embed
        config: Pipeline configuration
        rate_limiter: Optional rate limiter
        
    Returns:
        List of embedding vectors in same order as input texts
    """
    if not texts:
        return []
    
    BATCH_SIZE = 100  # OpenAI supports up to 2048, but 100 is safer
    MAX_RETRIES = 3
    
    all_embeddings = []
    
    # Process in batches
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        
        # Retry logic for this batch
        for attempt in range(MAX_RETRIES):
            try:
                if rate_limiter:
                    rate_limiter.acquire()
                
                headers = {
                    "Authorization": f"Bearer {config.embedding_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": config.embedding_model_name,
                    "input": batch,
                }
                
                response = requests.post(
                    config.embedding_api_url,
                    headers=headers,
                    json=payload,
                    timeout=config.embedding_timeout_seconds,
                )
                
                if response.status_code == 429 and rate_limiter:
                    delay = rate_limiter.handle_429(attempt)
                    logger.info(f"⏳ Rate limit backoff: Sleeping for {delay}s...")
                    time.sleep(delay)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                # Extract embeddings in order
                batch_embeddings = []
                for item in data["data"]:
                    embedding = item["embedding"]
                    if isinstance(embedding, list):
                        batch_embeddings.append(embedding)
                
                if len(batch_embeddings) != len(batch):
                    logger.error(
                        f"Embedding count mismatch: expected {len(batch)}, got {len(batch_embeddings)}"
                    )
                    # Return empty vectors for failed batch
                    batch_embeddings = [[] for _ in batch]
                
                all_embeddings.extend(batch_embeddings)
                logger.debug(f"Generated {len(batch_embeddings)} embeddings (batch {i // BATCH_SIZE + 1})")
                break
                
            except Exception as e:
                logger.warning(f"Embedding batch failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES - 1:
                    # Return empty vectors for failed batch
                    all_embeddings.extend([[] for _ in batch])
                else:
                    sleep_time = 2 ** attempt
                    logger.info(f"⏳ Retrying embedding batch in {sleep_time}s...")
                    time.sleep(sleep_time)
    
    return all_embeddings


# ============================================================================
# BULK DATABASE OPERATIONS
# ============================================================================

def bulk_fetch_facts(client, url_ids: List[str]) -> Dict[str, List[dict]]:
    """Fetch all facts for multiple URLs in a single query.
    
    Args:
        client: Supabase client
        url_ids: List of news URL IDs
        
    Returns:
        Dict mapping URL ID to list of fact records
    """
    if not url_ids:
        return {}
    
    facts_by_url = defaultdict(list)
    page_size = 1000
    offset = 0
    
    while True:
        response = (
            client.table("news_facts")
            .select("*")
            .in_("news_url_id", url_ids)
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        
        rows = getattr(response, "data", []) or []
        for row in rows:
            url_id = row.get("news_url_id")
            if url_id:
                facts_by_url[url_id].append(row)
        
        if len(rows) < page_size:
            break
        offset += page_size
    
    logger.debug(f"Bulk fetched facts for {len(url_ids)} URLs")
    return dict(facts_by_url)


def bulk_check_embeddings(client, fact_ids: List[str]) -> Set[str]:
    """Check which facts already have embeddings.
    
    Args:
        client: Supabase client
        fact_ids: List of fact IDs to check
        
    Returns:
        Set of fact IDs that have embeddings
    """
    if not fact_ids:
        return set()
    
    existing_ids = set()
    page_size = 1000
    offset = 0
    
    while True:
        response = (
            client.table("facts_embeddings")
            .select("news_fact_id")
            .in_("news_fact_id", fact_ids)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        
        rows = getattr(response, "data", []) or []
        for row in rows:
            fact_id = row.get("news_fact_id")
            if fact_id:
                existing_ids.add(fact_id)
        
        if len(rows) < page_size:
            break
        offset += page_size
    
    logger.debug(f"Bulk checked embeddings: {len(existing_ids)}/{len(fact_ids)} exist")
    return existing_ids


def bulk_insert_embeddings(client, records: List[dict]) -> int:
    """Bulk insert embedding records.
    
    Args:
        client: Supabase client
        records: List of embedding records to insert
        
    Returns:
        Number of records inserted
    """
    if not records:
        return 0
    
    BATCH_SIZE = 1000  # Supabase limit
    total_inserted = 0
    
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        try:
            response = client.table("facts_embeddings").insert(batch).execute()
            inserted = len(getattr(response, "data", []) or [])
            total_inserted += inserted
            logger.debug(f"Inserted {inserted} embeddings (batch {i // BATCH_SIZE + 1})")
        except Exception as e:
            logger.error(f"Failed to insert embedding batch: {e}")
    
    return total_inserted


def bulk_update_timestamps(client, url_ids: List[str], column: str) -> None:
    """Bulk update timestamp column for multiple URLs.
    
    Args:
        client: Supabase client
        url_ids: List of news URL IDs to update
        column: Column name to update
    """
    if not url_ids:
        return
    
    now_iso = datetime.now(timezone.utc).isoformat()
    
    try:
        client.table("news_urls").update(
            {column: now_iso}
        ).in_("id", url_ids).execute()
        
        logger.debug(f"Bulk updated {column} for {len(url_ids)} URLs")
    except Exception as e:
        logger.error(f"Failed to bulk update timestamps: {e}")


def mark_news_url_timestamp(client, news_url_id: str, column: str) -> None:
    """Set a single timestamp column on news_urls to now."""

    if not news_url_id:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        client.table("news_urls").update({column: now_iso}).eq("id", news_url_id).execute()
    except Exception as exc:
        logger.error(
            "Failed to mark %s for %s: %s",
            column,
            news_url_id,
            exc,
        )


# ============================================================================
# ARTICLE PROCESSING FUNCTIONS (Using direct extraction)
# ============================================================================

def fetch_article_content_direct(url: str, browser_pool: BrowserPool) -> str:
    """Fetch article content using direct library import.
    
    Args:
        url: Article URL
        browser_pool: Browser pool (not used with current extractor pattern)
        
    Returns:
        Extracted article content text
    """
    try:
        # Get appropriate extractor for URL
        extractor = get_extractor(url)
        
        # Extract content
        result = extractor.extract(url, timeout=45)
        
        if result.error:
            logger.warning(f"Extraction error for {url}: {result.error}")
            return ""
        
        # Join paragraphs to get full article text
        if result.paragraphs:
            content = "\n\n".join(result.paragraphs)
            return content.strip()
        
        logger.warning(f"Extractor returned no paragraphs for {url}")
        return ""
        
    except Exception as e:
        logger.error(f"Direct extraction failed for {url}: {e}")
        return ""


def fetch_article_content_with_fallback(
    url: str,
    config: PipelineConfig,
    browser_pool: BrowserPool,
    ping_handle: Optional[TaskPingHandle] = None,
) -> str:
    """Try the direct extractor first, then fall back to the extraction service."""

    content = fetch_article_content_direct(url, browser_pool)
    if content:
        return content

    if not config.content_extraction_url:
        return ""

    logger.info("Direct extractor returned empty, falling back to extraction service", {"url": url})
    send_ping(ping_handle, "facts: falling back to extractor")
    with ping_keepalive(ping_handle, "facts: fetching via extraction service"):
        try:
            return fetch_article_content_service(url, config) or ""
        except Exception as exc:
            logger.error("Fallback extraction failed", {"url": url, "error": str(exc)})
            return ""


def process_article_facts_stage(
    item: dict,
    client,
    config: PipelineConfig,
    checkpoint: CheckpointManager,
    browser_pool: BrowserPool,
    rate_limiter: RateLimiter,
    failure_tracker: FailureTracker,
    ping_handle: Optional[TaskPingHandle] = None,
) -> bool:
    """Process facts stage for a single article.
    
    Args:
        item: Article item from pending URLs
        client: Supabase client
        config: Pipeline configuration
        checkpoint: Checkpoint manager
        browser_pool: Browser pool
        rate_limiter: Rate limiter
        failure_tracker: Failure tracker
        
    Returns:
        True if successful
    """
    raw_url_id = item.get("id")
    article_url = item.get("url") or ""
    
    if not raw_url_id or not article_url:
        logger.warning("Skipping malformed URL payload", {"item": item})
        register_stage_failure(
            "facts",
            str(raw_url_id or "unknown"),
            article_url,
            "Missing article metadata",
            failure_tracker,
        )
        return False
    
    url_id = str(raw_url_id)
    
    logger.debug(f"[{url_id}] Starting facts stage processing...")
    send_ping(ping_handle, "facts: stage started")
    
    try:
        # Check if already complete
        if checkpoint.is_stage_complete(url_id, "facts"):
            logger.debug(f"Skipping completed article (facts): {url_id}")
            send_ping(ping_handle, "facts: already complete")
            return True
        
        # Fetch content with fallback
        logger.debug(f"[{url_id}] Extracting article content...")
        with ping_keepalive(ping_handle, "facts: extracting content"):
            article_text = fetch_article_content_with_fallback(
                article_url,
                config,
                browser_pool,
                ping_handle,
            )
        if not article_text:
            logger.warning(f"[{url_id}] No content extracted")
            register_stage_failure(
                "facts",
                url_id,
                article_url,
                "Content extraction returned empty",
                failure_tracker,
            )
            return False
        
        logger.debug(f"[{url_id}] Content extracted ({len(article_text)} chars), marking timestamp...")
        # Mark content extracted
        retry_on_network_error(lambda: mark_news_url_timestamp(client, url_id, "content_extracted_at"))
        checkpoint.mark_stage_complete(url_id, "content")
        send_ping(ping_handle, "facts: content extracted")
        
        # Extract facts
        logger.debug(f"[{url_id}] Extracting facts with LLM (acquiring rate limit)...")
        send_ping(ping_handle, "facts: waiting for LLM slot")
        rate_limiter.acquire()
        with ping_keepalive(ping_handle, "facts: extracting facts"):
            facts = extract_facts(article_text, config)
        if not facts:
            logger.warning(f"[{url_id}] No facts extracted by LLM")
            register_stage_failure(
                "facts",
                url_id,
                article_url,
                "LLM did not return any facts",
                failure_tracker,
            )
            return False
        
        logger.debug(f"[{url_id}] Extracted {len(facts)} facts, filtering...")
        send_ping(ping_handle, "facts: filtering results")
        # Filter facts
        filtered_facts, rejected_facts = filter_story_facts(facts)
        if rejected_facts:
            logger.debug(f"[{url_id}] Rejected {len(rejected_facts)} non-story facts")
        
        if not filtered_facts:
            logger.warning(f"[{url_id}] All facts rejected after filtering")
            with ping_keepalive(ping_handle, "facts: cleaning rejected facts"):
                retry_on_network_error(lambda: remove_non_story_facts_from_db(client, url_id))
            register_stage_failure(
                "facts",
                url_id,
                article_url,
                "All facts rejected after filtering",
                failure_tracker,
            )
            return False
        
        logger.debug(f"[{url_id}] Storing {len(filtered_facts)} filtered facts...")
        send_ping(ping_handle, "facts: storing facts")
        # Store facts
        with ping_keepalive(ping_handle, "facts: storing facts"):
            fact_ids = retry_on_network_error(
                lambda: store_facts(client, url_id, filtered_facts, config)
            )
        if not fact_ids:
            logger.debug(f"[{url_id}] Facts already exist, fetching existing IDs...")
            with ping_keepalive(ping_handle, "facts: loading fact ids"):
                fact_ids = retry_on_network_error(lambda: fetch_existing_fact_ids(client, url_id))
        else:
            logger.debug(f"[{url_id}] Stored {len(fact_ids)} new facts")
        
        # Generate embeddings (will be batched later)
        # For now, create embeddings for this article's facts
        logger.debug(f"[{url_id}] Checking existing embeddings for {len(fact_ids)} facts...")
        send_ping(ping_handle, "facts: preparing embeddings")
        with ping_keepalive(ping_handle, "facts: checking embeddings"):
            existing_embeddings = retry_on_network_error(
                lambda: bulk_check_embeddings(client, fact_ids)
            )
        facts_to_embed = [fid for fid in fact_ids if fid not in existing_embeddings]
        
        if facts_to_embed:
            logger.debug(f"[{url_id}] Generating embeddings for {len(facts_to_embed)} facts...")
            # Fetch fact texts
            with ping_keepalive(ping_handle, "facts: fetching texts"):
                facts_response = retry_on_network_error(
                    lambda: (
                        client.table("news_facts")
                        .select("id,fact_text")
                        .in_("id", facts_to_embed)
                        .execute()
                    )
                )
            fact_rows = getattr(facts_response, "data", []) or []
            
            if fact_rows:
                logger.debug(f"[{url_id}] Calling OpenAI batch embeddings API for {len(fact_rows)} facts...")
                # Batch generate embeddings
                texts = [row.get("fact_text", "") for row in fact_rows]
                with ping_keepalive(ping_handle, "facts: generating embeddings"):
                    embeddings = generate_embeddings_batch(texts, config, rate_limiter)
                
                logger.debug(f"[{url_id}] Generated {len(embeddings)} embeddings, storing...")
                # Prepare embedding records
                embedding_records = []
                for idx, row in enumerate(fact_rows):
                    if idx < len(embeddings) and embeddings[idx]:
                        embedding_records.append({
                            "news_fact_id": row.get("id"),
                            "embedding_vector": embeddings[idx],
                            "model_name": config.embedding_model_name,
                        })
                
                # Bulk insert
                if embedding_records:
                    with ping_keepalive(ping_handle, "facts: saving embeddings"):
                        bulk_insert_embeddings(client, embedding_records)
                    logger.debug(f"[{url_id}] Inserted {len(embedding_records)} embeddings")
        else:
            logger.debug(f"[{url_id}] All {len(fact_ids)} facts already have embeddings")
        
        # Create pooled embedding
        logger.debug(f"[{url_id}] Creating pooled embedding...")
        with ping_keepalive(ping_handle, "facts: pooling embeddings"):
            retry_on_network_error(lambda: create_fact_pooled_embedding(client, url_id, config))
        
        # Verify completion
        logger.debug(f"[{url_id}] Verifying stage completion...")
        send_ping(ping_handle, "facts: verifying completion")
        verification = retry_on_network_error(lambda: fact_stage_completed(client, url_id))
        if verification:
            retry_on_network_error(lambda: mark_news_url_timestamp(client, url_id, "facts_extracted_at"))
            checkpoint.mark_stage_complete(url_id, "facts")
            send_ping(ping_handle, "facts: stage complete")
            return True
        else:
            logger.warning(f"Fact stage incomplete after processing: {url_id}")
            diagnostics = get_fact_stage_diagnostics(client, url_id)
            if diagnostics:
                logger.warning("Fact stage diagnostics", {"news_url_id": url_id, **diagnostics})
            if diagnostics.get("facts_count", 0) > 0 and diagnostics.get("pooled_count", 0) == 0:
                logger.info(f"[{url_id}] Retrying pooled embedding after failed verification")
                with ping_keepalive(ping_handle, "facts: retry pooling"):
                    retry_on_network_error(lambda: create_fact_pooled_embedding(client, url_id, config))
                verification = retry_on_network_error(lambda: fact_stage_completed(client, url_id))
                if verification:
                    retry_on_network_error(lambda: mark_news_url_timestamp(client, url_id, "facts_extracted_at"))
                    checkpoint.mark_stage_complete(url_id, "facts")
                    send_ping(ping_handle, "facts: stage complete (retry)")
                    return True

            register_stage_failure(
                "facts",
                url_id,
                article_url,
                "Fact stage verification failed",
                failure_tracker,
            )
            return False
            
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to process facts for {url_id}: {e}\n{tb}")
        register_stage_failure("facts", url_id, article_url, str(e), failure_tracker, tb)
        return False


def retry_on_network_error(func, max_retries: int = 3, initial_delay: float = 1.0):
    """Retry a function on network/protocol errors with exponential backoff.
    
    Args:
        func: Callable to retry
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds (doubles each retry)
        
    Returns:
        Function result or raises last exception
    """
    import httpx
    from httpcore import LocalProtocolError, RemoteProtocolError
    
    retryable_errors = (
        LocalProtocolError,
        RemoteProtocolError,
        httpx.LocalProtocolError,
        httpx.RemoteProtocolError,
        httpx.ConnectError,
        httpx.ReadTimeout,
    )
    
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except retryable_errors as e:
            last_exception = e
            if attempt < max_retries - 1:
                logger.warning(
                    f"Network error (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                logger.error(f"Network error after {max_retries} attempts: {e}")
                raise
        except Exception as e:
            # Non-retryable error, raise immediately
            raise
    
    if last_exception:
        raise last_exception


def get_fact_stage_diagnostics(client, news_url_id: str) -> Dict[str, int]:
    """Collect basic counts used to debug fact stage verification."""

    diagnostics: Dict[str, int] = {}

    try:
        facts_response = retry_on_network_error(
            lambda: (
                client.table("news_facts")
                .select("id", count="exact")
                .eq("news_url_id", news_url_id)
                .execute()
            )
        )
        facts_count = getattr(facts_response, "count", None)
        if facts_count is None:
            facts_count = len(getattr(facts_response, "data", []) or [])
        diagnostics["facts_count"] = int(facts_count)
    except Exception as exc:
        logger.warning("Failed to collect facts diagnostics", {"news_url_id": news_url_id, "error": str(exc)})

    try:
        pooled_response = retry_on_network_error(
            lambda: (
                client.table("story_embeddings")
                .select("id", count="exact")
                .eq("news_url_id", news_url_id)
                .eq("embedding_type", "fact_pooled")
                .execute()
            )
        )
        pooled_count = getattr(pooled_response, "count", None)
        if pooled_count is None:
            pooled_count = len(getattr(pooled_response, "data", []) or [])
        diagnostics["pooled_count"] = int(pooled_count)
    except Exception as exc:
        logger.warning("Failed to collect pooled embedding diagnostics", {"news_url_id": news_url_id, "error": str(exc)})

    return diagnostics


def process_article_knowledge_stage(
    item: dict,
    client,
    config: PipelineConfig,
    checkpoint: CheckpointManager,
    rate_limiter: RateLimiter,
    failure_tracker: FailureTracker,
    ping_handle: Optional[TaskPingHandle] = None,
) -> bool:
    """Process knowledge extraction stage for a single article."""

    raw_url_id = item.get("id")
    article_url = item.get("url") or ""

    if not raw_url_id or not article_url:
        logger.warning("Knowledge stage received malformed payload", {"item": item})
        register_stage_failure(
            "knowledge",
            str(raw_url_id or "unknown"),
            article_url,
            "Missing article metadata",
            failure_tracker,
        )
        return False

    url_id = str(raw_url_id)

    try:
        if checkpoint.is_stage_complete(url_id, "knowledge"):
            logger.debug(f"Skipping completed article (knowledge): {url_id}")
            send_ping(ping_handle, "knowledge: already complete")
            return True

        logger.debug(f"[{url_id}] Starting knowledge extraction stage")
        send_ping(ping_handle, "knowledge: stage started")

        from src.functions.knowledge_extraction.core.db.fact_reader import NewsFactReader
        from src.functions.knowledge_extraction.core.db.knowledge_writer import KnowledgeWriter
        from src.functions.knowledge_extraction.core.extraction.entity_extractor import EntityExtractor
        from src.functions.knowledge_extraction.core.extraction.topic_extractor import TopicExtractor
        from src.functions.knowledge_extraction.core.resolution.entity_resolver import EntityResolver

        reader = NewsFactReader()
        writer = KnowledgeWriter()
        entity_extractor = EntityExtractor()
        topic_extractor = TopicExtractor()
        entity_resolver = EntityResolver()

        with ping_keepalive(ping_handle, "knowledge: fetching facts"):
            facts = retry_on_network_error(lambda: reader.get_facts_for_url(url_id))

        if not facts:
            logger.info(f"[{url_id}] No facts found for knowledge extraction")
            checkpoint.mark_stage_complete(url_id, "knowledge")
            send_ping(ping_handle, "knowledge: no facts, marked complete")
            return True

        logger.debug(f"[{url_id}] Processing {len(facts)} facts for knowledge extraction")
        send_ping(ping_handle, f"knowledge: {len(facts)} facts queued")

        fact_ids = [fact.get("id") for fact in facts if fact.get("id")]
        with ping_keepalive(ping_handle, "knowledge: loading existing outputs"):
            existing_topics = set(
                retry_on_network_error(lambda: reader.get_existing_topic_fact_ids(fact_ids))
            )
            existing_entities = set(
                retry_on_network_error(lambda: reader.get_existing_entity_fact_ids(fact_ids))
            )

        topics_written = 0
        entities_written = 0

        for idx, fact in enumerate(facts, start=1):
            fact_id = fact.get("id")
            fact_text = (fact.get("fact_text") or "").strip()
            if not fact_id or not fact_text:
                continue

            need_topics = fact_id not in existing_topics
            need_entities = fact_id not in existing_entities
            if not need_topics and not need_entities:
                continue

            if need_topics:
                with ping_keepalive(ping_handle, "knowledge: extracting topics"):
                    topics = topic_extractor.extract(fact_text, max_topics=3)
                topics_count = writer.write_fact_topics(
                    news_fact_id=fact_id,
                    topics=topics,
                    llm_model=topic_extractor.model,
                    dry_run=False,
                )
                topics_written += topics_count
                send_ping(ping_handle, f"knowledge: topics updated ({topics_written})")

            if need_entities:
                with ping_keepalive(ping_handle, "knowledge: extracting entities"):
                    entities = entity_extractor.extract(fact_text, max_entities=5)
                with ping_keepalive(ping_handle, "knowledge: resolving entities"):
                    resolved_entities = entity_resolver.resolve_entities(entities)
                entity_count = writer.write_fact_entities(
                    news_fact_id=fact_id,
                    entities=resolved_entities,
                    llm_model=entity_extractor.model,
                    dry_run=False,
                )
                entities_written += entity_count
                send_ping(ping_handle, f"knowledge: entities updated ({entities_written})")

            if idx % 5 == 0:
                send_ping(ping_handle, f"knowledge: processed {idx} facts")

        writer.update_article_metrics(news_url_id=str(url_id))

        logger.info(
            f"[{url_id}] Knowledge extraction complete: "
            f"{topics_written} topics, {entities_written} entities"
        )
        send_ping(ping_handle, "knowledge: stage complete")

        checkpoint.mark_stage_complete(url_id, "knowledge")
        return True

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to process knowledge for {url_id}: {e}\n{tb}")
        register_stage_failure("knowledge", url_id, article_url, str(e), failure_tracker, tb)
        return False


def process_article_summary_stage(
    item: dict,
    client,
    config: PipelineConfig,
    checkpoint: CheckpointManager,
    rate_limiter: RateLimiter,
    failure_tracker: FailureTracker,
    ping_handle: Optional[TaskPingHandle] = None,
) -> bool:
    """Process summary stage for a single article.
    
    Args:
        item: Article item from pending URLs
        client: Supabase client
        config: Pipeline configuration
        checkpoint: Checkpoint manager
        rate_limiter: Rate limiter
        failure_tracker: Failure tracker
        
    Returns:
        True if successful
    """
    raw_url_id = item.get("id")
    article_url = item.get("url") or ""

    if not raw_url_id or not article_url:
        logger.warning("Summary stage received malformed payload", {"item": item})
        register_stage_failure(
            "summary",
            str(raw_url_id or "unknown"),
            article_url,
            "Missing article metadata",
            failure_tracker,
        )
        return False

    url_id = str(raw_url_id)

    try:
        if checkpoint.is_stage_complete(url_id, "summary"):
            logger.debug(f"Skipping completed article (summary): {url_id}")
            send_ping(ping_handle, "summary: already complete")
            return True

        logger.debug(f"[{url_id}] Starting summary stage")
        send_ping(ping_handle, "summary: stage started")

        difficulty_record = retry_on_network_error(
            lambda: get_article_difficulty(client, url_id)
        )
        difficulty = difficulty_record.get("article_difficulty") if difficulty_record else None

        if not difficulty:
            logger.debug(f"[{url_id}] Waiting for knowledge extraction (no difficulty set)")
            send_ping(ping_handle, "summary: waiting for difficulty")
            return False

        logger.debug(f"[{url_id}] Generating {difficulty} article summary")
        if difficulty == "easy":
            with ping_keepalive(ping_handle, "summary: running easy handler"):
                handle_easy_article_summary(client, url_id, config)
            logger.info(f"[{url_id}] Easy article summary complete")
        else:
            with ping_keepalive(ping_handle, "summary: running hard handler"):
                handle_hard_article_summary(client, url_id, config)
            logger.info(f"[{url_id}] Hard article summary complete")

        if retry_on_network_error(lambda: summary_stage_completed(client, url_id)):
            mark_news_url_timestamp(client, url_id, "summary_created_at")
            checkpoint.mark_stage_complete(url_id, "summary")
            logger.info(f"[{url_id}] Summary stage complete")
            send_ping(ping_handle, "summary: stage complete")
            return True

        logger.warning(f"[{url_id}] Summary stage incomplete after processing")
        send_ping(ping_handle, "summary: verification failed")
        return False

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to process summary for {url_id}: {e}\n{tb}")
        register_stage_failure("summary", url_id, article_url, str(e), failure_tracker, tb)
        return False


# ============================================================================
# MAIN PROCESSING FUNCTIONS
# ============================================================================

def fetch_pending_urls_from_edge(
    stage: str,
    config: PipelineConfig,
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fetch pending URLs from Supabase edge function.
    
    Args:
        stage: Stage name
        config: Pipeline configuration
        
    Returns:
        List of pending URL records
    """
    endpoint = f"{config.edge_function_base_url.rstrip('/')}/get-pending-news-urls"
    effective_limit = limit or config.batch_limit
    params = {"stage": stage, "limit": str(effective_limit)}
    
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_key:
        logger.error("SUPABASE_KEY not found in environment")
        return []
    
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
        urls = payload.get("urls", [])
        logger.info(
            "Fetched %s pending URLs for stage %s (limit=%s)",
            len(urls),
            stage,
            effective_limit,
        )
        return urls
    except Exception as e:
        logger.error(f"Failed to fetch pending URLs: {e}")
        return []


def process_batch_concurrent(
    stage: str,
    urls: List[dict],
    client,
    config: PipelineConfig,
    checkpoint: CheckpointManager,
    browser_pool: BrowserPool,
    rate_limiter: RateLimiter,
    memory_monitor: MemoryMonitor,
    progress_tracker: ProgressTracker,
    failure_tracker: FailureTracker,
    ping_manager: TaskPingManager,
    max_workers: int = 10,
) -> None:
    """Process a batch of URLs concurrently.
    
    Args:
        stage: Stage name
        urls: List of URL records to process
        client: Supabase client
        config: Pipeline configuration
        checkpoint: Checkpoint manager
        browser_pool: Browser pool
        rate_limiter: Rate limiter
        memory_monitor: Memory monitor
        progress_tracker: Progress tracker
        failure_tracker: Failure tracker
        ping_manager: Per-task ping manager for watchdog enforcement
        max_workers: Maximum number of concurrent workers
    """
    if not urls:
        logger.warning("No URLs provided to process_batch_concurrent")
        return
    
    # Trust the edge function's database filtering - it already excludes completed articles
    # (e.g., facts_extracted_at IS NULL for facts stage)
    logger.info(f"✓ Processing {len(urls)} articles for stage: {stage} (pre-filtered by database)")
    
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        # Submit all tasks directly
        futures = {}
        
        for item in urls:
            raw_id = item.get("id")
            if not raw_id:
                logger.warning("Skipping record without id", {"item": item})
                continue
            article_id = str(raw_id)
            item["id"] = article_id  # normalize for downstream handlers
            article_url = item.get("url") or ""
            
            if failure_tracker.is_skipped(stage, article_id):
                logger.info(f"Skipping {article_id} for stage {stage} (marked as skipped this run)")
                continue
            
            if checkpoint.is_stage_complete(article_id, stage):
                logger.debug(f"Skipping already completed article ({stage}): {article_id}")
                continue
            
            ping_handle = ping_manager.create_handle(stage, article_id, article_url)
            if stage == "facts":
                future = executor.submit(
                    process_article_facts_stage,
                    item, client, config, checkpoint, browser_pool, rate_limiter, failure_tracker, ping_handle
                )
            elif stage == "knowledge":
                future = executor.submit(
                    process_article_knowledge_stage,
                    item, client, config, checkpoint, rate_limiter, failure_tracker, ping_handle
                )
            elif stage == "summary":
                future = executor.submit(
                    process_article_summary_stage,
                    item, client, config, checkpoint, rate_limiter, failure_tracker, ping_handle
                )
            else:
                logger.warning(f"Unknown stage: {stage}")
                continue
            
            ping_manager.track(future, ping_handle)
            futures[future] = {"item": item, "ping_handle": ping_handle}
        
        logger.info(f"Submitted {len(futures)} tasks to thread pool (workers={max_workers}), waiting for completion...")
        progress_tracker.total_articles += len(futures)
        
        # Process completed futures with heartbeat and timeout
        completed = 0
        start_time = time.time()
        last_heartbeat = time.time()
        heartbeat_interval = 30  # Log every 30 seconds if no article completes
        max_wait_time = 600  # 10 minutes max wait for any single task
        
        pending = set(futures.keys())
        
        while pending:
            # Detect stalled tasks before waiting for completions
            timed_out = ping_manager.collect_timeouts()
            for timed_out_future, handle in timed_out:
                if timed_out_future not in pending:
                    continue
                pending.remove(timed_out_future)
                metadata = futures.get(timed_out_future, {})
                item = metadata.get("item", {})
                article_id = handle.article_id
                article_url = handle.article_url or item.get("url", "")
                logger.error(
                    f"[{article_id}] {stage} stalled — no ping for {ping_manager.timeout_seconds}s. Skipping this article."
                )
                register_stage_failure(
                    stage,
                    article_id,
                    article_url,
                    f"Ping timeout ({ping_manager.timeout_seconds}s without heartbeat)",
                    failure_tracker,
                )
                failure_tracker.mark_skipped(stage, article_id)
                progress_tracker.increment(success=False)
                completed += 1
                ping_manager.release(timed_out_future)
                timed_out_future.cancel()
                # Attempt to cancel underlying work; even if it keeps running we no longer wait
            if not pending:
                break
            
            # Wait for first completion or timeout
            done, not_done = wait(pending, return_when=FIRST_COMPLETED, timeout=heartbeat_interval)
            
            if not done:
                # Timeout reached, no new tasks completed -> Log heartbeat
                logger.info(
                    f"⏳ Heartbeat: {completed}/{len(futures)} tasks completed in this batch, "
                    f"{len(pending)} still processing..."
                )
                last_heartbeat = time.time()
                
                # Check for overall timeout
                if time.time() - start_time > max_wait_time:
                    raise TimeoutError("Max wait time exceeded")
                continue
            
            # Process completed futures
            for future in done:
                pending.remove(future)
                metadata = futures[future]
                item = metadata["item"]
                ping_manager.release(future)
                completed += 1
                
                try:
                    success = future.result(timeout=5)  # 5 second timeout to get result
                    progress_tracker.increment(success=success)
                    
                    logger.info(f"✓ Task finished: {item.get('id')} ({completed}/{len(futures)})")
                    
                    # Reset heartbeat on completion
                    last_heartbeat = time.time()
                    
                    # Flush checkpoint periodically
                    if progress_tracker.processed_count % 10 == 0:
                        logger.debug("Flushing checkpoint...")
                        checkpoint.flush()
                        logger.debug("Checkpoint flushed")
                    
                    # Log progress
                    if progress_tracker.should_log(interval=10):
                        progress_tracker.log_progress(memory_monitor, rate_limiter, browser_pool)
                    
                except Exception as e:
                    logger.error(f"Future failed for {item.get('id')}: {e}")
                    progress_tracker.increment(success=False)
    
    except TimeoutError:
        logger.error(
            f"Timeout waiting for futures after {max_wait_time}s. "
            f"Completed {completed}/{len(futures)}, cancelling remaining tasks..."
        )
        # Cancel remaining futures
        for future in futures:
            if not future.done():
                future.cancel()
            ping_manager.release(future)
    
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt in batch processing, cancelling remaining tasks...")
        # Cancel all pending futures
        for future in futures:
            if not future.done():
                future.cancel()
            ping_manager.release(future)
        # Re-raise to propagate to outer handler
        raise
    
    finally:
        logger.info(f"Batch complete: {completed}/{len(futures)} tasks finished. Shutting down thread pool...")
        # Do not wait for threads to exit, we already waited for tasks
        executor.shutdown(wait=False)
        logger.info("Thread pool shutdown initiated")


def run_backlog_processor(args) -> None:
    """Main backlog processor entry point.
    
    Args:
        args: Parsed command-line arguments
    """
    # Load environment and setup logging
    load_env()
    setup_logging()
    
    logger.info("Starting backlog processor", {
        "stage": args.stage,
        "workers": args.workers,
        "batch_size": args.batch_size,
        "limit": args.limit,
        "max_memory_percent": args.max_memory_percent,
        "max_browsers": args.max_browsers,
        "resume": args.resume,
        "retry_failures": args.retry_failures,
    })
    
    # Build config
    env = dict(os.environ)
    config = build_config(env, fact_llm_override=args.facts_llm_model)
    config.batch_limit = args.batch_size

    if args.facts_llm_model:
        logger.info(
            "Facts LLM override enabled",
            {"model": args.facts_llm_model},
        )
    logger.info("Active fact LLM model", {"model": config.fact_llm_model})
    
    # Initialize components
    client = get_supabase_client()
    checkpoint = CheckpointManager(args.checkpoint_file)
    rate_limiter = RateLimiter(rate_per_minute=30)  # Gemini limit
    browser_pool = BrowserPool(max_browsers=args.max_browsers)
    memory_monitor = MemoryMonitor(
        max_percent=args.max_memory_percent,
        check_interval=10
    )
    memory_monitor.set_browser_pool(browser_pool)
    failure_tracker = FailureTracker()
    ping_manager = TaskPingManager(timeout_seconds=args.ping_timeout)
    
    # Start memory monitor
    memory_monitor.start()
    
    try:
        # Validate checkpoint if resuming
        if args.resume and Path(args.checkpoint_file).exists():
            logger.info("Resuming from checkpoint...")
            validation = checkpoint.validate_integrity(client, sample_rate=0.1)
            logger.info(
                f"Checkpoint validation: {validation['validated']} articles checked, "
                f"{validation['valid_rate']:.1f}% valid"
            )
            if validation['invalid']:
                logger.warning(f"Invalid checkpoint entries: {validation['invalid'][:10]}")
        
        # Handle retry failures mode
        if args.retry_failures:
            failures_path = Path(".backlog_failures.json")
            retry_ids_by_stage = failure_tracker.load(failures_path)
            
            if not retry_ids_by_stage:
                logger.info("No failures to retry")
                return
            
            # Process each stage's failures
            for stage, article_ids in retry_ids_by_stage.items():
                if args.stage != "full" and args.stage != stage:
                    continue
                
                logger.info(f"Retrying {len(article_ids)} failed articles for stage: {stage}")
                
                # Fetch article details
                response = (
                    client.table("news_urls")
                    .select("id,url")
                    .in_("id", article_ids)
                    .execute()
                )
                urls = getattr(response, "data", []) or []
                
                progress_tracker = ProgressTracker(len(urls), stage)
                
                process_batch_concurrent(
                    stage, urls, client, config, checkpoint, browser_pool,
                    rate_limiter, memory_monitor, progress_tracker, failure_tracker,
                    ping_manager,
                    max_workers=args.workers
                )
                
                progress_tracker.log_summary(memory_monitor)
            
            return
        
        # Normal processing mode
        stages = ["content", "facts", "knowledge", "summary"] if args.stage == "full" else [args.stage]
        
        for stage in stages:
            logger.info(f"Processing stage: {stage}")
            
            # Initialize progress tracker (will update total as we fetch batches)
            progress_tracker = ProgressTracker(0, stage)
            batch_number = 0
            total_processed = 0

            stage_prefetch_limit = args.prefetch_size
            if stage_prefetch_limit <= 0:
                stage_prefetch_limit = args.limit or (args.batch_size * 5)
            stage_prefetch_limit = max(args.batch_size, stage_prefetch_limit)
            stage_prefetch_limit = min(stage_prefetch_limit, MAX_EDGE_FETCH_LIMIT)
            pending_cache = PendingUrlCache(stage, config, stage_prefetch_limit)
            logger.info(
                "Pending cache configured",
                {
                    "stage": stage,
                    "fetch_window": stage_prefetch_limit,
                    "batch_size": args.batch_size,
                },
            )
            
            # Loop until no more pending URLs or limit reached
            while True:
                # Check if limit reached
                if args.limit and total_processed >= args.limit:
                    logger.info(f"Limit reached: {args.limit} articles processed for stage: {stage}")
                    break
                
                batch_number += 1

                remaining_limit = args.limit - total_processed if args.limit else None

                def _should_skip(item: dict) -> bool:
                    article_id = item.get("id")
                    if not article_id:
                        return True
                    if failure_tracker.is_skipped(stage, str(article_id)):
                        return True
                    return checkpoint.is_stage_complete(str(article_id), stage)

                urls = pending_cache.next_batch(
                    args.batch_size,
                    limit_remaining=remaining_limit,
                    skip_predicate=_should_skip,
                )

                if not urls:
                    logger.info(f"Pending cache depleted for stage: {stage} (batch #{batch_number})")
                    break
                
                logger.info(
                    f"Batch #{batch_number}: Prepared {len(urls)} cached URLs for stage: {stage}"
                )
                
                # Process batch
                process_batch_concurrent(
                    stage, urls, client, config, checkpoint, browser_pool,
                    rate_limiter, memory_monitor, progress_tracker, failure_tracker,
                    ping_manager,
                    max_workers=args.workers
                )
                
                # Update total processed count
                total_processed += len(urls)
                
                # Checkpoint flush after each batch
                checkpoint.flush()
                
                # Log batch summary
                limit_str = f"/{args.limit}" if args.limit else ""
                logger.info(
                    f"Batch #{batch_number} complete. "
                    f"Progress: {total_processed}{limit_str} articles fetched, "
                    f"{progress_tracker.processed_count}/{progress_tracker.total_articles} processed"
                )
            
            # Final checkpoint flush
            checkpoint.flush()
            
            # Log summary
            progress_tracker.log_summary(memory_monitor)
        
        # Log rate limiter stats (outside stage loop to avoid hanging)
        try:
            rate_stats = rate_limiter.get_stats()
            logger.info(f"Rate limiter stats: {rate_stats}")
        except Exception as e:
            logger.warning(f"Could not get rate limiter stats: {e}")
        
        # Save failures
        failures_path = Path(".backlog_failures.json")
        failure_tracker.save(failures_path)
        
        # Log final summary
        failure_summary = failure_tracker.get_summary()
        logger.info(f"Processing complete. Failures by stage: {failure_summary}")
        logger.info(f"Checkpoint saved to: {args.checkpoint_file}")
        logger.info(f"Failures saved to: {failures_path}")
        
        if not args.archive:
            logger.info("Files preserved for review. Run with --archive to backup and clean up.")
        else:
            # Archive checkpoint
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            checkpoint_archive = checkpoint.archive(timestamp)
            if checkpoint_archive:
                logger.info(f"Checkpoint archived to: {checkpoint_archive}")
            
            # Archive failures
            if failures_path.exists():
                import shutil
                failures_archive = failures_path.with_name(
                    f"{failures_path.stem}_{timestamp}{failures_path.suffix}"
                )
                shutil.copy2(failures_path, failures_archive)
                logger.info(f"Failures archived to: {failures_archive}")
        
        # Processing complete - cleanup and exit
        logger.info("Main processing complete, shutting down...")
        
        # Stop memory monitor first and wait for it to finish
        memory_monitor.stop()
        if memory_monitor.is_alive():
            memory_monitor.join(timeout=3)
            if memory_monitor.is_alive():
                logger.warning("Memory monitor did not stop cleanly")
        
        # Then shutdown browser pool
        browser_pool.shutdown()
        logger.info("Shutdown complete")
        os._exit(0)
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        # Fall through to finally block for cleanup
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Fall through to finally block for cleanup
    
    finally:
        # Cleanup - ensure this always runs
        try:
            logger.info("Starting cleanup...")
            
            # Stop memory monitor
            try:
                memory_monitor.stop()
                # Wait briefly for memory monitor thread to stop
                if memory_monitor.is_alive():
                    memory_monitor.join(timeout=2)
            except Exception as e:
                logger.warning(f"Error stopping memory monitor: {e}")
            
            # Shutdown browser pool
            try:
                browser_pool.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down browser pool: {e}")
            
            logger.info("Backlog processor shutdown complete")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            # Force exit to ensure all threads are terminated
            os._exit(0)


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="High-throughput backlog processor for content pipeline. "
                    "Optimized for processing 1000+ articles with concurrent workers, "
                    "adaptive memory management, and checkpoint/resume support."
    )
    
    parser.add_argument(
        "--stage",
        choices=["content", "facts", "knowledge", "summary", "full"],
        default="facts",
        help="Pipeline stage to process (default: facts)"
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        default=15,
        help="Initial number of concurrent workers (default: 15)"
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of articles to fetch per batch (default: 100)"
    )

    parser.add_argument(
        "--prefetch-size",
        type=int,
        default=0,
        help=(
            "Number of pending URLs to fetch per request when caching backlog IDs locally. "
            "Defaults to 0, which auto-scales to max(--limit, batch_size * 5)."
        ),
    )

    parser.add_argument(
        "--facts-llm-model",
        default=None,
        help=(
            "Override the fact extraction LLM model for backlog runs. "
            "Defaults to FACT_LLM_MODEL env var or gemma-3n-e4b-it when unset."
        ),
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum total articles to process (default: unlimited). Useful for testing."
    )
    
    parser.add_argument(
        "--checkpoint-file",
        default=".backlog_checkpoint.json",
        help="Path to checkpoint file (default: .backlog_checkpoint.json)"
    )
    
    parser.add_argument(
        "--max-memory-percent",
        type=int,
        default=80,
        help="Maximum memory usage percent before scaling down workers (default: 80)"
    )
    
    parser.add_argument(
        "--max-browsers",
        type=int,
        default=5,
        help="Maximum concurrent Playwright browser instances (default: 5)"
    )

    parser.add_argument(
        "--ping-timeout",
        type=int,
        default=90,
        help="Seconds without a task ping before declaring it stalled (default: 90)"
    )
    
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint, skipping completed articles"
    )
    
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="Retry previously failed articles from .backlog_failures.json"
    )
    
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Archive checkpoint and failures to timestamped backups after completion"
    )
    
    args = parser.parse_args()
    
    try:
        run_backlog_processor(args)
        # run_backlog_processor handles its own cleanup and calls os._exit(0)
        # If we reach here, something went wrong - force exit anyway
        os._exit(0)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        os._exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        os._exit(1)


if __name__ == "__main__":
    main()
