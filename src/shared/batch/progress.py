"""Progress tracking for batch processing pipelines."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger(__name__)


class ProgressTracker:
    """Tracks processing progress and calculates metrics.
    
    Provides real-time progress logging with rate calculation, ETA estimation,
    and optional memory monitoring.
    
    Example:
        tracker = ProgressTracker(total_articles=1000, stage="facts")
        
        for article in articles:
            try:
                process_article(article)
                tracker.increment(success=True)
            except Exception:
                tracker.increment(success=False)
            
            if tracker.should_log():
                tracker.log_progress()
        
        tracker.log_summary()
    """

    def __init__(
        self,
        total_articles: int,
        stage: str,
        *,
        log_interval: int = 10,
        log_time_interval: int = 30,
    ):
        """Initialize progress tracker.

        Args:
            total_articles: Total number of articles to process
            stage: Current stage name
            log_interval: Number of articles between logs
            log_time_interval: Seconds between time-based logs
        """
        self.total_articles = total_articles
        self.stage = stage
        self.log_interval = log_interval
        self.log_time_interval = log_time_interval
        
        self.start_time = time.time()
        self.processed_count = 0
        self.success_count = 0
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
            if success:
                self.success_count += 1
            else:
                self.error_count += 1

    def should_log(self) -> bool:
        """Check if progress should be logged.

        Returns:
            True if should log now
        """
        with self.lock:
            count_trigger = self.processed_count - self.last_log_count >= self.log_interval
            time_trigger = time.time() - self.last_log_time >= self.log_time_interval
            return count_trigger or time_trigger

    def log_progress(
        self,
        extra_stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log current progress with all metrics.

        Args:
            extra_stats: Optional additional stats to include in log
        """
        with self.lock:
            elapsed_hours = (time.time() - self.start_time) / 3600
            rate = self.processed_count / elapsed_hours if elapsed_hours > 0 else 0

            remaining = self.total_articles - self.processed_count
            eta_hours = remaining / rate if rate > 0 else 0

            percent = (
                (self.processed_count / self.total_articles * 100)
                if self.total_articles > 0
                else 0
            )

            # Build log message
            parts = [
                f"Progress: {self.processed_count:,}/{self.total_articles:,} ({percent:.1f}%)",
                f"Rate: {rate:.0f} art/h",
            ]

            # Add memory if psutil available
            if HAS_PSUTIL:
                memory = psutil.virtual_memory()
                parts.append(
                    f"Memory: {memory.percent:.0f}% ({memory.used / (1024**3):.1f}/{memory.total / (1024**3):.1f}GB)"
                )

            # Add extra stats if provided
            if extra_stats:
                for key, value in extra_stats.items():
                    if isinstance(value, float):
                        parts.append(f"{key}: {value:.1f}")
                    else:
                        parts.append(f"{key}: {value}")

            parts.extend([
                f"Errors: {self.error_count}",
                f"ETA: {eta_hours:.1f}h",
                f"Stage: {self.stage}",
            ])

            logger.info(" | ".join(parts))

            self.last_log_time = time.time()
            self.last_log_count = self.processed_count

    def log_summary(self) -> None:
        """Log final summary."""
        elapsed_hours = (time.time() - self.start_time) / 3600
        rate = self.processed_count / elapsed_hours if elapsed_hours > 0 else 0

        summary_parts = [
            f"Total processed: {self.processed_count:,}",
            f"Successful: {self.success_count:,}",
            f"Errors: {self.error_count:,}",
            f"Time: {elapsed_hours:.1f}h",
            f"Avg rate: {rate:.0f} art/h",
            f"Stage: {self.stage}",
        ]

        if HAS_PSUTIL:
            memory = psutil.virtual_memory()
            summary_parts.append(f"Final memory: {memory.percent:.0f}%")

        logger.info("Batch Processing Complete:\n  " + "\n  ".join(summary_parts))

    def get_stats(self) -> Dict[str, Any]:
        """Get current progress statistics.

        Returns:
            Dict with progress metrics
        """
        with self.lock:
            elapsed_hours = (time.time() - self.start_time) / 3600
            rate = self.processed_count / elapsed_hours if elapsed_hours > 0 else 0
            remaining = self.total_articles - self.processed_count
            eta_hours = remaining / rate if rate > 0 else 0

            return {
                "processed": self.processed_count,
                "successful": self.success_count,
                "errors": self.error_count,
                "total": self.total_articles,
                "percent": (
                    self.processed_count / self.total_articles * 100
                    if self.total_articles > 0
                    else 0
                ),
                "rate_per_hour": rate,
                "elapsed_hours": elapsed_hours,
                "eta_hours": eta_hours,
                "stage": self.stage,
            }
