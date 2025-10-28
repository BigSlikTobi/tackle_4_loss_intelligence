"""Helper script to generate Cloud Scheduler commands for the pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

DEFAULT_REGION = "us-central1"
DEFAULT_SCHEDULE = "0 12 * * *"  # Daily at noon UTC


@dataclass
class SchedulerConfig:
    name: str
    url: str
    schedule: str
    region: str
    time_zone: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Cloud Scheduler command for the daily team update pipeline",
    )
    parser.add_argument("--name", default="daily-team-update", help="Scheduler job name")
    parser.add_argument("--url", required=True, help="HTTP endpoint for the Cloud Function")
    parser.add_argument(
        "--schedule",
        default=DEFAULT_SCHEDULE,
        help="Cron schedule in UTC (default: 0 12 * * *)",
    )
    parser.add_argument(
        "--time-zone",
        default="UTC",
        help="Cron schedule time zone (default: UTC)",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help="GCP region for the scheduler job (default: us-central1)",
    )
    parser.add_argument(
        "--description",
        default="Daily NFL team update pipeline",
        help="Optional scheduler job description",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cmd = build_command(
        SchedulerConfig(
            name=args.name,
            url=args.url,
            schedule=args.schedule,
            region=args.region,
            time_zone=args.time_zone,
        ),
        description=args.description,
    )
    print(cmd)
    return 0


def build_command(config: SchedulerConfig, *, description: str) -> str:
    body = '{"parallel": true}'
    parts = [
        "gcloud",
        "scheduler",
        "jobs",
        "create",
        "http",
        config.name,
        f"--schedule='{config.schedule}'",
        f"--time-zone='{config.time_zone}'",
        f"--uri='{config.url}'",
        "--http-method=POST",
        "--headers='Content-Type=application/json'",
        f"--body='{body}'",
        f"--location='{config.region}'",
        f"--description='{description}'",
    ]
    return " ".join(parts)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
