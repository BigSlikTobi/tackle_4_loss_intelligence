"""Worker-side orchestration for a single news_extraction job.

Loads the queued row, claims it, instantiates a request-scoped
``NewsExtractionPipeline`` in **stateless mode** (no DB writes, no
watermark reads/writes), runs the extraction, and writes the terminal
state to the jobs row. The extracted items are returned in the response
— downstream consumers handle persistence.

Statelessness is enforced by:

1. Never constructing a ``NewsUrlWriter`` (so no ``news_urls`` writes).
2. Forcing ``dry_run=True`` on every ``pipeline.extract()`` call (which
   skips writes and skips watermark *advancement*).
3. Injecting a ``_NullWatermarkStore`` that returns no watermarks on
   reads (so items aren't filtered by stored state) and accepts
   ``update_watermarks`` as a no-op (defense-in-depth).

The extraction pipeline lives at ``..extraction.pipelines`` — a local
copy of the legacy ``news_extraction.core`` codebase, kept here so this
module has zero cross-function imports. The duplication is deliberate
and short-lived: legacy ``news_extraction`` will be deleted in a few
weeks once downstream callers migrate; at that point this copy becomes
the canonical home.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

from src.shared.jobs.contracts import JobStatus, SupabaseConfig
from src.shared.jobs.store import JobStore

from ..config import ExtractionOptions
from ..contracts.result import JobResult

SERVICE_NAME = "news_extraction"

logger = logging.getLogger(__name__)


class _Pipeline(Protocol):
    """Minimal protocol the worker requires of the underlying pipeline."""

    def extract(
        self,
        source_filter: Optional[str] = None,
        days_back: Optional[int] = None,
        max_articles: Optional[int] = None,
        dry_run: bool = False,
        clear: bool = False,
    ) -> Dict[str, Any]: ...

    def close(self) -> None: ...


# Pluggable seam so tests can inject a fake pipeline without touching network or DB.
PipelineFactory = Callable[[SupabaseConfig, ExtractionOptions], _Pipeline]


def run_job(
    job_id: str,
    supabase_config: SupabaseConfig,
    *,
    pipeline_factory: Optional[PipelineFactory] = None,
    store: Optional[JobStore] = None,
) -> Dict[str, Any]:
    """Run extraction for a single ``job_id``. Returns a summary dict."""
    store = store or JobStore(supabase_config, service=SERVICE_NAME)
    row = store.peek(job_id)
    if row is None:
        logger.warning("run_job: job %s not found (expired or consumed)", job_id)
        return {"job_id": job_id, "status": "not_found"}

    status = row.get("status")
    if status in (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value):
        logger.info("run_job: job %s already terminal (%s)", job_id, status)
        return {"job_id": job_id, "status": status, "idempotent_skip": True}

    claimed = store.mark_running(job_id)
    if claimed is None:
        logger.info("run_job: could not claim job %s", job_id)
        return {"job_id": job_id, "status": "not_claimed"}

    try:
        options = _rehydrate(row.get("input") or {})
    except ValueError as exc:
        store.mark_failed(
            job_id,
            {"code": "invalid_input", "message": str(exc), "retryable": False},
        )
        return {"job_id": job_id, "status": "failed", "reason": "invalid_input"}

    factory = pipeline_factory or _default_pipeline_factory
    pipeline: Optional[_Pipeline] = None
    try:
        pipeline = factory(supabase_config, options)
        # Forced dry_run + no writer + null watermark store = stateless.
        # Persistence is the caller's responsibility (see module docstring).
        # ``since`` is post-filtered below for exactness; the upstream
        # ``days_back`` is just a bound on how far the per-source extractor
        # walks the feed (RSS feeds rarely carry more than a few weeks).
        raw = pipeline.extract(
            source_filter=options.source_filter,
            days_back=_days_back_for_since(options.since),
            max_articles=options.max_articles,
            dry_run=True,
            clear=False,
        )
    except Exception as exc:
        logger.exception("Pipeline crashed for job %s", job_id)
        store.mark_failed(
            job_id,
            {
                "code": exc.__class__.__name__,
                "message": str(exc),
                "retryable": True,
            },
        )
        return {"job_id": job_id, "status": "failed", "reason": "exception"}
    finally:
        if pipeline is not None:
            try:
                pipeline.close()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("Pipeline close raised", exc_info=True)

    if isinstance(raw, dict) and not raw.get("success", True):
        # Pipeline reported a recoverable failure (e.g. config load error).
        message = "; ".join(raw.get("errors") or []) or "pipeline reported failure"
        store.mark_failed(
            job_id,
            {"code": "pipeline_failure", "message": message, "retryable": True},
        )
        return {"job_id": job_id, "status": "failed", "reason": "pipeline_failure"}

    # Apply the precise ``since`` filter on the post-transform records so
    # callers get a clean cutoff at their watermark (the upstream
    # ``days_back`` budget is intentionally loose). Items missing a
    # publication_date are dropped when ``since`` is set — we can't prove
    # they're newer than the watermark.
    if options.since is not None:
        raw = dict(raw)
        raw["records"] = _filter_records_since(raw.get("records") or [], options.since)

    # Surface the extracted items in the result (legacy pipeline returns
    # them under the `records` key when dry_run=True; we expose as `items`).
    result = JobResult.from_pipeline_dict(raw or {})
    store.mark_succeeded(job_id, result.to_dict())
    return {
        "job_id": job_id,
        "status": "succeeded",
        "sources_processed": result.sources_processed,
        "items_count": len(result.items),
    }


def _rehydrate(payload: Dict[str, Any]) -> ExtractionOptions:
    options_payload = payload.get("options") or {}
    if not isinstance(options_payload, dict):
        raise ValueError("stored input.options must be an object")
    # ``since`` is stored as an ISO string in the jsonb input; parse back to
    # datetime via the same coercer the submit endpoint uses so behavior
    # matches end-to-end.
    from ..factory import _coerce_since

    options = ExtractionOptions(
        source_filter=options_payload.get("source_filter"),
        since=_coerce_since(options_payload.get("since")),
        max_articles=options_payload.get("max_articles"),
        max_workers=options_payload.get("max_workers"),
    )
    options.validate()
    return options


def _days_back_for_since(since: Optional[datetime]) -> Optional[int]:
    """Translate ``since`` into a generous upstream ``days_back`` budget.

    Returns ``None`` when ``since`` is unset (so the per-source defaults
    in feeds.yaml apply). When set, computes ceil(now - since in days)
    plus a 1-day buffer to absorb timezone/clock skew. Never returns < 1.
    """
    if since is None:
        return None
    delta = datetime.now(timezone.utc) - since
    days = math.ceil(delta.total_seconds() / 86400) + 1
    return max(1, int(days))


def _filter_records_since(
    records: List[Dict[str, Any]],
    since: datetime,
) -> List[Dict[str, Any]]:
    """Keep records whose ``publication_date`` is on/after ``since``.

    Records lacking a parseable date are dropped. Everything is normalized
    to tz-aware UTC for the comparison.
    """
    cutoff = since.astimezone(timezone.utc) if since.tzinfo else since.replace(tzinfo=timezone.utc)
    kept: List[Dict[str, Any]] = []
    for record in records:
        published = _record_published_at(record)
        if published is None:
            continue
        if published >= cutoff:
            kept.append(record)
    return kept


def _record_published_at(record: Dict[str, Any]) -> Optional[datetime]:
    raw = record.get("publication_date")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc) if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class _NullWatermarkStore:
    """No-op watermark store so the pipeline runs without DB state.

    Returning an empty dict on ``fetch_watermarks`` means no items are
    filtered out by stored state — every freshly extracted item flows
    through to the response. ``update_watermarks`` is a no-op for
    defense-in-depth (the pipeline already gates that call on
    ``not dry_run`` but we never want it firing here).
    """

    def fetch_watermarks(self) -> Dict[str, Any]:
        return {}

    def update_watermarks(self, *_args, **_kwargs) -> None:
        return None


def _default_pipeline_factory(
    supabase_config: SupabaseConfig,
    options: ExtractionOptions,
) -> _Pipeline:
    """Build a request-scoped pipeline in stateless mode.

    No ``NewsUrlWriter`` is ever instantiated, so the pipeline cannot
    write to ``news_urls``. The watermark store is a null implementation,
    so the pipeline neither reads nor writes ``news_source_watermarks``.

    The pipeline class is the new service's own copy under
    ``..extraction.pipelines`` (no cross-function dependency on the
    legacy ``news_extraction`` module). Imported lazily so the module
    stays importable in environments that don't have the heavy deps
    (yaml, feedparser, ...) on the path — most notably the unit test
    runner, which injects a fake factory and never reaches this branch.
    """
    from ..extraction.pipelines import NewsExtractionPipeline

    return NewsExtractionPipeline(
        writer=None,  # never write to news_urls
        watermark_store=_NullWatermarkStore(),  # never read/write watermarks
        max_workers=options.max_workers,
    )
