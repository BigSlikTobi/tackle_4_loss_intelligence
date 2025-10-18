"""Cloud Function entry point for the image selection service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import flask

# Ensure project root is on sys.path before importing project modules
project_root = Path(__file__).parent.parent.parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.image_selection.core.factory import request_from_payload
from src.functions.image_selection.core.service import ImageSelectionService

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def image_selection_handler(request: flask.Request) -> flask.Response:
    """HTTP handler that orchestrates image selection."""

    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    if request.method != "POST":
        logger.warning("Unsupported HTTP method: %s", request.method)
        return _error_response("Method not allowed. Use POST.", status=405)

    try:
        payload = request.get_json(silent=True) or {}
        request_model = request_from_payload(payload)
        logger.info(
            "Incoming image selection request for %s images (LLM enabled=%s)",
            request_model.num_images,
            request_model.enable_llm,
        )

        service = ImageSelectionService(request_model)
        results = _run_async(service.process())

        response_body = {
            "status": "success",
            "query": getattr(service, "resolved_query", None)
            or request_model.explicit_query
            or request_model.article_text,
            "count": len(results),
            "images": [
                {
                    "image_url": image.public_url,
                    "original_url": image.original_url,
                    "author": image.author,
                    "source": image.source,
                    "width": image.width,
                    "height": image.height,
                    "title": image.title,
                }
                for image in results
            ],
        }

        return _cors_response(response_body)
    except ValueError as exc:
        logger.warning("Invalid request: %s", exc)
        return _error_response(str(exc), status=400)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected failure", exc_info=True)
        return _error_response("Internal server error", status=500)


def health_check_handler(request: flask.Request) -> flask.Response:
    """Health check endpoint."""

    return _cors_response({"status": "healthy", "service": "image_selection"})


def _cors_response(body: dict[str, Any] | Iterable[Any], status: int = 200) -> flask.Response:
    response = flask.make_response(json.dumps(body, ensure_ascii=False), status)
    headers = response.headers
    headers["Content-Type"] = "application/json"
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _error_response(message: str, status: int) -> flask.Response:
    return _cors_response({"status": "error", "message": message}, status=status)


def _run_async(coro):
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
    def select_article_images(request: flask.Request):
        return image_selection_handler(request)

    @functions_framework.http
    def health_check(request: flask.Request):
        return health_check_handler(request)
