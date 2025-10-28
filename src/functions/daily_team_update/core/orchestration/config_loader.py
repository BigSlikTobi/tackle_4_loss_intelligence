"""Utility helpers to construct pipeline configuration from the environment."""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional

from src.shared.utils.config_validator import (
    validate_bool_env,
    validate_int_env,
    require_env,
    ConfigurationError,
)
from ..contracts.config import (
    PipelineConfig,
    ServiceCoordinatorConfig,
    ServiceEndpointConfig,
    SupabaseSettings,
)

logger = logging.getLogger(__name__)


def bool_from_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer for %s=%s, using %s", name, value, default)
        return default


def build_pipeline_config(overrides: Optional[Dict[str, object]] = None) -> PipelineConfig:
    overrides = overrides or {}
    run_parallel = overrides.get("parallel")
    if run_parallel is None:
        run_parallel = bool_from_env("PIPELINE_PARALLEL", False)
    max_workers = overrides.get("max_workers")
    if max_workers is None:
        max_workers = int_from_env("PIPELINE_MAX_WORKERS", 4)
    continue_on_error_override = overrides.get("continue_on_error")
    if continue_on_error_override is None:
        continue_on_error = bool_from_env("PIPELINE_CONTINUE_ON_ERROR", True)
    else:
        continue_on_error = bool(continue_on_error_override)
    dry_run = bool(overrides.get("dry_run") or bool_from_env("PIPELINE_DRY_RUN", False))
    image_count_override = overrides.get("image_count")
    if image_count_override is None:
        image_count = int_from_env("PIPELINE_IMAGE_COUNT", 2)
    else:
        image_count = int(image_count_override)
    allow_empty_override = overrides.get("allow_empty_urls")
    if allow_empty_override is None:
        allow_empty = bool_from_env("PIPELINE_ALLOW_EMPTY_URLS", False)
    else:
        allow_empty = bool(allow_empty_override)
    max_urls_override = overrides.get("max_urls_per_team")
    if max_urls_override is None:
        raw = os.getenv("PIPELINE_MAX_URLS_PER_TEAM")
        if raw:
            try:
                max_urls = int(raw)
            except ValueError:
                logger.warning(
                    "Invalid PIPELINE_MAX_URLS_PER_TEAM=%s, defaulting to 10", raw
                )
                max_urls = 10
        else:
            max_urls = None
    else:
        max_urls = int(max_urls_override) if max_urls_override is not None else None
    summarisation_batch_override = overrides.get("summarization_batch_size")
    if summarisation_batch_override is None:
        summarisation_batch = int_from_env("PIPELINE_SUMMARIZATION_BATCH_SIZE", 5)
    else:
        summarisation_batch = int(summarisation_batch_override)

    return PipelineConfig(
        run_parallel=bool(run_parallel),
        max_workers=int(max_workers),
        continue_on_error=bool(continue_on_error),
        dry_run=dry_run,
        image_count=int(image_count),
        allow_empty_urls=allow_empty,
        max_urls_per_team=max_urls,
        summarization_batch_size=summarisation_batch,
    )


def build_service_config(overrides: Optional[Dict[str, object]] = None) -> ServiceCoordinatorConfig:
    overrides = overrides or {}
    config = ServiceCoordinatorConfig(
        content_extraction=_build_endpoint("CONTENT_EXTRACTION", overrides.get("content_extraction")),
        summarization=_build_endpoint("SUMMARIZATION", overrides.get("summarization")),
        article_generation=_build_endpoint("ARTICLE_GENERATION", overrides.get("article_generation")),
        translation=_build_endpoint("TRANSLATION", overrides.get("translation")),
        image_selection=_build_endpoint("IMAGE_SELECTION", overrides.get("image_selection")),
        max_parallel_requests=int_from_env("SERVICE_MAX_PARALLEL_REQUESTS", 4),
    )
    return config


def build_supabase_settings(overrides: Optional[Dict[str, object]] = None) -> SupabaseSettings:
    """Build Supabase settings with validation."""
    overrides = overrides or {}
    try:
        url = overrides.get("url") or require_env("SUPABASE_URL", "Supabase project URL")
        key = overrides.get("key") or require_env("SUPABASE_KEY", "Supabase service role key")
    except ConfigurationError as exc:
        raise ConfigurationError(
            f"{exc}\nRequired for daily team update pipeline. "
            "See .env.example for configuration template."
        )

    return SupabaseSettings(
        url=url,
        key=key,
        schema=overrides.get("schema") or os.getenv("SUPABASE_SCHEMA", "public"),
        team_table=overrides.get("team_table") or os.getenv("TEAM_METADATA_TABLE", "teams"),
        article_table=overrides.get("article_table") or os.getenv("TEAM_ARTICLE_TABLE", "team_article"),
        relationship_table=overrides.get("relationship_table")
        or os.getenv("TEAM_ARTICLE_RELATIONSHIP_TABLE", "team_article_image"),
        image_table=overrides.get("image_table") or os.getenv("TEAM_IMAGE_TABLE", "article_images"),
        news_function=overrides.get("news_function") or os.getenv("TEAM_NEWS_FUNCTION", "team-news-urls"),
        function_timeout=int_from_env("SUPABASE_FUNCTION_TIMEOUT", 30),
    )


def _build_endpoint(prefix: str, override: Optional[Dict[str, object]]) -> Optional[ServiceEndpointConfig]:
    if isinstance(override, ServiceEndpointConfig):
        return override
    override = override or {}
    url = override.get("url") or os.getenv(f"{prefix}_URL") or os.getenv(f"{prefix}_ENDPOINT")
    if not url:
        return None
    timeout = int(override.get("timeout_seconds") or int_from_env(f"{prefix}_TIMEOUT", 120))
    api_key = override.get("api_key") or os.getenv(f"{prefix}_API_KEY")
    authorization = override.get("authorization") or os.getenv(f"{prefix}_AUTHORIZATION")
    additional_headers = {
        key[len(prefix) + 1 :]: value
        for key, value in os.environ.items()
        if key.startswith(f"{prefix}_HEADER_")
    }
    additional_headers.update(override.get("additional_headers") or {})
    return ServiceEndpointConfig(
        url=url,
        timeout_seconds=timeout,
        api_key=api_key,
        authorization=authorization,
        additional_headers=additional_headers,
    )
