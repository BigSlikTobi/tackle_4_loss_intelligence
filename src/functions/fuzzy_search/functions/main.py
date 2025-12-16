"""HTTP entrypoint for the fuzzy search Cloud Function."""

from __future__ import annotations

import logging
import os
from typing import Any

import functions_framework
from flask import Request, jsonify

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.fuzzy_search.core.config import FuzzySearchRequest
from src.functions.fuzzy_search.core.search_service import FuzzySearchService

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
service = FuzzySearchService()


@functions_framework.http
def fuzzy_search(request: Request) -> tuple[Any, int]:
    """Handle HTTP requests for fuzzy search queries."""

    payload = request.get_json(silent=True) or {}
    logger.info("Received fuzzy search request with keys: %s", list(payload.keys()))

    try:
        search_request = FuzzySearchRequest.from_dict(payload)
        results = service.search(search_request)
        return jsonify({"results": [result.to_dict() for result in results]}), 200
    except ValueError as exc:
        logger.warning("Invalid fuzzy search request: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive server guard
        logger.exception("Unexpected error while running fuzzy search: %s", exc)
        return jsonify({"error": "Internal server error"}), 500
