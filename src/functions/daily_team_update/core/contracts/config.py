"""Configuration models for the daily team update pipeline."""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator


class SupabaseSettings(BaseModel):
    """Settings required to interact with Supabase tables and functions."""

    url: HttpUrl = Field(..., description="Supabase project URL")
    key: str = Field(..., min_length=10, description="Supabase service role or anon key")
    schema: str = Field(default="public", description="Target database schema")
    team_table: str = Field(default="teams", description="Table containing team metadata")
    article_table: str = Field(
        default="team_article",
        description="Table used to store generated team articles",
    )
    article_on_conflict: Optional[str] = Field(
        default=None,
        description="Comma-separated columns or constraint name used for article upsert conflict handling",
    )
    relationship_table: str = Field(
        default="team_article_image",
        description="Table linking articles to images",
    )
    image_table: str = Field(
        default="article_images",
        description="Table storing individual image metadata",
    )
    news_function: str = Field(
        default="team-news-urls",
        description="Edge function used to retrieve team news URLs",
    )
    function_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout for Edge Function invocations in seconds",
    )


class ServiceEndpointConfig(BaseModel):
    """HTTP endpoint definition for an external service call."""

    url: HttpUrl
    timeout_seconds: int = Field(default=90, ge=5, le=300)
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key sent via X-API-Key header",
    )
    authorization: Optional[str] = Field(
        default=None,
        description="Optional Authorization header value",
    )
    additional_headers: Dict[str, str] = Field(default_factory=dict)

    def build_headers(self) -> Dict[str, str]:
        """Return headers that should be attached to the request."""

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.authorization:
            headers["Authorization"] = self.authorization
        headers.update(self.additional_headers)
        return headers


class ServiceCoordinatorConfig(BaseModel):
    """Aggregated configuration for orchestrated service dependencies."""

    content_extraction: Optional[ServiceEndpointConfig] = None
    summarization: Optional[ServiceEndpointConfig] = None
    article_generation: Optional[ServiceEndpointConfig] = None
    translation: Optional[ServiceEndpointConfig] = None
    image_selection: Optional[ServiceEndpointConfig] = None
    max_parallel_requests: int = Field(default=4, ge=1, le=16)

    def require(self, attribute: str) -> ServiceEndpointConfig:
        """Return endpoint configuration or raise a descriptive error."""

        endpoint: Optional[ServiceEndpointConfig] = getattr(self, attribute, None)
        if endpoint is None:
            msg = f"Missing endpoint configuration for '{attribute}'"
            raise ValueError(msg)
        return endpoint


class PipelineConfig(BaseModel):
    """Operational configuration for the pipeline run."""

    run_parallel: bool = Field(default=False)
    max_workers: int = Field(default=4, ge=1, le=16)
    continue_on_error: bool = Field(default=True)
    dry_run: bool = Field(default=False)
    image_count: int = Field(default=2, ge=0, le=6)
    target_language: str = Field(default="de", min_length=2, max_length=5)
    allow_empty_urls: bool = Field(
        default=False,
        description="If true, teams without news URLs are treated as success",
    )
    max_urls_per_team: Optional[int] = Field(
        default=10,
        ge=1,
        le=40,
        description="Optional cap on URLs processed per team to limit costs",
    )
    summarization_batch_size: int = Field(default=5, ge=1, le=20)

    @field_validator("image_count")
    @classmethod
    def _validate_image_count(cls, value: int) -> int:
        if value < 0:
            msg = "image_count cannot be negative"
            raise ValueError(msg)
        return value

    def snapshot(self) -> Dict[str, object]:
        """Return a serialisable snapshot for reporting."""

        try:
            return self.model_dump()
        except ValidationError:  # pragma: no cover - defensive
            return {
                "run_parallel": self.run_parallel,
                "max_workers": self.max_workers,
                "continue_on_error": self.continue_on_error,
                "dry_run": self.dry_run,
            }
