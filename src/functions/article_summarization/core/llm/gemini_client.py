"""Gemini client implementation for article summarization."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from ..contracts.summary import ArticleSummary, SummarizationOptions, SummarizationRequest, parse_options
from ..llm.rate_limiter import rate_limiter
from ..processors.summary_formatter import format_summary


class GeminiSummarizationClient:
    """Handles calls to the Gemini API with retry and formatting support."""

    def __init__(
        self,
        *,
        model: str = "gemma-3n-e4b-it",
        api_key: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._options = SummarizationOptions(model=model)
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self._api_key:
            msg = "GEMINI_API_KEY environment variable is not set"
            raise ValueError(msg)
        genai.configure(api_key=self._api_key)
        self._logger = logger or logging.getLogger(__name__)

    def summarize(
        self,
        request: SummarizationRequest,
        *,
        options: SummarizationOptions | dict | None = None,
    ) -> ArticleSummary:
        effective_options = parse_options(options or self._options.model_dump())
        try:
            raw_text = self._generate_text(request, effective_options)
        except RetryError as exc:  # pragma: no cover - retried failure
            error_msg = str(exc.last_attempt.exception()) if exc.last_attempt else str(exc)
            self._logger.error("Gemini summarization failed after retries: %s", error_msg)
            return ArticleSummary(content="", source_article_id=request.article_id, error=error_msg)
        except Exception as exc:  # pragma: no cover - unexpected failure
            self._logger.exception("Gemini summarization failed for %s", request.article_id)
            return ArticleSummary(content="", source_article_id=request.article_id, error=str(exc))

        summary = ArticleSummary(content=raw_text, source_article_id=request.article_id)
        summary = format_summary(summary, options=effective_options)
        return summary.validate_content()

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3), reraise=True)
    def _generate_text(self, request: SummarizationRequest, options: SummarizationOptions) -> str:
        prompt = self._build_prompt(request, options)
        generation_config = genai.types.GenerationConfig(
            temperature=options.temperature,
            top_p=options.top_p,
            max_output_tokens=options.max_output_tokens,
        )
        with rate_limiter():
            model = genai.GenerativeModel(model_name=options.model)
            try:
                result = model.generate_content(prompt, generation_config=generation_config)
            except GoogleAPIError as exc:
                raise RuntimeError(f"Gemini API error: {exc.message if hasattr(exc, 'message') else exc}") from exc

        text = self._extract_text(result)
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text

    def _build_prompt(self, request: SummarizationRequest, options: SummarizationOptions) -> str:
        team_clause = f"Focus on insights about the {request.team_name}." if request.team_name else "Focus only on the team mentioned in the article."
        removal_clause = ", ".join(options.remove_patterns)
        return (
            "You are an NFL beat reporter summarizing a news article for internal editors. "
            "Remove boilerplate, advertisements, video transcripts, promotional copy, and unrelated paragraphs. "
            f"{team_clause} "
            "Preserve key facts, quotes, and meaningful context without speculation. "
            "Do not add analysis or commentary. Output a concise paragraph (120-180 words). "
            f"Never include phrases related to: {removal_clause}.\n\n"
            "Article Content:\n"
            f"{request.content}"
        )

    @staticmethod
    def _extract_text(result: Any) -> str:
        if hasattr(result, "text") and result.text:
            return str(result.text)
        if getattr(result, "candidates", None):
            for candidate in result.candidates:
                parts = getattr(candidate, "content", None)
                if not parts:
                    continue
                segments = [segment.text for segment in getattr(parts, "parts", []) if getattr(segment, "text", None)]
                if segments:
                    return " ".join(segments)
        return ""
