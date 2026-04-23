"""Request models and configuration for news extraction jobs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from src.shared.jobs.contracts import SupabaseConfig  # noqa: F401  (re-export)

logger = logging.getLogger(__name__)


MAX_ARTICLES_PER_SOURCE = 1000
MAX_WORKERS = 20

# Sanity floor for ``since`` so a malformed timestamp can't ask the pipeline
# to scrape the entire history of a source. RSS feeds only carry a few
# days/weeks anyway, but the floor keeps the upstream days_back budget bounded.
MIN_SINCE = datetime(2000, 1, 1, tzinfo=timezone.utc)


@dataclass
class ExtractionOptions:
    """Per-job extraction tuning.

    ``since`` is the canonical "give me everything published after this
    point" knob. It replaces the legacy ``days_back`` integer because
    downstream consumers manage their own watermark (e.g. ``last_seen_at``)
    and want to query forward from a precise instant. The service post-
    filters items by ``publication_date >= since`` so the result is exact.

    Note: this service is pure extraction — it never writes to the
    database. The legacy ``dry_run`` and ``clear`` options are
    intentionally absent; persistence is the caller's responsibility.
    """

    source_filter: Optional[str] = None
    since: Optional[datetime] = None
    max_articles: Optional[int] = None
    max_workers: Optional[int] = None

    def validate(self) -> None:
        if self.since is not None:
            if self.since.tzinfo is None:
                raise ValueError(
                    "options.since must be timezone-aware (e.g. ISO 8601 with offset)"
                )
            if self.since < MIN_SINCE:
                raise ValueError(
                    f"options.since must be on or after {MIN_SINCE.isoformat()}"
                )
            if self.since > datetime.now(timezone.utc):
                raise ValueError("options.since must not be in the future")
        if self.max_articles is not None and not (
            1 <= self.max_articles <= MAX_ARTICLES_PER_SOURCE
        ):
            raise ValueError(
                f"options.max_articles must be in [1, {MAX_ARTICLES_PER_SOURCE}]"
            )
        if self.max_workers is not None and not (1 <= self.max_workers <= MAX_WORKERS):
            raise ValueError(f"options.max_workers must be in [1, {MAX_WORKERS}]")


@dataclass
class SubmitRequest:
    options: ExtractionOptions
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        self.options.validate()
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")


def _validate_job_id(job_id: str) -> None:
    """Reject anything that isn't a parseable UUID.

    Without this check a typo'd or truncated job_id was being passed
    straight to Supabase, which threw `22P02 invalid input syntax for
    type uuid` and surfaced a 500 with a Postgres stack trace. Validate
    upstream so callers get a clean 400 instead.
    """
    if not job_id:
        raise ValueError("job_id is required")
    try:
        UUID(str(job_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"job_id must be a UUID, got {job_id!r}")


@dataclass
class PollRequest:
    job_id: str
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        _validate_job_id(self.job_id)
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")


@dataclass
class WorkerRequest:
    job_id: str
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        _validate_job_id(self.job_id)
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")
