"""Article translation service handler."""

from __future__ import annotations

import copy
import logging
import os
from typing import Any, Dict, List

from pydantic import ValidationError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
    RetryCallState,
)

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.article_translation.core.contracts.translated_article import (
    TranslationRequest,
)
from src.functions.article_translation.core.llm.openai_translator import (
    OpenAITranslationClient,
)

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def _log_retry_attempt(retry_state: RetryCallState) -> None:
    """Log detailed information about each retry attempt."""
    attempt = retry_state.attempt_number
    if retry_state.outcome and retry_state.outcome.failed:
        exception = retry_state.outcome.exception()
        logger.warning(
            "TRANSLATION_RETRY_ATTEMPT_%d: Retrying translation due to %s: %s",
            attempt,
            type(exception).__name__,
            str(exception)[:200],
            extra={
                "retry_attempt": attempt,
                "error_type": type(exception).__name__,
                "will_retry": attempt < 3
            }
        )


# Retry configuration for LLM translation failures
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((RuntimeError, ConnectionError, TimeoutError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    after=_log_retry_attempt,
    reraise=True,
)
def _translate_with_retry(
    client: OpenAITranslationClient,
    request_model: TranslationRequest,
    options: Dict[str, Any] | None,
) -> Any:
    """Execute translation with automatic retry on transient failures."""
    return client.translate(request_model, options=options)


def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Translate an English article into the requested target language."""

    article_input = request.get("article")
    if not isinstance(article_input, dict):
        return {
            "status": "error",
            "message": "Request must include an 'article' object",
        }

    target_language = (request.get("target_language") or article_input.get("language"))
    if not target_language:
        return {
            "status": "error",
            "message": "Target language must be provided as 'target_language'",
        }

    paragraphs = article_input.get("content")
    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    if not isinstance(paragraphs, list) or not paragraphs:
        return {
            "status": "error",
            "message": "Article content must be a non-empty list of paragraphs",
        }

    preserve_terms = _collect_terms(
        request.get("preserve_terms"),
        article_input.get("preserve_terms"),
    )

    try:
        request_model = TranslationRequest(
            article_id=article_input.get("article_id") or article_input.get("id"),
            language=str(target_language),
            source_language=
                request.get("source_language")
                or article_input.get("source_language")
                or "en",
            headline=article_input.get("headline", ""),
            sub_header=article_input.get("sub_header") or article_input.get("subHeader", ""),
            introduction_paragraph=article_input.get("introduction_paragraph")
            or article_input.get("introductionParagraph", ""),
            content=[str(paragraph) for paragraph in paragraphs],
            preserve_terms=preserve_terms,
        )
    except ValidationError as exc:
        return {"status": "error", "message": _format_validation_error(exc)}

    api_key = _resolve_api_key(
        request.get("llm"),
        request.get("openai"),
        request.get("secrets"),
        request.get("auth"),
    )
    model_override = None
    for block in (request.get("llm"), request.get("openai")):
        if isinstance(block, dict) and block.get("model"):
            model_override = block["model"]
            break

    try:
        client = OpenAITranslationClient(
            api_key=api_key,
            model=model_override or "gpt-5-mini",
            logger=logger,
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    base_options = request.get("options") if isinstance(request.get("options"), dict) else {}
    merged_options = _merge_options(base_options, request.get("llm_options"))
    
    # If caller doesn't specify timeout, use a safe default that leaves buffer for response handling
    # Ensure OpenAI timeout is always less than HTTP timeout to avoid connection drops
    if "request_timeout_seconds" not in merged_options:
        # Default to 360 seconds (6 minutes) - leaves 60s buffer for 420s HTTP timeout
        merged_options["request_timeout_seconds"] = 360
        logger.debug("Using default OpenAI timeout: 360 seconds")

    # Use retry wrapper for translation - will attempt up to 3 times
    attempt_count = 0
    try:
        translated = _translate_with_retry(
            client,
            request_model,
            options=merged_options if merged_options else None,
        )
        
        # Log successful translation (especially if it took multiple attempts)
        logger.info(
            "Translation successful: article_id=%s, language=%s->%s, has_error=%s",
            request_model.article_id or "<unknown>",
            request_model.source_language,
            request_model.language,
            bool(translated.error),
        )
        
    except Exception as exc:  # noqa: BLE001 - expose translation failures to caller
        # Log comprehensive failure information for monitoring
        error_details = {
            "article_id": request_model.article_id or "<unknown>",
            "source_language": request_model.source_language,
            "target_language": request_model.language,
            "headline": request_model.headline[:100] if request_model.headline else None,
            "content_length": len(request_model.content),
            "content_word_count": sum(len(p.split()) for p in request_model.content),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "model": model_override or "gpt-5-mini",
        }
        
        logger.error(
            "TRANSLATION_FAILURE_AFTER_RETRIES: Article translation failed after 3 attempts. "
            "Details: %s",
            error_details,
            extra={"translation_failure": error_details}
        )
        
        # Also log to structured format for easy querying
        logger.error(
            "Translation failed: article_id=%s, language=%s->%s, error=%s",
            error_details["article_id"],
            error_details["source_language"],
            error_details["target_language"],
            error_details["error_type"],
        )
        
        return {
            "status": "error",
            "message": f"Translation failed after 3 attempts: {exc}",
            "error_details": error_details
        }

    if not translated.content:
        logger.warning(
            "TRANSLATION_EMPTY_CONTENT: Translation returned empty content for %s; using source text instead",
            request_model.article_id or "<unknown>",
        )
        translated.content = request_model.content
        translated.compute_word_count()
        if not translated.error:
            translated.error = "Translation unavailable; returning source content"
        translated.language = request_model.language
        translated.source_article_id = translated.source_article_id or request_model.article_id
        if not translated.preserved_terms:
            translated.preserved_terms = request_model.preserve_terms

    article_payload: Dict[str, Any] = {
        "language": translated.language,
        "headline": translated.headline,
        "sub_header": translated.sub_header,
        "introduction_paragraph": translated.introduction_paragraph,
        "content": translated.content,
        "word_count": translated.word_count,
        "error": translated.error,
        "source_article_id": translated.source_article_id,
        "preserved_terms": translated.preserved_terms,
    }

    final_status = "success" if not translated.error else "partial"
    
    # Log final result summary
    logger.info(
        "TRANSLATION_COMPLETE: status=%s, article_id=%s, language=%s, "
        "word_count=%d, has_error=%s",
        final_status,
        request_model.article_id or "<unknown>",
        translated.language,
        translated.word_count,
        bool(translated.error),
        extra={
            "status": final_status,
            "article_id": request_model.article_id,
            "target_language": translated.language,
            "word_count": translated.word_count,
            "error": translated.error,
        }
    )

    return {
        "status": final_status,
        "article": article_payload,
    }


def _resolve_api_key(*blocks: Any) -> str | None:
    for block in blocks:
        if isinstance(block, dict):
            for key_name in ("api_key", "key", "token"):
                key_value = block.get(key_name)
                if key_value:
                    return key_value
    return None


def _merge_options(base: Dict[str, Any], override: Any) -> Dict[str, Any]:
    merged = copy.deepcopy(base) if base else {}
    if isinstance(override, dict):
        merged.update(override)
    return merged


def _collect_terms(*sources: Any) -> List[str]:
    terms: List[str] = []
    for source in sources:
        if isinstance(source, list):
            for value in source:
                if isinstance(value, str) and value.strip():
                    terms.append(value.strip())
    return terms


def _format_validation_error(exc: ValidationError) -> str:
    messages: List[str] = []
    for error in exc.errors():
        location = "->".join(str(component) for component in error.get("loc", []))
        if location:
            messages.append(f"{location}: {error.get('msg')}")
        else:
            messages.append(error.get("msg", "Invalid input"))
    return "; ".join(messages)

