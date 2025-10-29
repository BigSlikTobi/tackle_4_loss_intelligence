"""Per-team orchestration logic for the daily team update pipeline."""

from __future__ import annotations

from dataclasses import asdict
import logging
import time
from typing import List, Sequence

from ..contracts.config import PipelineConfig
from ..contracts.pipeline_result import FailureDetail, TeamProcessingResult
from ..db.article_writer import ArticleWriter
from ..db.relationship_manager import RelationshipManager
from ..db.team_reader import TeamRecord
from ..integration.service_coordinator import (
    ArticleSummary,
    GeneratedArticle,
    SelectedImage,
    ServiceCoordinator,
    ServiceInvocationError,
    TranslatedArticle,
)
from ..integration.supabase_client import SupabaseClient
from ..monitoring.error_handler import ErrorHandler
from ..monitoring.metrics_collector import MetricsCollector

logger = logging.getLogger(__name__)

RECORDED_FLAG = "_daily_team_update_recorded"


class TeamProcessor:
    """Coordinates all stages for a single team."""

    def __init__(
        self,
        *,
        supabase: SupabaseClient,
        service_coordinator: ServiceCoordinator,
        pipeline_config: PipelineConfig,
        metrics: MetricsCollector,
        error_handler: ErrorHandler,
    ) -> None:
        self._supabase = supabase
        self._service = service_coordinator
        self._config = pipeline_config
        self._metrics = metrics
        self._errors = error_handler
        self._writer = ArticleWriter(supabase, dry_run=pipeline_config.dry_run)
        self._relationships = RelationshipManager(supabase, dry_run=pipeline_config.dry_run)

    def process(self, team: TeamRecord, cached_result: TeamProcessingResult | None = None) -> TeamProcessingResult:
        """Run the pipeline for a single team and return the structured result.
        
        Args:
            team: The team to process
            cached_result: Optional cached result from previous attempt with intermediate data
        """

        is_retry = cached_result is not None and cached_result.retry_count > 0
        logger.info(
            "Processing team %s%s",
            team.abbreviation,
            f" (retry attempt {cached_result.retry_count + 1})" if is_retry else ""
        )
        
        result = cached_result or TeamProcessingResult(
            team_id=team.identifier,
            team_abbr=team.abbreviation,
            team_name=team.name,
        )
        
        if is_retry:
            result.retry_count += 1
        
        start_time = time.perf_counter()

        try:
            # Stage 1: URL Fetch (use cache if available)
            if result.cached_urls:
                logger.info("Using cached URLs for %s (%d URLs)", team.abbreviation, len(result.cached_urls))
                urls = result.cached_urls
            else:
                stage_start = time.perf_counter()
                try:
                    urls = self._fetch_team_urls(team)
                    result.cached_urls = urls  # Cache for potential retry
                except Exception as exc:  # noqa: BLE001
                    result.add_stage_duration("url_fetch", time.perf_counter() - stage_start)
                    logger.error("Failed fetching URLs for %s: %s", team.abbreviation, exc)
                    self._errors.record(team.abbreviation, "url_fetch", exc, retryable=True)
                    result.add_error(
                        FailureDetail(
                            stage="url_fetch",
                            message=str(exc),
                            retryable=True,
                        )
                    )
                    result.status = "failed"
                    setattr(exc, RECORDED_FLAG, True)
                    if not self._config.continue_on_error:
                        raise
                    return result
                else:
                    result.add_stage_duration("url_fetch", time.perf_counter() - stage_start)
                    
            result.urls_processed = len(urls)
            if not urls:
                result.status = "success" if self._config.allow_empty_urls else "no_news"
                return result

            # Stage 2: Content Extraction (use cache if available)
            if result.cached_extracted:
                logger.info("Using cached extracted content for %s (%d articles)", team.abbreviation, len(result.cached_extracted))
                extracted = result.cached_extracted
                extraction_failures = []
            else:
                stage_start = time.perf_counter()
                try:
                    extracted, extraction_failures = self._service.extract_content(team, urls)
                    # Cache extracted content for retry
                    result.cached_extracted = [
                        {
                            "url": art.url,
                            "title": art.title,
                            "content": art.content,
                            "author": art.author,
                            "published_at": art.published_at,
                        }
                        for art in extracted
                    ]
                finally:
                    result.add_stage_duration("content_extraction", time.perf_counter() - stage_start)
                for failure in extraction_failures:
                    result.add_error(failure)
                if not extracted:
                    result.status = "failed"
                    result.add_error(
                        FailureDetail(
                            stage="content_extraction",
                            message="No content could be extracted for any URL",
                            retryable=False,
                        )
                    )
                    return result

            # Stage 3: Summarization (use cache if available)
            if result.cached_summaries:
                logger.info("Using cached summaries for %s (%d summaries)", team.abbreviation, len(result.cached_summaries))
                summaries = [
                    ArticleSummary(source_url=s["source_url"], content=s["content"])
                    for s in result.cached_summaries
                ]
                summarisation_failures = []
            else:
                stage_start = time.perf_counter()
                try:
                    # Reconstruct extracted articles from cache
                    from ..integration.service_coordinator import ExtractedArticle
                    extracted_articles = [
                        ExtractedArticle(
                            url=art["url"],
                            title=art.get("title"),
                            content=art["content"],
                            author=art.get("author"),
                            published_at=art.get("published_at"),
                        )
                        for art in result.cached_extracted
                    ]
                    summaries, summarisation_failures = self._service.summarise_articles(team, extracted_articles)
                    # Cache summaries for retry
                    result.cached_summaries = [
                        {"source_url": s.source_url, "content": s.content}
                        for s in summaries
                    ]
                finally:
                    result.add_stage_duration("summarization", time.perf_counter() - stage_start)
                for failure in summarisation_failures:
                    result.add_error(failure)
                if not summaries:
                    result.status = "failed"
                    result.add_error(
                        FailureDetail(
                            stage="summarization",
                            message="Summarisation service returned no usable summaries",
                            retryable=False,
                        )
                    )
                    return result

            result.summaries_generated = len(summaries)

            # Stage 4: Article Generation - MUST succeed
            stage_start = time.perf_counter()
            try:
                article = self._service.generate_article(team, summaries)
            except ServiceInvocationError as exc:
                result.add_stage_duration("article_generation", time.perf_counter() - stage_start)
                logger.error("Article generation failed for %s: %s", team.abbreviation, exc)
                self._errors.record(team.abbreviation, exc.stage, exc, retryable=exc.retryable)
                result.add_error(FailureDetail(stage=exc.stage, message=str(exc), retryable=exc.retryable))
                result.mark_incomplete("No article generated")
                return result
            finally:
                result.add_stage_duration("article_generation", time.perf_counter() - stage_start)
            
            # Stage 5: Translation - MUST succeed  
            translated = None
            stage_start = time.perf_counter()
            try:
                translated = self._service.translate_article(article)
            except ServiceInvocationError as exc:
                result.add_stage_duration("translation", time.perf_counter() - stage_start)
                logger.error("Translation failed for %s: %s", team.abbreviation, exc)
                self._errors.record(team.abbreviation, exc.stage, exc, retryable=exc.retryable)
                result.add_error(FailureDetail(stage=exc.stage, message=str(exc), retryable=exc.retryable))
                result.mark_incomplete("No translation generated")
                return result
            else:
                result.add_stage_duration("translation", time.perf_counter() - stage_start)

            # Stage 6: Image Selection - MUST succeed
            images: List[SelectedImage] = []
            if self._config.image_count > 0:
                stage_start = time.perf_counter()
                try:
                    images = self._service.select_images(article=article, translated=translated)
                    if not images:
                        raise ServiceInvocationError(
                            "image_selection",
                            f"No images returned (requested {self._config.image_count})",
                            retryable=True
                        )
                except ServiceInvocationError as exc:
                    result.add_stage_duration("image_selection", time.perf_counter() - stage_start)
                    logger.error("Image selection failed for %s: %s", team.abbreviation, exc)
                    self._errors.record(team.abbreviation, exc.stage, exc, retryable=exc.retryable)
                    result.add_error(FailureDetail(stage=exc.stage, message=str(exc), retryable=exc.retryable))
                    result.mark_incomplete("No images selected")
                    return result
                else:
                    result.add_stage_duration("image_selection", time.perf_counter() - stage_start)

            # Stage 7: Persistence
            stage_start = time.perf_counter()
            try:
                article_records = self._persist_outputs(
                    team=team,
                    article=article,
                    translated=translated,
                    summaries=summaries,
                    images=images,
                    source_urls=[
                        entry.get("url") if isinstance(entry, dict) else entry
                        for entry in urls
                        if (entry.get("url") if isinstance(entry, dict) else entry)
                    ],
                )
            finally:
                result.add_stage_duration("persistence", time.perf_counter() - stage_start)
            
            result.mark_success(
                summaries=len(summaries),
                images=len(images),
                article_ids=article_records,
            )
            result.article_generated = True
            result.translation_generated = result.translation_generated or bool(article_records.get("de"))
            
            # Final validation: Ensure we have everything
            if not result.is_complete():
                missing = []
                if not result.article_generated:
                    missing.append("article")
                if not result.translation_generated:
                    missing.append("translation")
                if result.images_selected == 0:
                    missing.append("images")
                    
                reason = f"Missing: {', '.join(missing)}"
                logger.warning("Team %s marked incomplete: %s", team.abbreviation, reason)
                result.mark_incomplete(reason)
                return result
                
        except ServiceInvocationError as exc:
            if getattr(exc, RECORDED_FLAG, False):
                if not self._config.continue_on_error:
                    raise
            else:
                logger.error("Pipeline stage failed for %s: %s", team.abbreviation, exc)
                self._errors.record(team.abbreviation, exc.stage, exc, retryable=exc.retryable)
                result.add_error(
                    FailureDetail(stage=exc.stage, message=str(exc), retryable=exc.retryable)
                )
                if not self._config.continue_on_error:
                    raise
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, RECORDED_FLAG, False):
                if not self._config.continue_on_error:
                    raise
            else:
                logger.exception("Unhandled error while processing %s", team.abbreviation)
                self._errors.record(team.abbreviation, "pipeline", exc)
                result.add_error(
                    FailureDetail(stage="pipeline", message=str(exc), retryable=False)
                )
                if not self._config.continue_on_error:
                    raise
        finally:
            total_duration = time.perf_counter() - start_time
            result.add_stage_duration("team_total", total_duration)
            self._finalise(team, result)
        return result

    def _fetch_team_urls(self, team: TeamRecord) -> List[dict]:
        urls = self._supabase.fetch_team_news_urls(team.abbreviation)
        if self._config.max_urls_per_team and len(urls) > self._config.max_urls_per_team:
            urls = list(urls)[: self._config.max_urls_per_team]
        return list(urls)

    def _persist_outputs(
        self,
        *,
        team: TeamRecord,
        article: GeneratedArticle,
        translated: TranslatedArticle | None,
        summaries: Sequence[ArticleSummary],
        images: Sequence[SelectedImage],
        source_urls: Sequence[str],
    ) -> dict:
        if self._config.dry_run:
            return {"en": "dry-run", "de": "dry-run" if translated else None}

        article_record = self._writer.persist_article(
            team=team,
            language="en",
            article={
                "headline": article.headline,
                "sub_header": article.sub_header,
                "introduction_paragraph": article.introduction_paragraph,
                "content": article.content,
            },
            source_urls=source_urls,
            metadata={
                "central_theme": article.central_theme,
                "summary_urls": [summary.source_url for summary in summaries],
            },
        )
        article_id_en = article_record.get("id") if isinstance(article_record, dict) else None

        article_id_de = None
        if translated is not None:
            translation_record = self._writer.persist_article(
                team=team,
                language=translated.language,
                article={
                    "headline": translated.headline,
                    "sub_header": translated.sub_header,
                    "introduction_paragraph": translated.introduction_paragraph,
                    "content": translated.content,
                },
                source_urls=source_urls,
                metadata={"original_language": "en"},
            )
            article_id_de = translation_record.get("id") if isinstance(translation_record, dict) else None

        if article_id_en and images:
            self._relationships.link_articles_to_images(
                english_article_id=article_id_en,
                translated_article_id=article_id_de,
                image_records=[asdict(image) for image in images],
            )

        return {"en": article_id_en, "de": article_id_de}

    def _finalise(self, team: TeamRecord, result: TeamProcessingResult) -> None:
        self._metrics.record_team(result)
        logger.info(
            "Completed team %s with status %s (urls=%s, summaries=%s)",
            team.abbreviation,
            result.status,
            result.urls_processed,
            result.summaries_generated,
        )
