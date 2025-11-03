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


@dataclass(slots=True)
class ArticleValidationReport:
    """Structured response returned by the article validation service."""

    status: str
    decision: str
    is_releasable: bool
    rejection_reasons: List[str]
    review_reasons: List[str]
    processing_time_ms: Optional[int] = None


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
        # Use None timeout at client level to allow per-request timeouts to take effect
        # connect timeout is still 5 seconds for fast failure on network issues
        timeout = httpx.Timeout(None, connect=5.0)
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

    def has_article_validation(self) -> bool:
        """Return True when article validation endpoint has been configured."""

        return self._config.article_validation is not None

    def generate_article(
        self,
        team: TeamRecord,
        summaries: Sequence[ArticleSummary],
        *,
        feedback: Optional[Sequence[str]] = None,
        previous_article: Optional[GeneratedArticle] = None,
    ) -> GeneratedArticle:
        endpoint = self._config.require("article_generation")
        
        # Load OpenAI API key for LLM article generation - strip quotes if present
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            openai_api_key = openai_api_key.strip().strip('"').strip("'")
        
        payload: Dict[str, object] = {
            "team": {
                "abbr": team.abbreviation,
                "name": team.name,
            },
            "summaries": [asdict(summary) for summary in summaries],
        }

        cleaned_feedback = [
            str(reason).strip()
            for reason in (feedback or [])
            if isinstance(reason, str) and str(reason).strip()
        ]
        if cleaned_feedback:
            formatted_feedback = "\n".join(f"- {reason}" for reason in cleaned_feedback)
            narrative_focus = (
                "Focus on the primary storyline emerging from the provided summaries while addressing the "
                "following validation feedback. Do not repeat the cited issues and ensure all facts remain accurate.\n"
                f"{formatted_feedback}"
            )
            payload["options"] = {"narrative_focus": narrative_focus}
            payload["validation_feedback"] = cleaned_feedback

        if previous_article is not None:
            payload["previous_article"] = asdict(previous_article)

        # Add LLM credentials if available
        if openai_api_key:
            payload["llm"] = {
                "api_key": openai_api_key,
                "model": "gpt-5",
            }
        
        response = self._post_json("article_generation", endpoint.url, payload, endpoint.build_headers(), endpoint.timeout_seconds)

        # Some deployments wrap upstream failures in a 200 with a status payload; surface these cleanly.
        if isinstance(response, dict):
            status = response.get("status")
            if status and status.lower() != "success":
                message = response.get("message") or "Article generation service returned an error"
                # Treat non-success status as retryable unless explicitly marked otherwise.
                raise ServiceInvocationError(
                    "article_generation",
                    message,
                    retryable=True,
                )

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
            logger.debug(
                "Article generation missing required fields for %s: payload=%s normalised_headline=%r normalised_intro=%r paragraphs=%d",
                team.abbreviation,
                article,
                generated.headline,
                generated.introduction_paragraph,
                len(generated.content),
            )
            raise ServiceInvocationError("article_generation", "Article response missing required fields")
        return generated

    def validate_article(
        self,
        *,
        team: TeamRecord,
        article: GeneratedArticle,
        summaries: Sequence[ArticleSummary],
        previous_article: Optional[GeneratedArticle] = None,
        rejection_reasons: Optional[Sequence[str]] = None,
    ) -> ArticleValidationReport:
        endpoint = self._config.article_validation
        if endpoint is None:
            raise ServiceInvocationError(
                "article_validation",
                "Article validation endpoint is not configured",
                retryable=False,
            )

        payload: Dict[str, object] = {
            "article_type": "team_article",
            "article": {
                "headline": article.headline,
                "sub_header": article.sub_header,
                "introduction_paragraph": article.introduction_paragraph,
                "content": article.content,
            },
            "team_context": {
                "team_id": team.identifier,
                "team_abbr": team.abbreviation,
                "team_name": team.name,
            },
        }

        summaries_text = [summary.content for summary in summaries if summary.content]
        if summaries_text:
            payload["source_summaries"] = summaries_text

        if previous_article is not None:
            payload["previous_article"] = {
                "headline": previous_article.headline,
                "sub_header": previous_article.sub_header,
                "introduction_paragraph": previous_article.introduction_paragraph,
                "content": previous_article.content,
            }

        cleaned_rejections = [
            str(reason).strip()
            for reason in (rejection_reasons or [])
            if isinstance(reason, str) and str(reason).strip()
        ]
        if cleaned_rejections:
            payload["validation_feedback"] = {
                "rejection_reasons": cleaned_rejections,
            }

        llm_block = self._build_validation_llm_block()
        if llm_block:
            payload["llm"] = llm_block

        response = self._post_json(
            "article_validation",
            endpoint.url,
            payload,
            endpoint.build_headers(),
            endpoint.timeout_seconds,
        )

        status = str(response.get("status") or "error").lower()
        if status == "error":
            message = response.get("error") or response.get("message") or "Article validation failed"
            raise ServiceInvocationError("article_validation", message, retryable=False)

        decision = str(response.get("decision") or "").lower()
        if decision not in {"release", "reject", "review_required"}:
            raise ServiceInvocationError(
                "article_validation",
                f"Unexpected validation decision: {decision or 'missing'}",
                retryable=False,
            )

        rejection_list = self._normalise_reason_list(response.get("rejection_reasons"))
        review_list = self._normalise_reason_list(response.get("review_reasons"))
        processing_time = response.get("processing_time_ms")
        try:
            processing_time_ms = int(processing_time) if processing_time is not None else None
        except (TypeError, ValueError):
            processing_time_ms = None

        report = ArticleValidationReport(
            status=status,
            decision=decision,
            is_releasable=bool(response.get("is_releasable")),
            rejection_reasons=rejection_list,
            review_reasons=review_list,
            processing_time_ms=processing_time_ms,
        )

        logger.info(
            "Article validation decision for %s: decision=%s status=%s rejection=%d review=%d",
            team.abbreviation,
            decision,
            status,
            len(rejection_list),
            len(review_list),
        )
        if rejection_list:
            logger.info("Validation rejection reasons for %s: %s", team.abbreviation, rejection_list)
        if review_list:
            logger.info("Validation review reasons for %s: %s", team.abbreviation, review_list)

        return report

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

    @staticmethod
    def _normalise_reason_list(raw: object) -> List[str]:
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
            return []
        reasons: List[str] = []
        for entry in raw:
            if not isinstance(entry, str):
                continue
            cleaned = entry.strip()
            if cleaned:
                reasons.append(cleaned)
        return reasons

    @staticmethod
    def _interpret_bool(value: Optional[str]) -> Optional[bool]:
        if value is None:
            return None
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return None

    def _build_validation_llm_block(self) -> Optional[Dict[str, object]]:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            api_key = api_key.strip().strip('"').strip("'")
        if not api_key:
            return None

        llm_block: Dict[str, object] = {"api_key": api_key}
        model = os.getenv("GEMINI_MODEL") or os.getenv("GOOGLE_MODEL")
        if model:
            llm_block["model"] = model.strip().strip('"').strip("'")

        enable_web_search = self._interpret_bool(os.getenv("GEMINI_ENABLE_WEB_SEARCH"))
        if enable_web_search is None:
            enable_web_search = self._interpret_bool(os.getenv("GOOGLE_ENABLE_WEB_SEARCH"))
        if enable_web_search is not None:
            llm_block["enable_web_search"] = enable_web_search

        timeout_value = os.getenv("GEMINI_TIMEOUT_SECONDS") or os.getenv("GOOGLE_TIMEOUT_SECONDS")
        if timeout_value:
            try:
                llm_block["timeout_seconds"] = int(timeout_value)
            except ValueError:
                logger.warning(
                    "Invalid validation timeout configured: %s", timeout_value
                )
        return llm_block
