"""CLI entry point for the daily team update pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.daily_team_update.core.db.team_reader import TeamReader
from src.functions.daily_team_update.core.integration.service_coordinator import ServiceCoordinator
from src.functions.daily_team_update.core.integration.supabase_client import SupabaseClient
from src.functions.daily_team_update.core.monitoring.error_handler import ErrorHandler
from src.functions.daily_team_update.core.monitoring.metrics_collector import MetricsCollector
from src.functions.daily_team_update.core.orchestration.pipeline import Pipeline
from src.functions.daily_team_update.core.orchestration.team_processor import TeamProcessor
from src.functions.daily_team_update.core.orchestration.config_loader import (
    build_pipeline_config,
    build_service_config,
    build_supabase_settings,
)

LOG = logging.getLogger(__name__)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the daily team update pipeline.")
    parser.add_argument("--team", "-t", action="append", help="Team abbreviation to process (can be repeated)")
    parser.add_argument("--parallel", action="store_true", help="Enable parallel processing")
    parser.add_argument("--max-workers", type=int, help="Maximum number of worker threads when running in parallel")
    parser.add_argument(
        "--no-continue-on-error",
        action="store_true",
        help="Fail fast on the first critical error instead of continuing",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip database writes")
    parser.add_argument("--image-count", type=int, help="Override number of images to request per team")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format for results (default: text)",
    )
    return parser.parse_args(argv)


def run(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    load_env()
    setup_logging(level="DEBUG" if args.verbose else None)

    try:
        pipeline_config = build_pipeline_config(
            {
                "parallel": True if args.parallel else None,
                "max_workers": args.max_workers,
                "continue_on_error": False if args.no_continue_on_error else None,
                "dry_run": True if args.dry_run else None,
                "image_count": args.image_count,
            }
        )
        service_config = build_service_config()
        supabase_settings = build_supabase_settings()
    except KeyError as exc:
        LOG.error("Missing required environment variable: %s", exc)
        return 1

    if any(getattr(service_config, attr) is None for attr in ("content_extraction", "summarization", "article_generation", "translation", "image_selection")):
        LOG.error(
            "One or more service endpoints are not configured. Check CONTENT_EXTRACTION_URL, SUMMARIZATION_URL, ARTICLE_GENERATION_URL, TRANSLATION_URL, and IMAGE_SELECTION_URL."
        )
        return 1

    metrics = MetricsCollector()
    errors = ErrorHandler()

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
            result = pipeline.run(args.team)
        finally:
            service_coordinator.close()

    output = result.to_dict()
    output["errors"] = errors.as_dict()

    if args.output == "json":
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_summary(output)

    return 0 if output.get("failure_count", 0) == 0 else 2


def _print_summary(output: Dict[str, object]) -> None:
    LOG.info(
        "Pipeline complete: %s processed, %s success, %s failed, %s skipped",
        output.get("processed_teams"),
        output.get("success_count"),
        output.get("failure_count"),
        output.get("skipped_count"),
    )
    errors = output.get("errors") or []
    if errors:
        LOG.warning("Encountered %s errors", len(errors))
        for entry in errors:
            LOG.warning(
                "[%s] %s - %s",
                entry.get("team_abbr"),
                entry.get("stage"),
                entry.get("message"),
            )


if __name__ == "__main__":  # pragma: no cover - manual execution entry
    sys.exit(run())
