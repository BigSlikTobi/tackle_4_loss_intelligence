"""URL content extraction service handler."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.url_content_extraction.core.contracts.extracted_content import (
    ExtractedContent,
)
from src.functions.url_content_extraction.core.extractors.extractor_factory import (
    get_extractor,
)
from src.functions.url_content_extraction.core.utils import amp_detector

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_MAX_PARAGRAPHS = 120
DEFAULT_MIN_PARAGRAPH_CHARS = 240


def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structured content for each requested URL."""

    urls = request.get("urls") or []
    if not isinstance(urls, list) or not urls:
        return {
            "status": "error",
            "message": "Request must include a non-empty 'urls' list",
        }

    defaults = _as_mapping(request.get("defaults"))
    base_options = _as_mapping(request.get("options"))

    articles: List[Dict[str, Any]] = []
    for entry in urls:
        try:
            url, metadata = _normalise_url_entry(entry)
        except ValueError as exc:
            articles.append({"error": str(exc)})
            continue

        merged_meta = {**defaults, **metadata}
        options = _build_options(merged_meta, base_options)
        timeout_seconds = _coalesce_int(
            merged_meta.get("timeout_seconds"),
            defaults.get("timeout_seconds"),
            base_options.get("timeout_seconds"),
            DEFAULT_TIMEOUT_SECONDS,
        )

        target_url = url
        amp_used = False
        if not options.get("force_playwright", False):
            target_url, amp_used = _prefer_amp_variant(url, logger=logger)
            if amp_used:
                options["prefer_lightweight"] = True
                metadata.setdefault("amp_url", target_url)
                metadata["used_amp"] = True

        try:
            extractor = get_extractor(
                target_url,
                force_playwright=options.get("force_playwright", False),
                prefer_lightweight=options.get("prefer_lightweight", False),
                logger=logger,
            )
            extracted = extractor.extract(
                target_url,
                timeout=timeout_seconds,
                options=options,
            )
        except Exception as exc:  # noqa: BLE001 - propagate extraction failure
            logger.warning("Extraction failed for %s: %s", url, exc)
            failure = {"url": url, "error": str(exc)}
            if amp_used:
                failure["amp_url"] = target_url
                failure["used_amp"] = True
            failure.update({k: v for k, v in metadata.items() if k not in failure})
            articles.append(failure)
            continue

        payload = _serialise_content(extracted)
        if amp_used:
            payload["url"] = url
            payload["amp_url"] = target_url
            payload["used_amp"] = True
            payload.setdefault("original_url", url)
        if not extracted.is_valid():
            payload["error"] = extracted.error or "Insufficient content extracted"
            logger.debug("Extractor returned invalid content for %s", url)

        # Preserve incoming metadata fields not already present in response
        for key, value in metadata.items():
            if key not in payload and value is not None:
                payload[key] = value

        articles.append(payload)

    succeeded = sum(1 for article in articles if "error" not in article)
    return {
        "status": "success" if succeeded else "partial",
        "counts": {"total": len(articles), "succeeded": succeeded},
        "articles": articles,
    }


def _normalise_url_entry(entry: Any) -> Tuple[str, Dict[str, Any]]:
    if isinstance(entry, str):
        return entry, {}
    if isinstance(entry, dict):
        url = entry.get("url") or entry.get("link")
        if not url or not isinstance(url, str):
            raise ValueError("URL entries must include a valid 'url' field")
        return url, entry
    raise ValueError("Every entry in 'urls' must be a string or object with a 'url' field")


def _as_mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _build_options(metadata: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    options = {**base.get("options", {}), **metadata.get("options", {}), **base}
    options.setdefault(
        "force_playwright",
        _coalesce_bool(metadata.get("force_playwright"), base.get("force_playwright")),
    )
    options.setdefault(
        "prefer_lightweight",
        _coalesce_bool(metadata.get("prefer_lightweight"), base.get("prefer_lightweight"), False),
    )
    options["max_paragraphs"] = _coalesce_int(
        metadata.get("max_paragraphs"),
        base.get("max_paragraphs"),
        DEFAULT_MAX_PARAGRAPHS,
    )
    min_chars = _coalesce_int(
        metadata.get("min_paragraph_chars"),
        base.get("min_paragraph_chars"),
        DEFAULT_MIN_PARAGRAPH_CHARS,
    )
    if min_chars:
        options["min_paragraph_chars"] = min_chars
    return {key: value for key, value in options.items() if value is not None}


def _coalesce_bool(*values: Any, default: bool | None = None) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
    return bool(default) if default is not None else False


def _coalesce_int(*values: Any, default: int | None = None) -> int:
    for value in values:
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return int(default) if default is not None else 0


def _serialise_content(content: ExtractedContent) -> Dict[str, Any]:
    paragraphs = [paragraph.strip() for paragraph in content.paragraphs if paragraph and paragraph.strip()]
    text = "\n\n".join(paragraphs)
    response: Dict[str, Any] = {
        "url": content.url,
        "title": content.title,
        "description": content.description,
        "author": content.author,
        "quotes": content.quotes,
        "paragraphs": paragraphs,
        "content": text,
        "word_count": len(text.split()),
    }
    if content.published_at:
        response["published_at"] = _isoformat(content.published_at)
    if content.metadata:
        response["metadata"] = {
            "fetched_at": _isoformat(content.metadata.fetched_at),
            "extractor": content.metadata.extractor,
            "duration_seconds": content.metadata.duration_seconds,
            "page_language": content.metadata.page_language,
            "raw_url": content.metadata.raw_url,
        }
    if content.error:
        response["error"] = content.error
    return response


def _isoformat(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _prefer_amp_variant(
    url: str,
    *,
    logger: logging.Logger,
) -> tuple[str, bool]:
    try:
        return amp_detector.probe_for_amp(url, logger=logger)
    except Exception as exc:  # pragma: no cover - defensive safety
        logger.debug("AMP probe raised for %s: %s", url, exc)
        return url, False

