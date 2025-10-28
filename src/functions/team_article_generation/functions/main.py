"""Team article generation service handler."""

from __future__ import annotations

import copy
import logging
import os
from typing import Any, Dict, List

from pydantic import ValidationError

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.team_article_generation.core.contracts.team_article import (
    SummaryBundle,
)
from src.functions.team_article_generation.core.llm.openai_client import (
    OpenAIGenerationClient,
)

load_env()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a structured team article from aggregated summaries."""

    summaries_input = request.get("summaries") or []
    if not isinstance(summaries_input, list) or not summaries_input:
        return {
            "status": "error",
            "message": "Request must include a non-empty 'summaries' list",
        }

    team = request.get("team") or {}
    team_abbr = (team.get("abbr") or team.get("team_abbr") or "").strip().upper()
    if not team_abbr:
        return {
            "status": "error",
            "message": "Team abbreviation is required in the 'team' block",
        }

    team_name = team.get("name")
    summary_texts: List[str] = []
    sources: List[str] = []
    for entry in summaries_input:
        if not isinstance(entry, dict):
            continue
        text = entry.get("content") or entry.get("summary")
        if text:
            summary_texts.append(str(text))
        source = entry.get("source_url") or entry.get("url")
        if source:
            sources.append(source)

    if not summary_texts:
        return {
            "status": "error",
            "message": "At least one summary with 'content' is required",
        }

    try:
        bundle = SummaryBundle(team_abbr=team_abbr, team_name=team_name, summaries=summary_texts)
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
        client = OpenAIGenerationClient(
            api_key=api_key,
            model=model_override or "gpt-5",
            logger=logger,
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    base_options = request.get("options") if isinstance(request.get("options"), dict) else {}
    merged_options = _merge_options(base_options, request.get("llm_options"))

    try:
        article = client.generate(
            bundle,
            options=merged_options if merged_options else None,
        )
    except Exception as exc:  # noqa: BLE001 - surface LLM failures for orchestration layer
        logger.warning("Article generation failed for %s: %s", team_abbr, exc)
        return {"status": "error", "message": str(exc)}

    article_payload: Dict[str, Any] = {
        "headline": article.headline,
        "sub_header": article.sub_header,
        "introduction_paragraph": article.introduction_paragraph,
        "content": article.content,
        "central_theme": article.central_theme,
        "error": article.error,
    }
    if sources:
        article_payload["sources"] = sources

    return {
        "status": "success" if not article.error else "partial",
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


def _format_validation_error(exc: ValidationError) -> str:
    messages: List[str] = []
    for error in exc.errors():
        location = "->".join(str(component) for component in error.get("loc", []))
        if location:
            messages.append(f"{location}: {error.get('msg')}")
        else:
            messages.append(error.get("msg", "Invalid input"))
    return "; ".join(messages)

