"""Worker-side orchestration for a single article-extraction job.

Loads the queued row, claims it (queued -> running), runs the pipeline, and
writes a terminal state. Idempotent: if the job is already terminal, no-op.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from ..config import (
    ArticleInput,
    ExtractionOptions,
    LLMConfig,
    SupabaseConfig,
)
from ..contracts.job import JobStatus
from ..db.job_store import JobStore
from ..pipelines.article_extraction_pipeline import ArticleExtractionPipeline

logger = logging.getLogger(__name__)


def run_job(job_id: str, supabase_config: SupabaseConfig) -> Dict[str, Any]:
    """Run the extraction pipeline for a single job_id.

    Returns a summary dict for logging/telemetry. Errors are caught and stored
    on the job row — this function itself should not raise except for truly
    unexpected failures.
    """
    store = JobStore(supabase_config)
    row = store.peek(job_id)
    if row is None:
        logger.warning("run_job: job %s not found (expired or consumed)", job_id)
        return {"job_id": job_id, "status": "not_found"}

    status = row.get("status")
    if status in (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value):
        logger.info("run_job: job %s already terminal (%s); skipping", job_id, status)
        return {"job_id": job_id, "status": status, "idempotent_skip": True}

    claimed = store.mark_running(job_id)
    if claimed is None:
        # Another worker already claimed the job (queued -> running is atomic).
        # Bail out rather than run concurrently — the other worker is in flight,
        # or the requeue cron fired after this worker had already started.
        logger.info(
            "run_job: could not claim job %s (already claimed, current status=%s)",
            job_id,
            status,
        )
        return {"job_id": job_id, "status": "not_claimed"}

    input_payload = row.get("input") or {}
    try:
        article, options, llm = _rehydrate(input_payload)
    except ValueError as exc:
        store.mark_failed(
            job_id,
            {"code": "invalid_input", "message": str(exc), "retryable": False},
        )
        return {"job_id": job_id, "status": "failed", "reason": "invalid_input"}

    try:
        pipeline = ArticleExtractionPipeline.from_llm_config(
            llm, options, supabase=supabase_config
        )
        result = pipeline.run(article, options)
        store.mark_succeeded(job_id, result.to_dict())
        return {"job_id": job_id, "status": "succeeded"}
    except Exception as exc:
        logger.exception("Pipeline failed for job %s", job_id)
        store.mark_failed(
            job_id,
            {
                "code": exc.__class__.__name__,
                "message": str(exc),
                "retryable": True,
            },
        )
        return {"job_id": job_id, "status": "failed", "reason": "exception"}


def _rehydrate(payload: Dict[str, Any]):
    article_payload = payload.get("article") or {}
    options_payload = payload.get("options") or {}
    llm_payload = payload.get("llm") or {}

    article = ArticleInput(
        text=article_payload.get("text", ""),
        article_id=article_payload.get("article_id"),
        title=article_payload.get("title"),
        url=article_payload.get("url"),
    )
    article.validate()

    options = ExtractionOptions(
        max_topics=int(options_payload.get("max_topics", 5)),
        max_entities=int(options_payload.get("max_entities", 15)),
        resolve_entities=bool(options_payload.get("resolve_entities", True)),
        confidence_threshold=float(options_payload.get("confidence_threshold", 0.6)),
    )
    options.validate()

    # Read the OpenAI key from the worker's own runtime env — never from the
    # stored job row, so the secret doesn't live in the database.
    api_key = os.getenv("OPENAI_API_KEY", "")
    llm = LLMConfig(
        provider=llm_payload.get("provider", "openai"),
        model=llm_payload.get("model", "gpt-5.4-mini"),
        api_key=api_key,
        parameters=llm_payload.get("parameters") or {},
        timeout_seconds=int(llm_payload.get("timeout_seconds", 60)),
        max_retries=int(llm_payload.get("max_retries", 2)),
    )
    if not llm.api_key:
        raise ValueError(
            "OPENAI_API_KEY must be set in the worker's runtime env"
        )
    if not llm.model:
        raise ValueError("llm.model is required in the stored job input")

    return article, options, llm
