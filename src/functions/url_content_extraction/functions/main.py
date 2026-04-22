"""URL content extraction service handler."""

from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.shared.db.connection import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.url_content_extraction.core.contracts.extracted_content import (
    ExtractedContent,
)
from src.functions.url_content_extraction.core.db import EphemeralContentWriter
from src.functions.url_content_extraction.core.extractors.extractor_factory import (
    get_extractor,
)
from src.functions.url_content_extraction.core.utils import amp_detector

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Import fact extraction post-processor
try:
    from src.functions.url_content_extraction.core.post_processors.fact_extraction import (
        extract_and_store_facts,
    )
    FACT_EXTRACTION_AVAILABLE = True
except ImportError:
    FACT_EXTRACTION_AVAILABLE = False
    logger.warning("Fact extraction post-processor not available")

DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_MAX_PARAGRAPHS = 120
DEFAULT_MIN_PARAGRAPH_CHARS = 240
WORKER_TOKEN_HEADER = "X-Worker-Token"


def authenticate(headers: Optional[Mapping[str, str]]) -> Optional[Dict[str, Any]]:
    """Validate the shared-secret header.

    Returns ``None`` when the request is authorized (or auth is disabled
    because ``WORKER_TOKEN`` is unset, e.g. local dev). Returns an error
    payload dict (with ``status_code``) when auth fails.

    Constant-time comparison via :func:`hmac.compare_digest` defends against
    timing oracles. Header lookup is case-insensitive.
    """
    expected = os.getenv("WORKER_TOKEN")
    if not expected:
        return None  # Auth disabled (local dev / explicit opt-out at deploy).

    provided = ""
    if headers:
        # Flask's EnvironHeaders is case-insensitive; plain dicts are not.
        try:
            provided = headers.get(WORKER_TOKEN_HEADER) or ""
        except Exception:
            provided = ""
        if not provided and isinstance(headers, dict):
            for k, v in headers.items():
                if isinstance(k, str) and k.lower() == WORKER_TOKEN_HEADER.lower():
                    provided = v or ""
                    break

    if not provided or not hmac.compare_digest(str(provided), str(expected)):
        return {
            "status": "error",
            "message": "Unauthorized: missing or invalid worker token",
            "status_code": 401,
        }
    return None


