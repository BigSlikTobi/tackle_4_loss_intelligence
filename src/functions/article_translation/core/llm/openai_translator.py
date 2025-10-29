"""OpenAI GPT-5-mini client for article translation."""

from __future__ import annotations

import json
import logging
import os
import re
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
        except RuntimeError as exc:
            # JSON parsing failures are retryable - LLM might succeed on next attempt
            self._logger.warning("JSON extraction failed (retryable): %s", exc)
            raise  # Let tenacity retry this
        except APIError as exc:
            self._logger.error("OpenAI API error (not retryable): %s", exc)
            return self._fallback_translation(request, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive branch
            self._logger.warning("Unexpected error during translation (not retryable): %s", exc)
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
        """Extract JSON payload from OpenAI response with multiple fallback strategies."""
        texts: list[str] = []
        
        # Strategy 1: Direct output_text attribute
        if hasattr(response, "output_text") and response.output_text:
            texts.append(response.output_text)
        
        # Strategy 2: Parse output array
        outputs = getattr(response, "output", [])
        for item in outputs:
            if getattr(item, "type", None) == "output_text" and getattr(item, "text", None):
                texts.append(item.text)
            if getattr(item, "type", None) == "assistant_message":
                for content in getattr(item, "content", []):
                    if getattr(content, "type", None) == "output_text" and getattr(content, "text", None):
                        texts.append(content.text)
        
        # Strategy 3: Check choices array (common in chat completions)
        if hasattr(response, "choices"):
            for choice in response.choices:
                if hasattr(choice, "message") and hasattr(choice.message, "content"):
                    texts.append(choice.message.content)
        
        # Try to parse each text as JSON
        for text in texts:
            if not text or not isinstance(text, str):
                continue
            
            # Try direct JSON parse
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and self._is_valid_translation(parsed):
                    return parsed
            except json.JSONDecodeError:
                pass
            
            # Try extracting JSON from markdown code blocks
            if "```json" in text or "```" in text:
                try:
                    # Extract content between ```json and ``` or ``` and ```
                    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1).strip()
                        parsed = json.loads(json_str)
                        if isinstance(parsed, dict) and self._is_valid_translation(parsed):
                            return parsed
                except (json.JSONDecodeError, AttributeError):
                    pass
        
        # If we have any text but couldn't parse JSON, log it for debugging
        if texts:
            self._logger.error(
                "JSON_PARSE_FAILURE: Failed to extract valid JSON from OpenAI response. "
                "Response preview (first 500 chars): %s",
                texts[0][:500] if texts[0] else "empty",
                extra={
                    "response_length": len(texts[0]) if texts else 0,
                    "response_preview": texts[0][:200] if texts else None,
                    "has_json_markers": "```json" in texts[0] if texts else False,
                }
            )
        else:
            self._logger.error(
                "JSON_PARSE_FAILURE: No text content found in OpenAI response",
                extra={"response_attributes": dir(response) if response else []}
            )
        
        raise RuntimeError("OpenAI response did not contain valid JSON payload")
    
    def _is_valid_translation(self, payload: dict[str, Any]) -> bool:
        """Check if the payload has the required translation fields."""
        required_fields = {"headline", "sub_header", "introduction_paragraph", "content"}
        has_required = all(field in payload for field in required_fields)
        has_content = bool(payload.get("content"))
        return has_required and has_content

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
