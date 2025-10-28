"""Article translation service handler."""

from __future__ import annotations

import copy
import logging
import os
from typing import Any, Dict, List

from pydantic import ValidationError

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

    try:
        translated = client.translate(
            request_model,
            options=merged_options if merged_options else None,
        )
    except Exception as exc:  # noqa: BLE001 - expose translation failures to caller
        logger.warning(
            "Translation failed for article %s: %s",
            request_model.article_id or "<unknown>",
            exc,
        )
        return {"status": "error", "message": str(exc)}

    if not translated.content:
        logger.info(
            "Translation returned empty content for %s; using source text instead",
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

    return {
        "status": "success" if not translated.error else "partial",
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

