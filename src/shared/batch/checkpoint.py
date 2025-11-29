"""Checkpoint manager for per-article, per-stage tracking with atomic writes."""

from __future__ import annotations

import json
import logging
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Manages per-article, per-stage checkpoint with atomic writes and validation.
    
    Provides persistence for batch processing pipelines to resume from failures.
    Each article can have multiple stages tracked independently.
    
    Example:
        checkpoint = CheckpointManager("./checkpoints/run_001.json")
        
        for article in articles:
            if checkpoint.is_stage_complete(article.id, "facts"):
                continue
            
            # Process article...
            checkpoint.mark_stage_complete(article.id, "facts")
            checkpoint.flush()  # Persist to disk
    """

    CHECKPOINT_VERSION = "1.0"
    DEFAULT_STAGES = ["content", "facts", "knowledge", "summary"]

    def __init__(
        self,
        filepath: str,
        *,
        stages: Optional[List[str]] = None,
    ):
        """Initialize checkpoint manager.

        Args:
            filepath: Path to checkpoint JSON file
            stages: List of valid stage names (defaults to content/facts/knowledge/summary)
        """
        self.filepath = Path(filepath)
        self.stages = stages or self.DEFAULT_STAGES
        self.data: Dict[str, Any] = {
            "version": self.CHECKPOINT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "articles": {},
        }
        self.lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Load checkpoint from file if exists."""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r") as f:
                    loaded = json.load(f)
                    if loaded.get("version") == self.CHECKPOINT_VERSION:
                        self.data = loaded
                        logger.info(
                            "Loaded checkpoint from %s",
                            self.filepath,
                            extra={
                                "articles": len(self.data.get("articles", {})),
                                "created_at": self.data.get("created_at"),
                            },
                        )
                    else:
                        logger.warning("Checkpoint version mismatch, starting fresh")
            except Exception as e:
                logger.error("Failed to load checkpoint: %s", e)

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
                self.data["articles"][article_id] = {s: None for s in self.stages}

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
                article_id
                for article_id in candidate_ids
                if not self.is_stage_complete(article_id, stage)
            ]

    def flush(self) -> None:
        """Atomically write checkpoint to disk."""
        with self.lock:
            try:
                # Write to temp file first
                temp_path = self.filepath.with_suffix(".tmp")
                with open(temp_path, "w") as f:
                    json.dump(self.data, f, indent=2)

                # Atomic rename
                temp_path.replace(self.filepath)
                logger.debug("Checkpoint flushed to %s", self.filepath)
            except Exception as e:
                logger.error("Failed to flush checkpoint: %s", e)

    def validate_integrity(
        self,
        validator: Callable[[str, str], bool],
        sample_rate: float = 0.1,
    ) -> Dict[str, Any]:
        """Validate checkpoint integrity by sampling with a custom validator.

        Args:
            validator: Function(article_id, stage) -> bool that checks if data exists
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
            for stage, completed_at in stages.items():
                if completed_at and not validator(article_id, stage):
                    invalid.append(f"{article_id}:{stage}")

        valid_rate = ((sample_size - len(invalid)) / sample_size * 100) if sample_size > 0 else 100.0

        return {
            "validated": sample_size,
            "invalid": invalid,
            "valid_rate": valid_rate,
        }

    def archive(self, timestamp: str) -> Optional[Path]:
        """Create timestamped backup of checkpoint.

        Args:
            timestamp: Timestamp string for archive filename

        Returns:
            Path to archive file or None if failed
        """
        if not self.filepath.exists():
            return None

        archive_path = self.filepath.with_name(
            f"{self.filepath.stem}_{timestamp}{self.filepath.suffix}"
        )

        try:
            import shutil

            shutil.copy2(self.filepath, archive_path)
            logger.info("Checkpoint archived to %s", archive_path)
            return archive_path
        except Exception as e:
            logger.error("Failed to archive checkpoint: %s", e)
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get checkpoint statistics.

        Returns:
            Dict with article counts and stage completion stats
        """
        with self.lock:
            articles = self.data["articles"]
            stage_counts = {stage: 0 for stage in self.stages}

            for article_id, stages in articles.items():
                for stage, completed_at in stages.items():
                    if completed_at and stage in stage_counts:
                        stage_counts[stage] += 1

            return {
                "total_articles": len(articles),
                "stage_counts": stage_counts,
                "created_at": self.data.get("created_at"),
                "last_updated": self.data.get("last_updated"),
            }

    def clear(self) -> None:
        """Clear all checkpoint data."""
        with self.lock:
            self.data = {
                "version": self.CHECKPOINT_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "articles": {},
            }
            logger.info("Checkpoint cleared")
