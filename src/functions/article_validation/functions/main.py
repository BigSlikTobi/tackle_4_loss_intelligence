"""Cloud Function entry point for the article validation service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import flask

# Ensure project root is on sys.path before importing project modules
project_root = Path(__file__).parent.parent.parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.article_validation.core.factory import request_from_payload
from src.functions.article_validation.core.service import ArticleValidationService

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def article_validation_handler(request: flask.Request) -> flask.Response:
    """HTTP handler that orchestrates article validation."""

    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    if request.method != "POST":
        logger.warning("Unsupported HTTP method: %s", request.method)
        return _error_response("Method not allowed. Use POST.", status=405)

    try:
        payload = request.get_json(silent=True) or {}
        request_model = request_from_payload(payload)
        logger.info(
            "Incoming validation request for article_type=%s (factual=%s, contextual=%s, quality=%s)",
            request_model.article_type,
            request_model.validation_config.enable_factual if request_model.validation_config else True,
            request_model.validation_config.enable_contextual if request_model.validation_config else True,
            request_model.validation_config.enable_quality if request_model.validation_config else True,
        )

        service = ArticleValidationService(request_model)
        report = _run_async(service.validate())

        response_body = {
            "status": report.status,
            "decision": report.decision,
            "is_releasable": report.is_releasable,
            "article_type": report.article_type,
            "validation_timestamp": report.validation_timestamp,
            "processing_time_ms": report.processing_time_ms,
            "factual": {
                "enabled": report.factual.enabled,
                "score": report.factual.score,
                "confidence": report.factual.confidence,
                "passed": report.factual.passed,
                "issues": [
                    {
                        "severity": issue.severity,
                        "category": issue.category,
                        "message": issue.message,
                        "location": issue.location,
                        "suggestion": issue.suggestion,
                        "source_url": issue.source_url,
                    }
                    for issue in report.factual.issues
                ],
                "details": report.factual.details,
            },
            "contextual": {
                "enabled": report.contextual.enabled,
                "score": report.contextual.score,
                "confidence": report.contextual.confidence,
                "passed": report.contextual.passed,
                "issues": [
                    {
                        "severity": issue.severity,
                        "category": issue.category,
                        "message": issue.message,
                        "location": issue.location,
                        "suggestion": issue.suggestion,
                        "source_url": issue.source_url,
                    }
                    for issue in report.contextual.issues
                ],
                "details": report.contextual.details,
            },
            "quality": {
                "enabled": report.quality.enabled,
                "score": report.quality.score,
                "confidence": report.quality.confidence,
                "passed": report.quality.passed,
                "issues": [
                    {
                        "severity": issue.severity,
                        "category": issue.category,
                        "message": issue.message,
                        "location": issue.location,
                        "suggestion": issue.suggestion,
                        "source_url": issue.source_url,
                    }
                    for issue in report.quality.issues
                ],
                "details": report.quality.details,
            },
            "rejection_reasons": report.rejection_reasons,
            "review_reasons": report.review_reasons,
        }

        if report.error:
            response_body["error"] = report.error

        logger.info(
            "Validation complete: decision=%s, releasable=%s, time=%dms",
            report.decision,
            report.is_releasable,
            report.processing_time_ms,
        )

        return _cors_response(response_body)

    except ValueError as exc:
        logger.warning("Invalid request: %s", exc)
        return _error_response(str(exc), status=400)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected failure", exc_info=True)
        return _error_response("Internal server error", status=500)


def health_check_handler(request: flask.Request) -> flask.Response:
    """Health check endpoint."""
    return _cors_response({"status": "healthy", "service": "article_validation"})


def _cors_response(body: dict[str, Any], status: int = 200) -> flask.Response:
    """Create a CORS-enabled JSON response."""
    response = flask.make_response(json.dumps(body, ensure_ascii=False), status)
    headers = response.headers
    headers["Content-Type"] = "application/json"
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _error_response(message: str, status: int) -> flask.Response:
    """Create an error response with CORS headers."""
    return _cors_response({"status": "error", "message": message}, status=status)


def _run_async(coro):
    """Run an async coroutine in a new or existing event loop."""
    try:
        return asyncio.run(coro)
    except RuntimeError as exc:
        if "event loop" in str(exc).lower():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        raise


# Optional functions-framework registration for local tooling parity
try:  # pragma: no cover - optional dependency
    import functions_framework
except ImportError:  # pragma: no cover
    functions_framework = None

if functions_framework is not None:

    @functions_framework.http
    def validate_article(request: flask.Request):
        """Entry point for functions-framework."""
        return article_validation_handler(request)

    @functions_framework.http
    def health_check(request: flask.Request):
        """Health check entry point."""
        return health_check_handler(request)
