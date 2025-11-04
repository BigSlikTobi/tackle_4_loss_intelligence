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
        """Execute the pipeline returning a structured result with automatic retry for incomplete teams."""

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

        # First pass: Process all teams
        logger.info("=== FIRST PASS: Processing all %d teams ===", len(teams))
        team_results_map = {}  # Map team_abbr to result for retry lookup
        
        if self._config.run_parallel and len(teams) > 1:
            executor = ParallelExecutor(self._config.max_workers)
            for team, result in executor.execute(teams, self._processor.process):
                pipeline_result.add_result(result)
                team_results_map[result.team_abbr] = result
        else:
            for team in teams:
                result = self._processor.process(team)
                pipeline_result.add_result(result)
                team_results_map[result.team_abbr] = result

        # Retry incomplete teams up to 3 times
        max_retry_attempts = 3
        total_retries = 0
        
        for retry_attempt in range(1, max_retry_attempts + 1):
            # Identify incomplete teams that need retry
            incomplete_results = [
                (team, team_results_map[team.abbreviation])
                for team in teams
                if team_results_map[team.abbreviation].status == "incomplete"
            ]
            
            if not incomplete_results:
                break  # All teams complete
                
            logger.warning(
                "=== RETRY PASS %d/%d: %d teams have incomplete results ===",
                retry_attempt,
                max_retry_attempts,
                len(incomplete_results)
            )
            
            for team, cached_result in incomplete_results:
                logger.info(
                    "Retrying team %s (attempt %d) - cached: %d URLs, %d extracted, %d summaries",
                    team.abbreviation,
                    retry_attempt,
                    len(cached_result.cached_urls),
                    len(cached_result.cached_extracted),
                    len(cached_result.cached_summaries)
                )
                
                # Retry with cached intermediate results
                retry_result = self._processor.process(team, cached_result=cached_result)
                
                # Replace the original incomplete result
                original_index = pipeline_result.results.index(cached_result)
                pipeline_result.results[original_index] = retry_result
                
                # Update the map
                team_results_map[team.abbreviation] = retry_result
                
                # Update counters
                if retry_result.status == "success":
                    logger.info(
                        "✅ Team %s retry SUCCESS on attempt %d - now complete with article, translation, and %d images",
                        team.abbreviation,
                        retry_attempt,
                        retry_result.images_selected
                    )
                    pipeline_result.incomplete_count -= 1
                    pipeline_result.success_count += 1
                elif retry_result.status == "incomplete":
                    logger.warning(
                        "⚠️  Team %s still INCOMPLETE after attempt %d - missing: %s",
                        team.abbreviation,
                        retry_attempt,
                        ", ".join([
                            "article" if not retry_result.article_generated else "",
                            "translation" if not retry_result.translation_generated else "",
                            "images" if retry_result.images_selected == 0 else ""
                        ]).strip(", ")
                    )
                else:
                    logger.error(
                        "❌ Team %s retry FAILED on attempt %d with status: %s",
                        team.abbreviation,
                        retry_attempt,
                        retry_result.status
                    )
                    pipeline_result.incomplete_count -= 1
                    pipeline_result.failure_count += 1
                
                total_retries += 1
                
        pipeline_result.retry_count = total_retries
        
        # Final summary of incomplete teams
        still_incomplete = [
            r for r in pipeline_result.results
            if r.status == "incomplete"
        ]
        
        failed_results = [
            r for r in pipeline_result.results
            if r.status == "failed"
        ]

        if still_incomplete:
            logger.error(
                "PIPELINE INCOMPLETE: %d teams still incomplete after %d retry attempts: %s",
                len(still_incomplete),
                max_retry_attempts,
                ", ".join(r.team_abbr for r in still_incomplete)
            )
            for incomplete in still_incomplete:
                logger.error(
                    "  - %s: %s",
                    incomplete.team_abbr,
                    "; ".join(e.message for e in incomplete.errors[-3:])  # Last 3 errors
                )
        elif failed_results:
            logger.error(
                "PIPELINE FAILED: %d teams failed processing: %s",
                len(failed_results),
                ", ".join(r.team_abbr for r in failed_results)
            )
            for failed in failed_results:
                if failed.errors:
                    logger.error(
                        "  - %s: %s",
                        failed.team_abbr,
                        "; ".join(e.message for e in failed.errors[-3:])
                    )
        else:
            logger.info("✅ All teams processed successfully")

        metrics_snapshot = self._metrics.build_snapshot()
        metrics_snapshot.start_time = start_time
        metrics_snapshot.set_end_time()
        pipeline_result.metrics = metrics_snapshot
        pipeline_result.error_records = self._errors.as_dict()
        
        # Final summary
        logger.info(
            "PIPELINE COMPLETE: success=%d, incomplete=%d, failed=%d, skipped=%d, retries=%d",
            pipeline_result.success_count,
            pipeline_result.incomplete_count,
            pipeline_result.failure_count,
            pipeline_result.skipped_count,
            pipeline_result.retry_count
        )
        
        return pipeline_result
