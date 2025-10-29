"""Deployment wrapper for the article translation Cloud Function."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

import flask

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.functions.article_translation.functions.main import handle_request

logger = logging.getLogger(__name__)


def article_translation_handler(request: flask.Request) -> flask.Response:
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    if request.method != "POST":
        return _cors_response({"status": "error", "message": "Method not allowed. Use POST."}, status=405)

    try:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        result = handle_request(payload)
        status_code = 200 if result.get("status") == "success" else 400
        return _cors_response(result, status=status_code)
    except Exception as exc:
        logger.exception("Unexpected error in article translation handler")
        return _cors_response(
            {"status": "error", "message": f"Internal error: {exc}"},
            status=500
        )


def _cors_response(body: Dict[str, Any] | list[Any], status: int = 200) -> flask.Response:
    response = flask.make_response(json.dumps(body, ensure_ascii=False), status)
    headers = response.headers
    headers["Content-Type"] = "application/json; charset=utf-8"
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response
