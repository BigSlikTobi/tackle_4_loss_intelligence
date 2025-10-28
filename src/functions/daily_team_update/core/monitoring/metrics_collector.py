"""Metrics collection utilities for the daily team update pipeline."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict

from ..contracts.pipeline_result import PipelineMetrics, TeamProcessingResult


@dataclass
class _MutableMetrics:
    total_urls: int = 0
    total_summaries: int = 0
    total_articles: int = 0
    total_translations: int = 0
    total_images: int = 0


class MetricsCollector:
    """Aggregates counters across pipeline stages with thread safety."""

    def __init__(self) -> None:
        self._metrics = _MutableMetrics()
        self._stage_durations: Dict[str, float] = {}
        self._lock = threading.Lock()

    def record_team(self, result: TeamProcessingResult) -> None:
        """Accumulate metrics from a team result."""

        with self._lock:
            self._metrics.total_urls += result.urls_processed
            self._metrics.total_summaries += result.summaries_generated
            if result.article_generated:
                self._metrics.total_articles += 1
            if result.translation_generated:
                self._metrics.total_translations += 1
            self._metrics.total_images += result.images_selected
            for stage, duration in result.durations.items():
                current = self._stage_durations.get(stage, 0.0)
                self._stage_durations[stage] = round(current + duration, 4)

    def build_snapshot(self) -> PipelineMetrics:
        """Produce an immutable snapshot for reporting."""

        metrics = PipelineMetrics()
        metrics.total_urls = self._metrics.total_urls
        metrics.total_summaries = self._metrics.total_summaries
        metrics.total_articles = self._metrics.total_articles
        metrics.total_translations = self._metrics.total_translations
        metrics.total_images = self._metrics.total_images
        metrics.stage_durations = dict(self._stage_durations)
        return metrics
