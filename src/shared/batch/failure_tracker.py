"""Failure tracking for batch processing with retry support."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Default max attempts before skipping an article for the rest of a run
DEFAULT_MAX_ATTEMPTS = 3


class FailureTracker:
    """Tracks failed articles for retry and analysis.
    
    Records failures with full context (error message, traceback, timestamp)
    and supports retry limiting to prevent infinite loops on persistent errors.
    
    Example:
        tracker = FailureTracker()
        
        try:
            process_article(article)
        except Exception as e:
            attempts = tracker.record_failure(
                stage="facts",
                article_id=article.id,
                url=article.url,
                error=str(e),
                tb=traceback.format_exc(),
            )
            if attempts >= 3:
                tracker.mark_skipped("facts", article.id)
        
        # Save failures for analysis
        tracker.save(Path("./failures.json"))
    """

    def __init__(self, max_attempts: int = DEFAULT_MAX_ATTEMPTS):
        """Initialize failure tracker.
        
        Args:
            max_attempts: Max attempts before marking article as skipped
        """
        self.max_attempts = max_attempts
        self.failures: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.lock = threading.Lock()
        self.attempt_counts: Dict[str, Dict[str, int]] = defaultdict(dict)
        self.skipped_articles: Dict[str, Set[str]] = defaultdict(set)

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
        tb: str = "",
    ) -> int:
        """Record a processing failure.

        Args:
            stage: Stage name
            article_id: Article ID
            url: Article URL
            error: Error message
            tb: Traceback string

        Returns:
            Number of attempts for this article/stage
        """
        with self.lock:
            attempt_count = self._increment_attempt(stage, article_id)
            self.failures[stage].append(
                {
                    "article_id": article_id,
                    "url": url,
                    "error": str(error),
                    "traceback": tb,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "attempt": attempt_count,
                }
            )
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
                temp_path = filepath.with_suffix(".tmp")
                with open(temp_path, "w") as f:
                    json.dump(dict(self.failures), f, indent=2)
                temp_path.replace(filepath)

                total_failures = sum(len(v) for v in self.failures.values())
                logger.info("Saved %d failures to %s", total_failures, filepath)
            except Exception as e:
                logger.error("Failed to save failures: %s", e)

    def load(self, filepath: Path) -> Dict[str, List[str]]:
        """Load failures from JSON file and extract article IDs by stage.

        Args:
            filepath: Path to failures file

        Returns:
            Dict mapping stage to list of article IDs
        """
        if not filepath.exists():
            logger.warning("Failures file not found: %s", filepath)
            return {}

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            article_ids_by_stage = {}
            for stage, failures in data.items():
                article_ids_by_stage[stage] = [f["article_id"] for f in failures]

            total_failures = sum(len(v) for v in article_ids_by_stage.values())
            logger.info("Loaded %d failures from %s", total_failures, filepath)
            return article_ids_by_stage
        except Exception as e:
            logger.error("Failed to load failures: %s", e)
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

    def clear(self) -> None:
        """Clear all failure data."""
        with self.lock:
            self.failures.clear()
            self.attempt_counts.clear()
            self.skipped_articles.clear()
            logger.info("Failure tracker cleared")


def register_stage_failure(
    stage: str,
    article_id: str,
    article_url: str,
    message: str,
    failure_tracker: FailureTracker,
    tb: str = "",
    max_attempts: Optional[int] = None,
) -> None:
    """Record a failure and skip the article after max attempts.
    
    Convenience function that handles the common pattern of recording
    a failure and checking if the article should be skipped.

    Args:
        stage: Stage name
        article_id: Article ID  
        article_url: Article URL
        message: Error message
        failure_tracker: FailureTracker instance
        tb: Traceback string
        max_attempts: Override max attempts (uses tracker default if None)
    """
    article_id = str(article_id)
    attempts = failure_tracker.record_failure(stage, article_id, article_url, message, tb)
    
    max_att = max_attempts if max_attempts is not None else failure_tracker.max_attempts
    
    if attempts >= max_att:
        failure_tracker.mark_skipped(stage, article_id)
        logger.warning(
            "[%s] %s stage failed (%s). Reached %d attempts — skipping for the rest of this run.",
            article_id,
            stage,
            message,
            attempts,
        )
    else:
        remaining = max_att - attempts
        logger.info(
            "[%s] %s stage failed (%s). %d retry(s) remaining this run.",
            article_id,
            stage,
            message,
            remaining,
        )
