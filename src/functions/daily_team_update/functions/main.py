"""Cloud Function entry point for the daily team update pipeline."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import flask

# Ensure project root is available on import path
project_root = Path(__file__).parent.parent.parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.daily_team_update.core.db.team_reader import TeamReader
from src.functions.daily_team_update.core.integration.service_coordinator import ServiceCoordinator
from src.functions.daily_team_update.core.integration.supabase_client import SupabaseClient
from src.functions.daily_team_update.core.monitoring.error_handler import ErrorHandler
from src.functions.daily_team_update.core.monitoring.metrics_collector import MetricsCollector
from src.functions.daily_team_update.core.orchestration.config_loader import (
    build_pipeline_config,
    build_service_config,
    build_supabase_settings,
)
from src.functions.daily_team_update.core.orchestration.pipeline import Pipeline
from src.functions.daily_team_update.core.orchestration.team_processor import TeamProcessor

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def pipeline_handler(request: flask.Request) -> flask.Response:
    """HTTP handler orchestrating the daily team update pipeline."""

    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    if request.method != "POST":
        return _error_response("Method not allowed. Use POST.", status=405)

    payload = request.get_json(silent=True) or {}
    logger.info("Received pipeline invocation with payload keys: %s", list(payload.keys()))

    overrides = {
        "parallel": payload.get("parallel"),
        "max_workers": payload.get("max_workers"),
        "continue_on_error": payload.get("continue_on_error"),
        "dry_run": payload.get("dry_run"),
        "image_count": payload.get("image_count"),
        "max_urls_per_team": payload.get("max_urls_per_team"),
        "summarization_batch_size": payload.get("summarization_batch_size"),
        "allow_empty_urls": payload.get("allow_empty_urls"),
    }

    try:
        pipeline_config = build_pipeline_config(overrides)
        service_config = build_service_config()
        supabase_settings = build_supabase_settings()
    except KeyError as exc:
        logger.error("Missing configuration: %s", exc)
        return _error_response(f"Configuration error: {exc}", status=500)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build pipeline configuration")
        return _error_response(f"Configuration error: {exc}", status=500)

    missing_endpoint = _missing_endpoint(service_config)
    if missing_endpoint:
        logger.error("Missing service endpoint configuration: %s", missing_endpoint)
        return _error_response(
            f"Service endpoint '{missing_endpoint}' is not configured",
            status=500,
        )

    metrics = MetricsCollector()
    errors = ErrorHandler()

    teams = payload.get("teams")
    if teams is not None and not isinstance(teams, (list, tuple)):
        return _error_response("'teams' must be an array of team abbreviations", status=400)

    with SupabaseClient(supabase_settings) as supabase:
        team_reader = TeamReader(supabase)
        service_coordinator = ServiceCoordinator(service_config, pipeline_config)
        try:
            team_processor = TeamProcessor(
                supabase=supabase,
                service_coordinator=service_coordinator,
                pipeline_config=pipeline_config,
                metrics=metrics,
                error_handler=errors,
            )
            pipeline = Pipeline(
                team_reader=team_reader,
                team_processor=team_processor,
                metrics=metrics,
                errors=errors,
                config=pipeline_config,
            )
            result = pipeline.run(teams)
        finally:
            service_coordinator.close()

    response_body = result.to_dict()
    response_body["errors"] = errors.as_dict()
    logger.info(
        "Pipeline finished: successes=%s failures=%s skipped=%s",
        response_body.get("success_count"),
        response_body.get("failure_count"),
        response_body.get("skipped_count"),
    )
    return _cors_response(response_body)


def health_check_handler(request: flask.Request) -> flask.Response:
    """Health check endpoint returning module status."""

    return _cors_response({"status": "healthy", "module": "daily_team_update"})


def _missing_endpoint(service_config) -> str | None:
    for attr in ("content_extraction", "summarization", "article_generation", "translation", "image_selection"):
        if getattr(service_config, attr) is None:
            return attr
    return None


def _cors_response(body: dict[str, Any] | Iterable[Any], status: int = 200) -> flask.Response:
    response = flask.make_response(json.dumps(body, ensure_ascii=False), status)
    headers = response.headers
    headers["Content-Type"] = "application/json"
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,X-API-Key"
    return response


def _error_response(message: str, status: int) -> flask.Response:
    return _cors_response({"status": "error", "message": message}, status=status)


try:  # pragma: no cover - optional registration for local emulators
    import functions_framework
except ImportError:  # pragma: no cover
    functions_framework = None

if functions_framework is not None:

    @functions_framework.http
    def run_pipeline(request: flask.Request):
        return pipeline_handler(request)

    @functions_framework.http
    def health_check(request: flask.Request):
        return health_check_handler(request)
