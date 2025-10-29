"""OpenAI GPT-5-mini client for article translation."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from openai import APIError, OpenAI

from src.shared.utils.config_validator import check_config_override, ConfigurationError
from ..contracts.translated_article import (
    TranslatedArticle,
    TranslationOptions,
    TranslationRequest,
    parse_translation_options,
)
from ..processors.structure_validator import validate_structure
from ..prompts import build_translation_prompt, build_translation_system_prompt


class OpenAITranslationClient:
    """Wraps GPT-5-mini translation with JSON enforcement."""

    def __init__(
        self,
        *,
        model: str = "gpt-5-mini",
        api_key: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._options = TranslationOptions(model=model)
        try:
            self._api_key = check_config_override(
                api_key, 
                "OPENAI_API_KEY", 
                required=True
            )
        except ConfigurationError as e:
            raise ConfigurationError(
                f"{e}\nRequired for article translation. "
                "See .env.example for configuration template."
            )
        self._client = OpenAI(api_key=self._api_key)
        self._logger = logger or logging.getLogger(__name__)

    def translate(
        self,
        request: TranslationRequest,
        *,
        options: TranslationOptions | dict | None = None,
    ) -> TranslatedArticle:
        opts = parse_translation_options(options or self._options.model_dump())
        prompt = build_translation_prompt(request, opts)
        schema = self._build_schema()

        client = self._client.with_options(timeout=float(opts.request_timeout_seconds))
        request_kwargs: dict[str, Any] = {
            "model": opts.model,
            "input": [
                {"role": "system", "content": self._system_prompt(opts)},
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
        except TypeError as exc:  # pragma: no cover - fallback when SDK lacks response_format
            if "response_format" not in str(exc):
                raise
            self._logger.info(
                "Response schema unsupported by current OpenAI SDK; retrying without response_format",
            )
            response = client.responses.create(**request_kwargs)
            payload = self._extract_payload(response)
        except APIError as exc:
            self._logger.error("OpenAI translation error: %s", exc)
            return self._fallback_translation(request, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive branch
            self._logger.warning("Falling back to original language due to OpenAI failure: %s", exc)
            return self._fallback_translation(request, error=str(exc))

        raw_content = payload.get("content", [])
        if isinstance(raw_content, str):
            raw_content = [raw_content]
        article = TranslatedArticle(
            language=request.language,
            headline=payload.get("headline", ""),
            sub_header=payload.get("sub_header", ""),
            introduction_paragraph=payload.get("introduction_paragraph", ""),
            content=raw_content,
        )
        article = validate_structure(article, reference=request)
        return article

    def _system_prompt(self, options: TranslationOptions) -> str:
        return build_translation_system_prompt(options)

    @staticmethod
    def _build_schema() -> dict[str, Any]:
        return {
            "name": "translated_article",
            "schema": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "sub_header": {"type": "string"},
                    "introduction_paragraph": {"type": "string"},
                    "content": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "required": [
                    "headline",
                    "sub_header",
                    "introduction_paragraph",
                    "content",
                ],
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

    def _fallback_translation(self, request: TranslationRequest, *, error: str) -> TranslatedArticle:
        return TranslatedArticle(
            language=request.language,
            headline=request.headline,
            sub_header=request.sub_header,
            introduction_paragraph=request.introduction_paragraph,
            content=request.content,
            source_article_id=request.article_id,
            error=error,
            preserved_terms=request.preserve_terms,
        )
