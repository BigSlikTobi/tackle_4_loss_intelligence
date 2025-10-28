"""OpenAI GPT-5 client for team article generation."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from openai import APIError, OpenAI

from src.shared.utils.config_validator import check_config_override, ConfigurationError
from ..contracts.team_article import GeneratedArticle, GenerationOptions, SummaryBundle, parse_generation_options
from ..llm.prompt_builder import build_prompt
from ..processors.article_validator import validate_article
from ..processors.narrative_analyzer import find_central_narrative


class OpenAIGenerationClient:
    """Wraps GPT-5 interactions with JSON schema enforcement."""

    def __init__(
        self,
        *,
        model: str = "gpt-5",
        api_key: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._options = GenerationOptions(model=model)
        try:
            self._api_key = check_config_override(
                api_key, 
                "OPENAI_API_KEY", 
                required=True
            )
        except ConfigurationError as e:
            raise ConfigurationError(
                f"{e}\nRequired for team article generation. "
                "See .env.example for configuration template."
            )
        self._client = OpenAI(api_key=self._api_key)
        self._logger = logger or logging.getLogger(__name__)

    def generate(
        self,
        bundle: SummaryBundle,
        *,
        options: GenerationOptions | dict | None = None,
    ) -> GeneratedArticle:
        opts = parse_generation_options(options or self._options.model_dump())
        prompt = build_prompt(bundle, opts)
        schema = self._build_schema()
        client = self._client.with_options(timeout=float(opts.request_timeout_seconds))
        request_kwargs = {
            "model": opts.model,
            "input": [
                {"role": "system", "content": self._system_prompt(bundle)},
                {"role": "user", "content": prompt},
            ],
            "service_tier": opts.service_tier,
        }
        if opts.temperature is not None:
            request_kwargs["temperature"] = opts.temperature
        if opts.max_output_tokens is not None:
            request_kwargs["max_output_tokens"] = opts.max_output_tokens
        try:
            response = client.responses.create(
                **request_kwargs,
                response_format={"type": "json_schema", "json_schema": schema},
            )
            payload = self._extract_payload(response)
        except TypeError as exc:  # pragma: no cover - older SDK versions
            if "response_format" not in str(exc):
                raise
            self._logger.info(
                "OpenAI client does not support response_format json schema; retrying without schema enforcement",
            )
            response = client.responses.create(**request_kwargs)
            payload = self._extract_payload(response)
        except APIError as exc:
            self._logger.error("OpenAI API error: %s", exc)
            return GeneratedArticle(
                headline="",
                sub_header="",
                introduction_paragraph="",
                content=[],
                error=str(exc),
            )
        except Exception as exc:  # pragma: no cover - fallback for offline usage
            self._logger.warning("Falling back to heuristic article due to OpenAI failure: %s", exc)
            payload = self._fallback_article(bundle)

        article = GeneratedArticle(**payload, central_theme=find_central_narrative(bundle))
        return validate_article(article, bundle=bundle)

    def _system_prompt(self, bundle: SummaryBundle) -> str:
        team_label = bundle.team_name or bundle.team_abbr
        return (
            "You are an experienced NFL beat writer crafting a daily update article. "
            "Use only the provided summaries, avoid speculation, and ensure the piece reads like a cohesive story. "
            f"Write in third person about the {team_label}."
        )

    @staticmethod
    def _build_schema() -> dict[str, Any]:
        return {
            "name": "team_article",
            "schema": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "sub_header": {"type": "string"},
                    "introduction_paragraph": {"type": "string"},
                    "content": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                    },
                },
                "required": ["headline", "sub_header", "introduction_paragraph", "content"],
                "additionalProperties": False,
            },
        }

    def _extract_payload(self, response: Any) -> dict[str, Any]:
        texts: list[str] = []
        if hasattr(response, "output_text") and response.output_text:
            texts.append(response.output_text)
        outputs = getattr(response, "output", [])
        for item in outputs:
            if getattr(item, "type", None) == "output_text" and getattr(item, "text", None):
                texts.append(item.text)
            if getattr(item, "type", None) == "assistant_message":
                for content in getattr(item, "content", []):
                    if getattr(content, "type", None) == "output_text" and getattr(content, "text", None):
                        texts.append(content.text)
        for text in texts:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        raise RuntimeError("OpenAI response did not contain JSON payload")

    def _fallback_article(self, bundle: SummaryBundle) -> dict[str, Any]:
        abbr = bundle.team_abbr.upper() if bundle.team_abbr else "TEAM"
        headline = f"{abbr} daily roundup"
        intro = bundle.summaries[0]
        remaining = bundle.summaries[1:]
        return {
            "headline": headline,
            "sub_header": "Key storylines from recent coverage",
            "introduction_paragraph": intro,
            "content": remaining or [intro],
        }
