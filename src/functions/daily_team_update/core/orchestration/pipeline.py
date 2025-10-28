"""Pipeline entry point orchestrating all teams."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Sequence

from ..contracts.config import PipelineConfig
from ..contracts.pipeline_result import PipelineResult
from ..db.team_reader import TeamReader
from ..monitoring.error_handler import ErrorHandler
from ..monitoring.metrics_collector import MetricsCollector
from .parallel_executor import ParallelExecutor
from .team_processor import TeamProcessor

logger = logging.getLogger(__name__)


class Pipeline:
    """Coordinates fetching teams and delegating processing to TeamProcessor."""

    def __init__(
        self,
        *,
        team_reader: TeamReader,
        team_processor: TeamProcessor,
        metrics: MetricsCollector,
        errors: ErrorHandler,
        config: PipelineConfig,
    ) -> None:
        self._reader = team_reader
        self._processor = team_processor
        self._metrics = metrics
        self._errors = errors
        self._config = config

    def run(self, team_filter: Optional[Sequence[str]] = None) -> PipelineResult:
        """Execute the pipeline returning a structured result."""

        normalised_filter: Optional[list[str]] = None
        if team_filter:
            normalised_filter = [abbr.upper() for abbr in team_filter if isinstance(abbr, str) and abbr.strip()]
        if normalised_filter:
            teams = self._reader.fetch_all(normalised_filter)
        else:
            logger.info("No team filter supplied; loading all teams from Supabase")
            teams = self._reader.fetch_all()

        logger.info("Starting pipeline for %s teams", len(teams))

        start_time = datetime.utcnow()
        pipeline_result = PipelineResult(
            requested_teams=len(normalised_filter or teams),
            config_snapshot={**self._config.snapshot(), "team_filter": normalised_filter},
        )

        if not teams:
            metrics_snapshot = self._metrics.build_snapshot()
            metrics_snapshot.start_time = start_time
            metrics_snapshot.set_end_time()
            pipeline_result.metrics = metrics_snapshot
            pipeline_result.error_records = self._errors.as_dict()
            return pipeline_result

        if self._config.run_parallel and len(teams) > 1:
            executor = ParallelExecutor(self._config.max_workers)
            for _, result in executor.execute(teams, self._processor.process):
                pipeline_result.add_result(result)
        else:
            for team in teams:
                result = self._processor.process(team)
                pipeline_result.add_result(result)

        metrics_snapshot = self._metrics.build_snapshot()
        metrics_snapshot.start_time = start_time
        metrics_snapshot.set_end_time()
        pipeline_result.metrics = metrics_snapshot
        pipeline_result.error_records = self._errors.as_dict()
        return pipeline_result
