"""Cloud Function entry point for news extraction.

This function is deployed independently from data_loading. It accepts an
optional ``supabase`` credentials block in the request payload so callers can
run the function with request-scoped credentials (matching the
``image_selection`` pattern documented in CLAUDE.md).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import flask

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.news_extraction.core.db import NewsUrlWriter
from src.functions.news_extraction.core.db.watermarks import NewsSourceWatermarkStore
from src.functions.news_extraction.core.pipelines import NewsExtractionPipeline

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def handle_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run a news-extraction invocation from a JSON payload.

    Supported keys (all optional):
        source_filter (str): case-insensitive substring filter over source names.
        days_back (int): override per-source ``days_back`` filter.
        max_articles (int): override per-source ``max_articles`` filter.
        dry_run (bool): if True, don't write to the database.
        clear (bool): if True, clear the target table before writing.
        max_workers (int): override parallel-worker count.
        supabase (dict): optional ``{"url": ..., "key": ...}`` credentials block.
            When provided, a request-scoped Supabase client is passed to the
            writer and watermark store. When omitted, both fall back to the
            module's shared client (i.e. the deploy-time env vars).

    Returns the pipeline result dictionary, or an error envelope.
    """
    if not isinstance(payload, dict):
        return _error("Request body must be a JSON object")

    client = _build_supabase_client(payload.get("supabase"))

    source_filter = _coerce_str(payload.get("source_filter"))
    days_back = _coerce_int(payload.get("days_back"))
    max_articles = _coerce_int(payload.get("max_articles"))
    max_workers = _coerce_int(payload.get("max_workers"))
    dry_run = bool(payload.get("dry_run", False))
    clear = bool(payload.get("clear", False))

    try:
        writer = None if dry_run else NewsUrlWriter(client=client) if client is not None else NewsUrlWriter()
        watermark_store = (
            NewsSourceWatermarkStore(client=client)
            if client is not None
            else NewsSourceWatermarkStore()
        )
        pipeline = NewsExtractionPipeline(
            writer=writer,
            watermark_store=watermark_store,
            max_workers=max_workers,
        )
    except Exception as exc:
        logger.exception("Failed to initialize news extraction pipeline")
        return _error(f"Pipeline initialization failed: {exc}")

    try:
        result = pipeline.extract(
            source_filter=source_filter,
            days_back=days_back,
            max_articles=max_articles,
            dry_run=dry_run,
            clear=clear,
        )
    except Exception as exc:
        logger.exception("News extraction failed")
        return _error(str(exc))
    finally:
        pipeline.close()

    # Drop non-JSON-serializable or bulky fields before returning.
    result.pop("records", None)
    return result


def news_extractor(request: flask.Request) -> flask.Response:
    """Flask entry point used by Cloud Functions."""
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    if request.method != "POST":
        return _cors_response({"error": "Method not allowed", "status": 405}, status=405)

    payload = request.get_json(silent=True) or {}
    result = handle_request(payload)
    status = 200 if result.get("success", True) else 500
    return _cors_response(result, status=status)


def _build_supabase_client(block: Any) -> Optional[Any]:
    """Create a Supabase client from an in-request credentials block.

    Returns None when no block is supplied so callers fall back to the
    deploy-time environment credentials.
    """
    if not isinstance(block, dict):
        return None
    url = block.get("url")
    key = block.get("key")
    if not url or not key:
        logger.warning("supabase block present but missing url/key; ignoring")
        return None
    try:
        from supabase import create_client

        return create_client(url, key)
    except Exception as exc:
        logger.warning("Failed to build request-scoped Supabase client: %s", exc)
        return None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cors_response(body: Dict[str, Any], status: int = 200) -> flask.Response:
    response = flask.make_response(json.dumps(body, ensure_ascii=False, default=str), status)
    headers = response.headers
    headers["Content-Type"] = "application/json"
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response


def _error(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}
