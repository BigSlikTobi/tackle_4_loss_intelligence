"""Cloud Function entry point for news extraction.

This function is deployed independently from data_loading.
"""

from __future__ import annotations
import logging
from typing import Any
import flask

# Use shared logging
from src.shared.utils.logging import setup_logging

# TODO: Import from news_extraction core when implemented
# from ..core.pipelines.extraction_pipeline import extract_news_urls
# from ..core.contracts import NewsExtractionRequest

setup_logging()
logger = logging.getLogger(__name__)


def news_extractor(request: flask.Request) -> flask.Response:
    """Handle news extraction requests.
    
    Args:
        request: Flask request object with JSON payload
    
    Returns:
        Flask response with extracted news URLs
    """
    
    if request.method == "OPTIONS":
        return _cors_response({}, 204)
    
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
    
    try:
        payload = request.get_json(silent=True)
        if payload is None:
            return _error_response("Invalid or missing JSON payload", 400)

        # TODO: Implement extraction logic
        # extraction_request = NewsExtractionRequest.from_dict(payload)
        # results = extract_news_urls(extraction_request)

        # Explicitly fail until the pipeline is wired in.
        return _cors_response(
            {
                "status": "not_implemented",
                "message": "News extraction pipeline is not wired in yet.",
            },
            status=501,
        )
        
    except Exception as exc:
        logger.exception("News extraction failed")
        return _error_response(str(exc), 500)


def _cors_response(data: dict[str, Any], status: int = 200) -> flask.Response:
    """Create CORS-enabled response."""
    response = flask.jsonify(data)
    response.status_code = status
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _error_response(message: str, status: int = 400) -> flask.Response:
    """Create error response."""
    return _cors_response({"error": message, "status": status}, status)
