"""LLM helpers for optimizing image search queries."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from .config import LLMConfig
from .prompts import (
    IMAGE_QUERY_PROMPT_TEMPLATE,
    IMAGE_QUERY_SYSTEM_PROMPT,
    build_image_query_prompt,
)

logger = logging.getLogger(__name__)

class LLMClient:
    """Base class for provider specific LLM clients."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        if not self.config.prompt_template:
            self.config.prompt_template = IMAGE_QUERY_PROMPT_TEMPLATE

    def _build_prompt(self, article_text: str) -> str:
        return build_image_query_prompt(
            article_text,
            max_words=self.config.max_query_words,
            template=self.config.prompt_template,
        )

    async def generate_query(self, article_text: str) -> str:
        raise NotImplementedError

    def _post_process(self, response_text: str) -> str:
        text = response_text.strip()
        if ":" in text:
            label, candidate = text.split(":", 1)
            if any(tag in label.lower() for tag in ("search query", "query")):
                text = candidate.strip()
        text = text.replace("`", "").replace("\n", " ")
        words = text.split()
        if self.config.max_query_words > 0 and len(words) > self.config.max_query_words:
            text = " ".join(words[: self.config.max_query_words])
        return text


class GeminiLLMClient(LLMClient):
    """Gemini implementation."""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        try:
            import google.generativeai as genai
        except ImportError as exc:  # pragma: no cover - import guard
            raise ImportError(
                "google-generativeai must be installed to use Gemini provider"
            ) from exc

        genai.configure(api_key=config.api_key)
        self._model = genai.GenerativeModel(config.model)

    async def generate_query(self, article_text: str) -> str:
        prompt = self._build_prompt(article_text)
        parameters = self._build_generation_config(self.config.parameters)

        def _generate() -> str:
            response = self._model.generate_content(
                prompt,
                generation_config=parameters or None,
            )
            result_text = getattr(response, "text", None)
            if not result_text and getattr(response, "candidates", None):
                parts = [
                    part.text
                    for candidate in response.candidates
                    for part in getattr(candidate, "content", {}).parts
                    if hasattr(part, "text")
                ]
                result_text = " ".join(parts)
            if not result_text:
                raise RuntimeError("LLM returned empty response")
            return result_text

        response_text = await asyncio.to_thread(_generate)
        return self._post_process(response_text)

    @staticmethod
    def _build_generation_config(params: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"temperature", "top_p", "top_k", "max_output_tokens"}
        generation_config = {
            key: value for key, value in params.items() if key in allowed
        }
        return generation_config


class OpenAILLMClient(LLMClient):
    """OpenAI implementation for GPT style models."""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - import guard
            raise ImportError("openai must be installed to use OpenAI provider") from exc

        self._client = OpenAI(api_key=config.api_key)

    async def generate_query(self, article_text: str) -> str:
        prompt = self._build_prompt(article_text)
        params = self._filter_parameters(self.config.parameters, self.config.model)

        def _generate() -> str:
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {
                        "role": "system",
                        "content": IMAGE_QUERY_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                **params,
            )
            choice = response.choices[0]
            content = choice.message.content if choice.message else ""
            if not content:
                raise RuntimeError("LLM returned empty response")
            return content

        response_text = await asyncio.to_thread(_generate)
        return self._post_process(response_text)

    @staticmethod
    def _filter_parameters(parameters: Dict[str, Any], model: str) -> Dict[str, Any]:
        allowed = {
            "temperature",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "max_tokens",
            "seed",
        }
        filtered = {k: v for k, v in parameters.items() if k in allowed}

        # Some newer GPT-5 style models do not expose temperature; drop it when requested
        if model.lower().startswith("gpt-5") and "temperature" in filtered:
            logger.info("Removing unsupported temperature parameter for %s", model)
            filtered.pop("temperature")

        # Set sensible defaults for GPT-4.1 to get precise, deterministic outputs
        if model.lower().startswith("gpt-4.1") or model.lower() == "gpt-4.1":
            if "temperature" not in filtered:
                filtered["temperature"] = 0.3  # Low temperature for more focused queries
            if "max_tokens" not in filtered:
                filtered["max_tokens"] = 50  # Short output for search queries

        return filtered


def create_llm_client(config: LLMConfig) -> LLMClient:
    """Factory for provider specific LLM clients."""

    provider = config.provider.lower()
    if provider in {"gemini", "google", "google-genai"}:
        return GeminiLLMClient(config)
    if provider in {"openai", "gpt"}:
        return OpenAILLMClient(config)

    raise ValueError(f"Unsupported LLM provider: {config.provider}")
