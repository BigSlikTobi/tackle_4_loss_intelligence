"""Article summarization service handler."""

from __future__ import annotations

import copy
import logging
import os
from typing import Any, Dict, List

from pydantic import ValidationError

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.article_summarization.core.contracts.summary import (
    SummarizationRequest,
)
from src.functions.article_summarization.core.llm.gemini_client import (
    GeminiSummarizationClient,
)

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Summarise each article payload with Gemini."""

    articles = request.get("articles") or []
    if not isinstance(articles, list) or not articles:
        return {
            "status": "error",
            "message": "Request must include a non-empty 'articles' list",
        }

    team = request.get("team") or {}
    team_name = team.get("name") or team.get("abbr")

    api_key = _resolve_api_key(
        request.get("llm"),
        request.get("gemini"),
        request.get("secrets"),
        request.get("auth"),
    )
    model_override = None
    for block in (request.get("llm"), request.get("gemini")):
        if isinstance(block, dict) and block.get("model"):
            model_override = block["model"]
            break

    try:
        client = GeminiSummarizationClient(
            api_key=api_key,
            model=model_override or "gemma-3n-e4b-it",
            logger=logger,
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    base_options = request.get("options") if isinstance(request.get("options"), dict) else {}
    summaries: List[Dict[str, Any]] = []

    for entry in articles:
        if not isinstance(entry, dict):
            summaries.append({
                "error": "Each item in 'articles' must be an object",
            })
            continue

        source_url = entry.get("source_url") or entry.get("url") or entry.get("id")
        article_id = entry.get("article_id") or source_url
        content = entry.get("content") or ""

        try:
            request_model = SummarizationRequest(
                article_id=article_id,
                team_name=team_name,
                content=content,
            )
        except ValidationError as exc:
            summaries.append(
                {
                    "source_url": source_url,
                    "error": _format_validation_error(exc),
                }
            )
            continue

        merged_options = _merge_options(base_options, entry.get("options"))

        try:
            summary = client.summarize(
                request_model,
                options=merged_options if merged_options else None,
            )
        except Exception as exc:  # noqa: BLE001 - surface LLM failures as structured error
            logger.warning("Summarization failed for %s: %s", source_url, exc)
            summaries.append(
                {
                    "source_url": source_url,
                    "error": str(exc),
                    "content": "",
                }
            )
            continue

        summaries.append(
            {
                "source_url": source_url,
                "content": summary.content,
                "word_count": summary.word_count,
                "error": summary.error,
            }
        )

    succeeded = sum(1 for summary in summaries if not summary.get("error"))
    return {
        "status": "success" if succeeded else "partial",
        "counts": {"total": len(summaries), "succeeded": succeeded},
        "summaries": summaries,
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


def _format_validation_error(exc: ValidationError) -> str:
    messages: List[str] = []
    for error in exc.errors():
        location = "->".join(str(component) for component in error.get("loc", []))
        if location:
            messages.append(f"{location}: {error.get('msg')}")
        else:
            messages.append(error.get("msg", "Invalid input"))
    return "; ".join(messages)

