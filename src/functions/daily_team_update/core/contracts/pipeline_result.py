"""Result models for the daily team update pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class FailureDetail(BaseModel):
    """Represents a failure encountered during a pipeline stage."""

    stage: str = Field(..., description="Name of the stage that failed")
    message: str = Field(..., description="Human readable error message")
    retryable: bool = Field(
        default=False,
        description="Whether the failure is likely recoverable on a retry",
    )
    raw: Optional[Dict[str, object]] = Field(
        default=None,
        description="Optional raw payload captured with the failure",
    )

    @field_validator("stage")
    @classmethod
    def _validate_stage(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "stage must be a non-empty string"
            raise ValueError(msg)
        return cleaned


class TeamProcessingResult(BaseModel):
    """Represents the outcome for a single team processed by the pipeline."""

    team_id: Optional[str] = Field(
        default=None,
        description="Database identifier for the team if available",
    )
    team_abbr: str = Field(..., min_length=2, max_length=5)
    team_name: Optional[str] = Field(
        default=None,
        description="Friendly team name used for logging and analytics",
    )
    status: str = Field(
        default="skipped",
        description="Outcome status (success|failed|no_news|skipped)",
    )
    urls_processed: int = Field(default=0, ge=0)
    summaries_generated: int = Field(default=0, ge=0)
    article_generated: bool = Field(default=False)
    translation_generated: bool = Field(default=False)
    images_selected: int = Field(default=0, ge=0)
    article_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of language code to persisted article ID",
    )
    durations: Dict[str, float] = Field(
        default_factory=dict,
        description="Elapsed time (seconds) recorded per pipeline stage",
    )
    errors: List[FailureDetail] = Field(default_factory=list)

    def add_stage_duration(self, stage: str, duration: float) -> None:
        """Record the elapsed time for a stage."""

        if duration < 0:
            return
        self.durations[stage] = round(duration, 4)

    def add_error(self, detail: FailureDetail) -> None:
        """Attach a failure detail to the result."""

        self.errors.append(detail)
        if self.status == "success":
            self.status = "failed"

    def mark_success(
        self,
        *,
        summaries: int,
        images: int,
        article_ids: Optional[Dict[str, str]] = None,
    ) -> None:
        """Mark the result as successful with summary counts."""

        self.status = "success"
        self.summaries_generated = summaries
        self.images_selected = images
        if article_ids:
            self.article_ids.update(article_ids)
        self.article_generated = bool(article_ids and article_ids.get("en"))
        self.translation_generated = bool(article_ids and article_ids.get("de"))


class PipelineMetrics(BaseModel):
    """Aggregated numeric metrics for a pipeline run."""

    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = Field(default=None)
    total_urls: int = Field(default=0, ge=0)
    total_summaries: int = Field(default=0, ge=0)
    total_articles: int = Field(default=0, ge=0)
    total_translations: int = Field(default=0, ge=0)
    total_images: int = Field(default=0, ge=0)
    stage_durations: Dict[str, float] = Field(default_factory=dict)

    def set_end_time(self) -> None:
        """Mark the end time of the pipeline run."""

        self.end_time = datetime.utcnow()

    def record_stage_duration(self, stage: str, duration: float) -> None:
        """Record duration for a named stage."""

        if duration < 0:
            return
        self.stage_durations[stage] = round(duration, 4)

    @property
    def duration_seconds(self) -> float:
        """Return total runtime in seconds."""

        if not self.end_time:
            return 0.0
        delta = self.end_time - self.start_time
        return round(delta.total_seconds(), 4)


class PipelineResult(BaseModel):
    """Container for the overall pipeline execution outcome."""

    requested_teams: int = Field(default=0, ge=0)
    processed_teams: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    config_snapshot: Dict[str, object] = Field(default_factory=dict)
    results: List[TeamProcessingResult] = Field(default_factory=list)
    metrics: PipelineMetrics = Field(default_factory=PipelineMetrics)
    error_records: List[Dict[str, object]] = Field(default_factory=list)

    def add_result(self, result: TeamProcessingResult) -> None:
        """Add a team result and update counters."""

        self.results.append(result)
        self.processed_teams = len(self.results)
        if result.status == "success":
            self.success_count += 1
        elif result.status == "failed":
            self.failure_count += 1
        else:
            self.skipped_count += 1

    def to_dict(self) -> Dict[str, object]:
        """Return a JSON-serialisable representation."""

        metrics_dump = self.metrics.model_dump()
        start_time = metrics_dump.get("start_time")
        end_time = metrics_dump.get("end_time")
        if start_time is not None:
            metrics_dump["start_time"] = start_time.isoformat()
        if end_time is not None:
            metrics_dump["end_time"] = end_time.isoformat()

        payload: Dict[str, object] = {
            "requested_teams": self.requested_teams,
            "processed_teams": self.processed_teams,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skipped_count": self.skipped_count,
            "config": self.config_snapshot,
            "metrics": {**metrics_dump, "duration_seconds": self.metrics.duration_seconds},
            "results": [result.model_dump() for result in self.results],
            "errors": self.error_records,
        }
        return payload
