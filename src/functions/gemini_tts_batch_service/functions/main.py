"""Cloud Function entry points for gemini_tts_batch (submit/poll/worker).

Three handlers share this deployment:

- ``submit_tts_batch_job``   — POST /submit (returns 202)
- ``poll_tts_batch_job``     — POST /poll (status or terminal-consume)
- ``run_tts_batch_worker``   — POST /worker (internal, token-protected)

Architecture mirrors ``url_content_extraction_service``: submit writes a
queued row, fire-and-forget POSTs to the worker URL, returns 202 immediately.
The worker dispatches to the legacy ``TTSBatchService`` based on the stored
``action`` (``create`` / ``status`` / ``process``) and writes terminal state.
Poll reads non-terminal statuses, or atomically delete-on-read when terminal.
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

from src.shared.jobs.contracts import JobStatus
from src.shared.jobs.store import JobStore
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.gemini_tts_batch_service import SERVICE_NAME
from src.functions.gemini_tts_batch_service.core.factory import (
    poll_request_from_payload,
    submit_request_from_payload,
    worker_request_from_payload,
)
from src.functions.gemini_tts_batch_service.core.worker.job_runner import (
    run_job,
)

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

WORKER_URL = os.getenv("WORKER_URL", "")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
# Shared bearer token that authenticates submit/poll callers. Fails closed:
# if the env var is unset we reject every call rather than silently accepting
# anonymous traffic, since anonymous traffic would run on our Gemini+Supabase
# credentials.
CALLER_TOKEN = os.getenv("TTS_BATCH_FUNCTION_AUTH_TOKEN", "")


def _check_caller_auth(request: flask.Request) -> flask.Response | None:
    if not CALLER_TOKEN:
        logger.error(
            "TTS_BATCH_FUNCTION_AUTH_TOKEN is not configured; rejecting caller"
        )
        return _error_response(
            "Service misconfigured: caller auth token not set", status=503
        )
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix) or not hmac.compare_digest(
        header[len(prefix):], CALLER_TOKEN
    ):
        logger.warning("submit/poll handler rejected unauthenticated request")
        return _error_response("Unauthorized", status=401)
    return None


# --------------------------------------------------------------------- handlers


def submit_handler(request: flask.Request) -> flask.Response:
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)
    if request.method != "POST":
        return _error_response("Method not allowed. Use POST.", status=405)

    auth_error = _check_caller_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        payload = request.get_json(silent=True) or {}
        req = submit_request_from_payload(payload)
    except ValueError as exc:
        return _error_response(str(exc), status=400)

    store = JobStore(req.supabase, service=SERVICE_NAME)
    input_payload = _serialize_input(req)

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
            "action": req.action,
            "expires_at": job.get("expires_at"),
        },
        status=202,
    )


def poll_handler(request: flask.Request) -> flask.Response:
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)
    if request.method != "POST":
        return _error_response("Method not allowed. Use POST.", status=405)

    auth_error = _check_caller_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        payload = request.get_json(silent=True) or {}
        req = poll_request_from_payload(payload)
    except ValueError as exc:
        return _error_response(str(exc), status=400)

    store = JobStore(req.supabase, service=SERVICE_NAME)
    row = store.peek(req.job_id)
    if row is None:
        return _error_response("job_id not found or expired", status=404)

    status = row.get("status")
    if status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
        return _cors_response({"status": status, "job_id": req.job_id})

    consumed = store.consume_terminal(req.job_id)
    if consumed is None:
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
    return _cors_response({"status": "healthy", "service": SERVICE_NAME})


# --------------------------------------------------------------------- helpers


def _serialize_input(req) -> Dict[str, Any]:
    """Persist exactly what the worker needs to rehydrate the legacy request."""
    if req.action == "create":
        return {
            "action": "create",
            "model_name": req.create_input.model_name,
            "voice_name": req.create_input.voice_name,
            "items": req.create_input.items,
        }
    if req.action == "status":
        return {"action": "status", "batch_id": req.status_input.batch_id}
    return {
        "action": "process",
        "batch_id": req.process_input.batch_id,
        "bucket": req.process_input.bucket,
        "path_prefix": req.process_input.path_prefix,
    }


def _fire_worker(job_id: str, supabase_config) -> None:
    """Fire-and-forget POST to the worker endpoint."""
    if not WORKER_URL:
        logger.warning(
            "WORKER_URL not configured; job %s will only run if a cron requeues it",
            job_id,
        )
        return
    payload = {
        "job_id": job_id,
        "supabase": {
            "url": supabase_config.url,
            # key intentionally omitted: the worker reads
            # SUPABASE_SERVICE_ROLE_KEY from its own runtime env.
            "jobs_table": supabase_config.jobs_table,
        },
    }
    headers = {"Content-Type": "application/json"}
    if WORKER_TOKEN:
        headers["X-Worker-Token"] = WORKER_TOKEN
    try:
        requests.post(WORKER_URL, json=payload, headers=headers, timeout=(3, 0.5))
    except requests.RequestException as exc:
        # Read timeout is intentional. Log at debug.
        logger.debug("Worker fire-and-forget returned: %s", exc)


def _cors_response(body, status: int = 200) -> flask.Response:
    response = flask.make_response(json.dumps(body, ensure_ascii=False, default=str), status)
    response.headers["Content-Type"] = "application/json"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type,X-Worker-Token,Authorization"
    )
    return response


def _error_response(message: str, status: int) -> flask.Response:
    return _cors_response({"status": "error", "message": message}, status=status)


# functions-framework registration ------------------------------------------

try:  # pragma: no cover - optional dependency
    import functions_framework
except ImportError:  # pragma: no cover
    functions_framework = None

if functions_framework is not None:

    @functions_framework.http
    def submit_tts_batch_job(request: flask.Request):
        return submit_handler(request)

    @functions_framework.http
    def poll_tts_batch_job(request: flask.Request):
        return poll_handler(request)

    @functions_framework.http
    def run_tts_batch_worker(request: flask.Request):
        return worker_handler(request)

    @functions_framework.http
    def health_check(request: flask.Request):
        return health_check_handler(request)
