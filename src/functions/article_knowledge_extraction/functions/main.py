"""Cloud Function entry points for article knowledge extraction.

Three handlers share this deployment (one zip, three `gcloud functions deploy`
entry points):

- ``submit_article_knowledge_job``  — POST /submit
- ``poll_article_knowledge_job``    — POST /poll
- ``run_article_knowledge_worker``  — POST /worker (internal)

Async pattern: submit writes a queued row, fire-and-forget POSTs to the worker
URL, returns 202 immediately. Worker runs the pipeline and writes terminal
state. Poll reads non-terminal statuses, or atomically consume-on-read when
terminal.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

import flask
import requests

project_root = Path(__file__).resolve().parents[4]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.article_knowledge_extraction.core.factory import (
    poll_request_from_payload,
    submit_request_from_payload,
    worker_request_from_payload,
)
from src.functions.article_knowledge_extraction.core.contracts.job import JobStatus
from src.functions.article_knowledge_extraction.core.db.job_store import JobStore
from src.functions.article_knowledge_extraction.core.worker.job_runner import run_job

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

WORKER_URL = os.getenv("WORKER_URL", "")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")


# --------------------------------------------------------------------- handlers


def submit_handler(request: flask.Request) -> flask.Response:
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)
    if request.method != "POST":
        return _error_response("Method not allowed. Use POST.", status=405)

    try:
        payload = request.get_json(silent=True) or {}
        req = submit_request_from_payload(payload)
    except ValueError as exc:
        return _error_response(str(exc), status=400)

    store = JobStore(req.supabase)
    input_payload = {
        "article": {
            "text": req.article.text,
            "article_id": req.article.article_id,
            "title": req.article.title,
            "url": req.article.url,
        },
        "options": {
            "max_topics": req.options.max_topics,
            "max_entities": req.options.max_entities,
            "resolve_entities": req.options.resolve_entities,
            "confidence_threshold": req.options.confidence_threshold,
        },
        "llm": {
            "provider": req.llm.provider,
            "model": req.llm.model,
            "api_key": req.llm.api_key,
            "parameters": req.llm.parameters,
            "timeout_seconds": req.llm.timeout_seconds,
            "max_retries": req.llm.max_retries,
        },
    }

    try:
        job = store.create_job(input_payload)
    except Exception:
        logger.exception("Failed to create job")
        return _error_response("Failed to create job", status=500)

    job_id = job.get("job_id")
    _fire_worker(job_id, req.supabase)

    return _cors_response(
        {
            "status": JobStatus.QUEUED.value,
            "job_id": job_id,
            "expires_at": job.get("expires_at"),
        },
        status=202,
    )


def poll_handler(request: flask.Request) -> flask.Response:
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)
    if request.method != "POST":
        return _error_response("Method not allowed. Use POST.", status=405)

    try:
        payload = request.get_json(silent=True) or {}
        req = poll_request_from_payload(payload)
    except ValueError as exc:
        return _error_response(str(exc), status=400)

    store = JobStore(req.supabase)
    row = store.peek(req.job_id)
    if row is None:
        return _error_response("job_id not found or expired", status=404)

    status = row.get("status")
    if status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
        return _cors_response({"status": status, "job_id": req.job_id})

    # Terminal — consume atomically.
    consumed = store.consume_terminal(req.job_id)
    if consumed is None:
        # Race: another poller just read it, or it expired between the peek
        # and the RPC call. Report not found.
        return _error_response("job_id not found or already consumed", status=404)

    body: Dict[str, Any] = {"status": consumed.get("status"), "job_id": req.job_id}
    if consumed.get("result") is not None:
        body["result"] = consumed["result"]
    if consumed.get("error") is not None:
        body["error"] = consumed["error"]
    return _cors_response(body)


def worker_handler(request: flask.Request) -> flask.Response:
    if request.method != "POST":
        return _error_response("Method not allowed. Use POST.", status=405)

    if WORKER_TOKEN:
        token = request.headers.get("X-Worker-Token", "")
        if not hmac.compare_digest(token, WORKER_TOKEN):
            logger.warning("Worker handler rejected unauthenticated request")
            return _error_response("Forbidden", status=403)

    try:
        payload = request.get_json(silent=True) or {}
        req = worker_request_from_payload(payload)
    except ValueError as exc:
        return _error_response(str(exc), status=400)

    summary = run_job(req.job_id, req.supabase)
    return _cors_response(summary)


def health_check_handler(request: flask.Request) -> flask.Response:
    return _cors_response(
        {"status": "healthy", "service": "article_knowledge_extraction"}
    )


# --------------------------------------------------------------------- helpers


def _fire_worker(job_id: str, supabase_config) -> None:
    """Fire-and-forget POST to the worker endpoint. Timeouts are tiny so the
    TCP write completes but we never wait on the worker's response."""
    if not WORKER_URL:
        logger.warning(
            "WORKER_URL not configured; job %s will only run if a cron requeues it", job_id
        )
        return

    payload = {
        "job_id": job_id,
        "supabase": {
            "url": supabase_config.url,
            "key": supabase_config.key,
            "jobs_table": supabase_config.jobs_table,
        },
    }
    headers = {"Content-Type": "application/json"}
    if WORKER_TOKEN:
        headers["X-Worker-Token"] = WORKER_TOKEN
    try:
        requests.post(WORKER_URL, json=payload, headers=headers, timeout=(3, 0.5))
    except requests.RequestException as exc:
        # Expected — read timeout is intentional. Log at debug.
        logger.debug("Worker fire-and-forget returned: %s", exc)


def _cors_response(body, status: int = 200) -> flask.Response:
    response = flask.make_response(json.dumps(body, ensure_ascii=False, default=str), status)
    response.headers["Content-Type"] = "application/json"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,X-Worker-Token"
    return response


def _error_response(message: str, status: int) -> flask.Response:
    return _cors_response({"status": "error", "message": message}, status=status)


# functions-framework registration for `gcloud` deployment -------------------

try:  # pragma: no cover - optional dependency
    import functions_framework
except ImportError:  # pragma: no cover
    functions_framework = None

if functions_framework is not None:

    @functions_framework.http
    def submit_article_knowledge_job(request: flask.Request):
        return submit_handler(request)

    @functions_framework.http
    def poll_article_knowledge_job(request: flask.Request):
        return poll_handler(request)

    @functions_framework.http
    def run_article_knowledge_worker(request: flask.Request):
        return worker_handler(request)

    @functions_framework.http
    def health_check(request: flask.Request):
        return health_check_handler(request)
