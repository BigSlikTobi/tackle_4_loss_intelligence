"""Worker-side orchestration for a single URL-content-extraction job.

Loads the queued row, claims it (queued -> running), runs Playwright/light
extraction across the URLs, and writes a terminal state. Idempotent: if the
job is already terminal, no-op.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from src.shared.contracts.extracted_content import ExtractedContent
from src.shared.extractors.extractor_factory import get_extractor
from src.shared.jobs.contracts import JobStatus, SupabaseConfig
from src.shared.jobs.store import JobStore
from src.shared.utils.amp_detector import probe_for_amp

from .. import config as svc_config
from ..config import ExtractionOptions
from ..contracts.result import ArticleOut, JobResult

SERVICE_NAME = "url_content_extraction"

logger = logging.getLogger(__name__)


# A pluggable extractor seam so the worker can be unit-tested without
# launching Playwright or hitting the network.
ExtractorFn = Callable[[str, ExtractionOptions], ExtractedContent]


def run_job(
    job_id: str,
    supabase_config: SupabaseConfig,
    *,
    extractor_fn: Optional[ExtractorFn] = None,
    store: Optional[JobStore] = None,
) -> Dict[str, Any]:
    """Run extraction for a single job_id. Returns a summary dict."""
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
        urls, options = _rehydrate(row.get("input") or {})
    except ValueError as exc:
        store.mark_failed(
            job_id,
            {"code": "invalid_input", "message": str(exc), "retryable": False},
        )
        return {"job_id": job_id, "status": "failed", "reason": "invalid_input"}

    extractor = extractor_fn or _default_extractor
    started = time.monotonic()
    articles: List[ArticleOut] = []
    succeeded = 0
    try:
        for url in urls:
            article = _extract_one(url, options, extractor)
            if article.error is None:
                succeeded += 1
            articles.append(article)
    except Exception as exc:
        logger.exception("Extraction crashed for job %s", job_id)
        store.mark_failed(
            job_id,
            {
                "code": exc.__class__.__name__,
                "message": str(exc),
                "retryable": True,
            },
        )
        return {"job_id": job_id, "status": "failed", "reason": "exception"}

    elapsed_ms = int((time.monotonic() - started) * 1000)
    result = JobResult(
        articles=articles,
        counts={"total": len(articles), "succeeded": succeeded},
        metrics={"total_ms": elapsed_ms},
    )
    store.mark_succeeded(job_id, result.to_dict())
    return {
        "job_id": job_id,
        "status": "succeeded",
        "total": len(articles),
        "succeeded": succeeded,
    }


def _rehydrate(payload: Dict[str, Any]):
    urls = payload.get("urls")
    if not isinstance(urls, list) or not urls:
        raise ValueError("stored input has empty 'urls'")
    options_payload = payload.get("options") or {}
    options = ExtractionOptions(
        timeout_seconds=int(options_payload.get("timeout_seconds", 45)),
        force_playwright=bool(options_payload.get("force_playwright", False)),
        prefer_lightweight=bool(options_payload.get("prefer_lightweight", False)),
        max_paragraphs=int(options_payload.get("max_paragraphs", 120)),
        min_paragraph_chars=int(options_payload.get("min_paragraph_chars", 240)),
    )
    options.validate()
    return [str(u) for u in urls], options


def _default_extractor(url: str, options: ExtractionOptions) -> ExtractedContent:
    """Production extraction path: AMP probe → factory-selected extractor."""
    target = url
    used_amp = False
    if not options.force_playwright:
        try:
            amp_url, is_amp = probe_for_amp(url, logger=logger)
            if is_amp and amp_url and amp_url != url:
                target = amp_url
                used_amp = True
        except Exception:  # pragma: no cover - probe never fatal
            logger.debug("AMP probe raised for %s", url, exc_info=True)
    extractor = get_extractor(
        target,
        force_playwright=options.force_playwright,
        prefer_lightweight=options.prefer_lightweight or used_amp,
        logger=logger,
    )
    return extractor.extract(target, timeout=options.timeout_seconds)


def _extract_one(
    url: str,
    options: ExtractionOptions,
    extractor: ExtractorFn,
) -> ArticleOut:
    try:
        extracted = extractor(url, options)
    except Exception as exc:  # noqa: BLE001 - per-URL failure must not abort the job
        logger.warning("Extractor crashed for %s: %s", url, exc, exc_info=True)
        return ArticleOut(url=url, error=str(exc))

    if not extracted.is_valid():
        return ArticleOut(
            url=url,
            error=extracted.error or "Insufficient content extracted",
        )

    paragraphs = [p.strip() for p in extracted.paragraphs if p and p.strip()]
    text = "\n\n".join(paragraphs)
    metadata: Dict[str, Any] | None = None
    if extracted.metadata is not None:
        metadata = {
            "extractor": extracted.metadata.extractor,
            "fetched_at": _isoformat(extracted.metadata.fetched_at),
            "duration_seconds": extracted.metadata.duration_seconds,
            "page_language": extracted.metadata.page_language,
            "raw_url": extracted.metadata.raw_url,
        }
    return ArticleOut(
        url=extracted.url or url,
        title=extracted.title,
        description=extracted.description,
        author=extracted.author,
        paragraphs=paragraphs,
        content=text,
        word_count=len(text.split()),
        quotes=list(extracted.quotes or []),
        published_at=_isoformat(extracted.published_at) if extracted.published_at else None,
        metadata=metadata,
    )


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")
