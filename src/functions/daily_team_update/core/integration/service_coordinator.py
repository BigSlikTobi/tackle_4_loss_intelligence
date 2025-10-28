"""Service coordination utilities for the daily team update pipeline."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from ..contracts.config import PipelineConfig, ServiceCoordinatorConfig
from ..contracts.pipeline_result import FailureDetail
from ..db.team_reader import TeamRecord

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractedArticle:
    """Represents content extracted from a news URL."""

    url: str
    title: Optional[str]
    content: str
    author: Optional[str]
    published_at: Optional[str]


@dataclass(slots=True)
class ArticleSummary:
    """Summarised content for a single article."""

    source_url: str
    content: str


@dataclass(slots=True)
class GeneratedArticle:
    """Structured article generated for a team."""

    headline: str
    sub_header: str
    introduction_paragraph: str
    content: List[str]
    central_theme: Optional[str] = None


@dataclass(slots=True)
class TranslatedArticle:
    """Translated article maintaining the same structure as the original."""

    headline: str
    sub_header: str
    introduction_paragraph: str
    content: List[str]
    language: str


@dataclass(slots=True)
class SelectedImage:
    """Image metadata returned by the image selection service."""

    image_url: str
    original_url: Optional[str]
    title: Optional[str]
    source: Optional[str]
    author: Optional[str]
    width: Optional[int]
    height: Optional[int]
    id: Optional[str] = None


class ServiceInvocationError(RuntimeError):
    """Raised when a downstream service call fails fatally."""

    def __init__(self, stage: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.stage = stage
        self.retryable = retryable


class ServiceCoordinator:
    """Encapsulates outbound calls to the various functional services."""

    def __init__(
        self,
        config: ServiceCoordinatorConfig,
        pipeline_config: PipelineConfig,
        *,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._config = config
        self._pipeline_config = pipeline_config
        timeout = httpx.Timeout(pipeline_config.summarization_batch_size * 30, connect=5.0)
        self._http = http_client or httpx.Client(timeout=timeout)
        self._image_selection_defaults = self._prepare_image_selection_defaults()

    def extract_content(
        self,
        team: TeamRecord,
        urls: Sequence[Dict[str, object]],
    ) -> Tuple[List[ExtractedArticle], List[FailureDetail]]:
        endpoint = self._config.require("content_extraction")
        payload = {
            "team": {
                "abbr": team.abbreviation,
                "name": team.name,
                "conference": team.conference,
                "division": team.division,
            },
            "urls": urls,
        }
        response = self._post_json("content_extraction", endpoint.url, payload, endpoint.build_headers(), endpoint.timeout_seconds)
        articles: List[ExtractedArticle] = []
        failures: List[FailureDetail] = []
        for item in response.get("articles", []):
            error = item.get("error") if isinstance(item, dict) else None
            if error:
                failures.append(
                    FailureDetail(
                        stage="content_extraction",
                        message=str(error),
                        retryable=False,
                        raw={"url": item.get("url")},
                    )
                )
                continue
            url = item.get("url") if isinstance(item, dict) else None
            content = item.get("content") if isinstance(item, dict) else None
            if not url or not content:
                continue
            articles.append(
                ExtractedArticle(
                    url=url,
                    title=item.get("title"),
                    content=content,
                    author=item.get("author"),
                    published_at=item.get("published_at") or item.get("publishedAt"),
                )
            )
        return articles, failures

    def summarise_articles(
        self,
        team: TeamRecord,
        articles: Sequence[ExtractedArticle],
    ) -> Tuple[List[ArticleSummary], List[FailureDetail]]:
        endpoint = self._config.require("summarization")
        
        # Load Gemini API key for LLM summarization - strip quotes if present
        llm_api_key = os.getenv("GEMINI_API_KEY")
        if llm_api_key:
            llm_api_key = llm_api_key.strip().strip('"').strip("'")
        
        payload = {
            "team": {
                "abbr": team.abbreviation,
                "name": team.name,
            },
            "articles": [
                {"source_url": article.url, "content": article.content, "title": article.title, "author": article.author, "published_at": article.published_at}
                for article in articles
            ],
            "batch_size": self._pipeline_config.summarization_batch_size,
        }
        
        # Add LLM credentials if available
        if llm_api_key:
            payload["llm"] = {
                "api_key": llm_api_key,
                "model": "gemma-3n-e4b-it",
            }
        
        response = self._post_json("summarization", endpoint.url, payload, endpoint.build_headers(), endpoint.timeout_seconds)
        summaries: List[ArticleSummary] = []
        failures: List[FailureDetail] = []
        for item in response.get("summaries", []):
            if isinstance(item, dict) and item.get("error"):
                failures.append(
                    FailureDetail(
                        stage="summarization",
                        message=str(item.get("error")),
                        retryable=False,
                        raw={"url": item.get("source_url")},
                    )
                )
                continue
            source_url = item.get("source_url") if isinstance(item, dict) else None
            content = item.get("content") if isinstance(item, dict) else None
            if not source_url or not content:
                continue
            summaries.append(ArticleSummary(source_url=source_url, content=content))
        return summaries, failures

    def generate_article(
        self,
        team: TeamRecord,
        summaries: Sequence[ArticleSummary],
    ) -> GeneratedArticle:
        endpoint = self._config.require("article_generation")
        
        # Load OpenAI API key for LLM article generation - strip quotes if present
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            openai_api_key = openai_api_key.strip().strip('"').strip("'")
        
        payload = {
            "team": {
                "abbr": team.abbreviation,
                "name": team.name,
            },
            "summaries": [asdict(summary) for summary in summaries],
        }
        
        # Add LLM credentials if available
        if openai_api_key:
            payload["llm"] = {
                "api_key": openai_api_key,
                "model": "gpt-5",
            }
        
        response = self._post_json("article_generation", endpoint.url, payload, endpoint.build_headers(), endpoint.timeout_seconds)
        article = response.get("article") or response
        if not isinstance(article, dict):
            raise ServiceInvocationError("article_generation", "Invalid article payload returned")
        try:
            content = article.get("content")
            paragraphs = content if isinstance(content, list) else [content]
            paragraphs = [paragraph for paragraph in paragraphs if isinstance(paragraph, str) and paragraph.strip()]
            generated = GeneratedArticle(
                headline=article.get("headline") or "",
                sub_header=article.get("sub_header") or article.get("subHeader") or "",
                introduction_paragraph=article.get("introduction_paragraph")
                or article.get("introductionParagraph")
                or "",
                content=paragraphs,
                central_theme=article.get("central_theme") or article.get("centralTheme"),
            )
        except Exception as exc:  # noqa: BLE001
            raise ServiceInvocationError("article_generation", f"Malformed article response: {exc}") from exc
        if not generated.headline or not generated.introduction_paragraph or not generated.content:
            raise ServiceInvocationError("article_generation", "Article response missing required fields")
        return generated

    def translate_article(self, article: GeneratedArticle) -> TranslatedArticle:
        endpoint = self._config.require("translation")
        
        # Load OpenAI API key for LLM translation - strip quotes if present
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            openai_api_key = openai_api_key.strip().strip('"').strip("'")
        
        payload = {
            "article": {
                "headline": article.headline,
                "sub_header": article.sub_header,
                "introduction_paragraph": article.introduction_paragraph,
                "content": article.content,
            },
            "target_language": self._pipeline_config.target_language,
        }
        
        # Add LLM credentials if available
        if openai_api_key:
            payload["llm"] = {
                "api_key": openai_api_key,
                "model": "gpt-5-mini",  # Translation uses gpt-5-mini
            }
        
        response = self._post_json("translation", endpoint.url, payload, endpoint.build_headers(), endpoint.timeout_seconds)
        translated = response.get("article") or response
        if not isinstance(translated, dict):
            raise ServiceInvocationError("translation", "Invalid translation payload")
        content = translated.get("content")
        paragraphs = content if isinstance(content, list) else [content]
        paragraphs = [paragraph for paragraph in paragraphs if isinstance(paragraph, str) and paragraph.strip()]
        if not paragraphs:
            raise ServiceInvocationError("translation", "Translated article missing content")
        return TranslatedArticle(
            headline=translated.get("headline") or "",
            sub_header=translated.get("sub_header") or translated.get("subHeader") or "",
            introduction_paragraph=translated.get("introduction_paragraph")
            or translated.get("introductionParagraph")
            or "",
            content=paragraphs,
            language=translated.get("language") or self._pipeline_config.target_language,
        )

    def select_images(
        self,
        *,
        article: GeneratedArticle,
        translated: Optional[TranslatedArticle],
    ) -> List[SelectedImage]:
        endpoint = self._config.require("image_selection")
        article_text = "\n".join([article.headline, article.sub_header, article.introduction_paragraph, *article.content])
        payload = {
            "article_text": article_text,
            "num_images": self._pipeline_config.image_count,
        }
        if translated:
            payload["translated_text"] = "\n".join(
                [
                    translated.headline,
                    translated.sub_header,
                    translated.introduction_paragraph,
                    *translated.content,
                ]
            )
        defaults = self._image_selection_defaults
        payload["enable_llm"] = defaults.get("enable_llm", False)
        for block_key in ("llm", "search", "supabase"):
            if defaults.get(block_key):
                payload[block_key] = defaults[block_key]
        response = self._post_json("image_selection", endpoint.url, payload, endpoint.build_headers(), endpoint.timeout_seconds)
        images: List[SelectedImage] = []
        for item in response.get("images", []):
            if not isinstance(item, dict):
                continue
            images.append(
                SelectedImage(
                    image_url=item.get("image_url") or item.get("public_url") or "",
                    original_url=item.get("original_url"),
                    title=item.get("title"),
                    source=item.get("source"),
                    author=item.get("author"),
                    width=item.get("width"),
                    height=item.get("height"),
                    id=(
                        item.get("id")
                        or item.get("record_id")
                        or item.get("image_id")
                    ),
                )
            )
        return [image for image in images if image.image_url]

    def close(self) -> None:
        self._http.close()

    def _post_json(
        self,
        stage: str,
        url: str,
        payload: Dict[str, object],
        headers: Dict[str, str],
        timeout: int,
    ) -> Dict[str, object]:
        resolved_url = str(url)
        try:
            response = self._http.post(resolved_url, headers=headers, json=payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise ServiceInvocationError(stage, f"Request to {resolved_url} timed out", retryable=True) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network runtime
            raise ServiceInvocationError(stage, f"HTTP error calling {resolved_url}: {exc}", retryable=True) from exc
        if response.status_code >= 400:
            raise ServiceInvocationError(stage, f"{resolved_url} returned status {response.status_code}: {response.text}")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ServiceInvocationError(stage, f"Invalid JSON response from {url}") from exc
        if isinstance(data, dict):
            return data
        raise ServiceInvocationError(stage, "Unexpected response payload type")

    def _prepare_image_selection_defaults(self) -> Dict[str, object]:
        # Load credentials and strip quotes if present
        llm_api_key = os.getenv("GEMINI_API_KEY")
        if llm_api_key:
            llm_api_key = llm_api_key.strip().strip('"').strip("'")
            
        search_api_key = os.getenv("Custom_Search_API_KEY")
        if search_api_key:
            search_api_key = search_api_key.strip().strip('"').strip("'")
            
        search_engine_id = os.getenv("GOOGLE_CUSTOM_SEARCH_ID")
        if search_engine_id:
            search_engine_id = search_engine_id.strip().strip('"').strip("'")
            
        supabase_url = os.getenv("SUPABASE_URL")
        if supabase_url:
            supabase_url = supabase_url.strip().strip('"').strip("'")
            
        supabase_key = os.getenv("SUPABASE_KEY")
        if supabase_key:
            supabase_key = supabase_key.strip().strip('"').strip("'")

        defaults: Dict[str, object] = {
            "enable_llm": bool(llm_api_key),
        }

        if llm_api_key:
            defaults["llm"] = {
                "provider": "gemini",
                "model": "gemma-3n-e4b-it",
                "api_key": llm_api_key,
                "parameters": {"temperature": 0.4},
                "max_query_words": 10,
            }

        if search_api_key and search_engine_id:
            defaults["search"] = {
                "api_key": search_api_key,
                "engine_id": search_engine_id,
                "rights": "cc_publicdomain,cc_attribute,cc_sharealike",
                "image_type": "photo",
                "image_size": "large",
            }

        if supabase_url and supabase_key:
            defaults["supabase"] = {
                "url": supabase_url,
                "key": supabase_key,
                "bucket": "images",
                "table": "article_images",
            }

        return defaults
