"""Cloud Function entry point for package assembly.

This file is the entry point for the data_loading Cloud Function.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import flask

from ...core.packaging import assemble_package


def package_handler(request: flask.Request) -> flask.Response:
    """HTTP Cloud Function entry point for package assembly.
    
    Args:
        request: Flask request object
        
    Returns:
        Flask response with assembled package or error message
    """
    # Handle CORS preflight
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    # Only accept POST requests
    if request.method != "POST":
        return _error_response("Only POST requests are supported", status=405)

    # Parse JSON payload
    try:
        payload = request.get_json(force=True)
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
    except Exception as exc:
        logging.error(f"Invalid JSON body: {exc}")
        return _error_response(f"Invalid JSON body: {exc}", status=400)

    # Assemble package
    try:
        envelope = assemble_package(payload)
    except ValueError as exc:
        logging.error(f"Package assembly validation error: {exc}")
        return _error_response(str(exc), status=400)
    except Exception as exc:
        logging.exception("Failed to assemble package")
        return _error_response("Internal server error", status=500)

    return _cors_response(envelope.to_dict())


def _cors_response(body: dict[str, Any], status: int = 200) -> flask.Response:
    """Create a CORS-enabled response."""
    response = flask.make_response(json.dumps(body, ensure_ascii=False), status)
    response.headers["Content-Type"] = "application/json"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _error_response(message: str, status: int) -> flask.Response:
    """Create an error response."""
    return _cors_response({"error": message}, status=status)
