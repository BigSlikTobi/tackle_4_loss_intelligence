"""
Google Cloud Function entry point for content summarization.

Provides HTTP API for triggering content summarization jobs.
"""

import logging
import os
from typing import Any

import functions_framework
from flask import Request, jsonify

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.content_summarization.core.db import NewsUrlReader, SummaryWriter
from src.functions.content_summarization.core.llm import GeminiClient
from src.functions.content_summarization.core.pipelines import SummarizationPipeline

# Load environment and setup logging
load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))

logger = logging.getLogger(__name__)


@functions_framework.http
def summarize_content(request: Request) -> tuple[Any, int]:
    """
    HTTP endpoint for content summarization.

    Accepts JSON POST requests with the following parameters:
    - limit (int, optional): Maximum number of URLs to process
    - publisher (str, optional): Filter by publisher name
    - url_ids (list[str], optional): Specific URL IDs to process
    - model (str, optional): Gemini model to use
    - enable_grounding (bool, optional): Enable Google Search grounding

    Returns:
        JSON response with processing statistics

    Examples:
        POST /summarize_content
        {
            "limit": 10,
            "publisher": "ESPN"
        }

        POST /summarize_content
        {
            "url_ids": ["uuid1", "uuid2", "uuid3"],
            "enable_grounding": true
        }
    """
    try:
        # Parse request
        request_json = request.get_json(silent=True) or {}

        limit = request_json.get("limit")
        publisher = request_json.get("publisher")
        url_ids = request_json.get("url_ids")
        model = request_json.get("model", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
        enable_grounding = request_json.get("enable_grounding", False)

        logger.info(
            f"Received summarization request: limit={limit}, "
            f"publisher={publisher}, url_ids={url_ids}, "
            f"model={model}, grounding={enable_grounding}"
        )

        # Validate environment
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            logger.error("GEMINI_API_KEY not configured")
            return jsonify({"error": "Server configuration error"}), 500

        # Initialize components
        gemini_client = GeminiClient(
            api_key=gemini_api_key,
            model=model,
            enable_grounding=enable_grounding,
        )

        url_reader = NewsUrlReader()
        summary_writer = SummaryWriter(dry_run=False)

        pipeline = SummarizationPipeline(
            gemini_client=gemini_client,
            url_reader=url_reader,
            summary_writer=summary_writer,
            continue_on_error=True,
        )

        # Process based on request parameters
        if url_ids:
            logger.info(f"Processing {len(url_ids)} specific URL IDs")
            stats = pipeline.process_by_ids(url_ids)
        elif publisher:
            logger.info(f"Processing URLs from publisher: {publisher}")
            stats = pipeline.process_by_publisher(publisher=publisher, limit=limit)
        else:
            logger.info("Processing all unsummarized URLs")
            stats = pipeline.process_unsummarized_urls(limit=limit)

        # Build response
        response = {
            "status": "success",
            "statistics": {
                "total": stats["total"],
                "successful": stats["successful"],
                "failed": stats["failed"],
                "skipped": stats["skipped"],
            },
            "errors": stats["errors"][:10] if stats["errors"] else [],  # Limit to 10 errors
        }

        logger.info(
            f"Summarization complete: {stats['successful']} successful, "
            f"{stats['failed']} failed, {stats['skipped']} skipped"
        )

        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Request failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@functions_framework.http
def health_check(request: Request) -> tuple[Any, int]:
    """
    Health check endpoint.

    Returns:
        Simple health status
    """
    return jsonify({"status": "healthy", "service": "content_summarization"}), 200