def handle_request(
    request: Dict[str, Any],
    *,
    headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Extract structured content for each requested URL.

    Supports optional fact extraction via enable_fact_extraction flag.
    For real-time processing of 1-10 articles with fact extraction.
    For bulk backlog processing (1000+ articles), use backlog_processor.py instead.

    When ``persist_ephemeral`` is true in the request payload the extracted
    body is upserted into ``news_url_content_ephemeral`` so downstream
    consumers can read it instead of re-fetching the URL. Requires either a
    ``supabase`` block in the request or ``SUPABASE_URL``/``SUPABASE_KEY``
    in the environment.
    """

    auth_error = authenticate(headers)
    if auth_error is not None:
        return auth_error

    urls = request.get("urls") or []
    if not isinstance(urls, list) or not urls:
        return {
            "status": "error",
            "message": "Request must include a non-empty 'urls' list",
        }

    persist_ephemeral = bool(request.get("persist_ephemeral"))
    ephemeral_ttl_hours = request.get("ephemeral_ttl_hours")
    if ephemeral_ttl_hours is not None:
        try:
            ephemeral_ttl_hours = int(ephemeral_ttl_hours)
        except (TypeError, ValueError):
            ephemeral_ttl_hours = None
    skip_response_body = bool(request.get("skip_response_body"))

    ephemeral_writer: Optional[EphemeralContentWriter] = None
    if persist_ephemeral:
        ephemeral_writer = _build_ephemeral_writer(request)
        if ephemeral_writer is None:
            logger.warning(
                "persist_ephemeral requested but Supabase credentials are missing; "
                "skipping ephemeral writes"
            )

    # Check if fact extraction is enabled
    enable_fact_extraction = request.get("enable_fact_extraction", False)
    
    # Extract fact extraction configs (with fallback to environment)
    fact_config = None
    if enable_fact_extraction and FACT_EXTRACTION_AVAILABLE:
        fact_config = _build_fact_extraction_config(request)
        if not fact_config:
            logger.warning("Fact extraction requested but config incomplete, skipping")
            enable_fact_extraction = False

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
            logger.warning("Extraction failed for %s", url, exc_info=True)
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

        # Optional ephemeral handoff: write the body so downstream consumers
        # can read instead of re-fetching. Skips invalid/empty extractions.
        if (
            ephemeral_writer is not None
            and "error" not in payload
            and payload.get("content")
        ):
            news_url_id = metadata.get("news_url_id") or metadata.get("id")
            if news_url_id:
                try:
                    ephemeral_writer.upsert_one(
                        extracted.to_ephemeral_row(news_url_id),
                        ttl_hours=ephemeral_ttl_hours,
                    )
                    payload["ephemeral_persisted"] = True
                except Exception as exc:
                    logger.warning(
                        "Ephemeral upsert failed for %s: %s", news_url_id, exc
                    )
                    payload["ephemeral_persisted"] = False
            else:
                logger.debug(
                    "persist_ephemeral set but request did not supply news_url_id "
                    "for %s; skipping",
                    url,
                )

        # Optional fact extraction (for real-time processing)
        if enable_fact_extraction and fact_config and "error" not in payload:
            news_url_id = metadata.get("news_url_id") or metadata.get("id")
            if news_url_id and payload.get("content"):
                try:
                    fact_result = extract_and_store_facts(
                        article_content=payload["content"],
                        news_url_id=news_url_id,
                        supabase_config=fact_config["supabase"],
                        llm_config=fact_config["llm"],
                        embedding_config=fact_config["embedding"],
                    )
                    
                    # Add fact extraction results to response
                    payload["facts_count"] = fact_result.get("facts_count", 0)
                    payload["facts_extracted"] = fact_result.get("facts_extracted", False)
                    payload["embedding_count"] = fact_result.get("embedding_count", 0)
                    
                    if fact_result.get("error"):
                        payload["facts_error"] = fact_result["error"]
                        logger.warning(
                            f"Fact extraction failed for {news_url_id}: {fact_result['error']}"
                        )
                    else:
                        logger.info(
                            f"Fact extraction complete for {news_url_id}: "
                            f"{fact_result['facts_count']} facts, "
                            f"{fact_result['embedding_count']} embeddings"
                        )
                except Exception as e:
                    logger.error(f"Fact extraction error for {news_url_id}: {e}", exc_info=True)
                    payload["facts_error"] = str(e)
                    payload["facts_extracted"] = False
            else:
                if not news_url_id:
                    logger.debug("Skipping fact extraction: no news_url_id in metadata")
                if not payload.get("content"):
                    logger.debug("Skipping fact extraction: no content extracted")

        if skip_response_body and "error" not in payload:
            # Caller signaled they'll read content from the ephemeral table
            # instead — strip the heavy fields to slim the response.
            payload.pop("content", None)
            payload.pop("paragraphs", None)
            payload["body_omitted"] = True

        articles.append(payload)

    succeeded = sum(1 for article in articles if "error" not in article)
    return {
        "status": "success" if succeeded else "partial",
        "counts": {"total": len(articles), "succeeded": succeeded},
        "articles": articles,
    }


def _build_ephemeral_writer(
    request: Dict[str, Any],
) -> Optional[EphemeralContentWriter]:
    """Construct a Supabase-backed ephemeral writer using request creds first,
    then env vars. Returns ``None`` when no credentials are available.

    Per-request creds (image_selection pattern) let external callers drive
    the function without sharing the deploy-time service-role key.
    """
    sb = request.get("supabase") if isinstance(request.get("supabase"), dict) else {}
    url = sb.get("url") or os.getenv("SUPABASE_URL")
    key = sb.get("key") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        if sb.get("url") or sb.get("key"):
            from supabase import create_client

            client = create_client(url, key)
        else:
            client = get_supabase_client()
    except Exception as exc:
        logger.warning("Failed to build Supabase client for ephemeral writes: %s", exc)
        return None
    return EphemeralContentWriter(client)


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
    # Precedence (lowest → highest): base top-level < base.options < metadata
    # top-level < metadata.options. Previously `base` was merged last, so
    # top-level base keys silently overrode both `options` blocks, inverting
    # the expected precedence.
    def _scrub(d: Dict[str, Any]) -> Dict[str, Any]:
        # Drop the nested 'options' key so it doesn't collide with its flattened form.
        return {k: v for k, v in d.items() if k != "options"}

    options: Dict[str, Any] = {}
    options.update(_scrub(base))
    options.update(base.get("options") or {})
    options.update(_scrub(metadata))
    options.update(metadata.get("options") or {})
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


def _build_fact_extraction_config(request: Dict[str, Any]) -> Dict[str, Dict[str, str]] | None:
    """Build fact extraction configuration from request with environment fallbacks.
    
    Args:
        request: Request dict with optional supabase, llm, and embedding configs
        
    Returns:
        Config dict with supabase, llm, and embedding sections, or None if incomplete
    """
    # Supabase config (required)
    supabase_config = request.get("supabase", {})
    supabase_url = supabase_config.get("url") or os.getenv("SUPABASE_URL")
    supabase_key = supabase_config.get("key") or os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        logger.error("Fact extraction requires Supabase credentials (url and key)")
        return None
    
    # LLM config (required)
    llm_config = request.get("llm", {})
    llm_api_url = llm_config.get("api_url") or "https://generativelanguage.googleapis.com/v1beta/models"
    llm_api_key = llm_config.get("api_key") or os.getenv("GEMINI_API_KEY")
    llm_model = llm_config.get("model") or os.getenv("FACT_LLM_MODEL", "gemma-3n-e4b-it")
    
    if not llm_api_key:
        logger.error("Fact extraction requires LLM API key (GEMINI_API_KEY)")
        return None
    
    # Embedding config (required)
    embedding_config = request.get("embedding", {})
    embedding_api_url = embedding_config.get("api_url") or "https://api.openai.com/v1/embeddings"
    embedding_api_key = embedding_config.get("api_key") or os.getenv("OPENAI_API_KEY")
    embedding_model = embedding_config.get("model") or os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    
    if not embedding_api_key:
        logger.error("Fact extraction requires embedding API key (OPENAI_API_KEY)")
        return None
    
    return {
        "supabase": {
            "url": supabase_url,
            "key": supabase_key,
        },
        "llm": {
            "api_url": llm_api_url,
            "api_key": llm_api_key,
            "model": llm_model,
        },
        "embedding": {
            "api_url": embedding_api_url,
            "api_key": embedding_api_key,
            "model": embedding_model,
        },
    }

