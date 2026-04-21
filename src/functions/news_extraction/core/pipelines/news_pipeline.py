"""
News extraction pipeline.

Orchestrates the complete flow: load config → extract → process → transform → write.
Optimized for production with concurrent processing and comprehensive monitoring.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

from ..config import load_feed_config, FeedConfig
from ..contracts import NewsItem
from ..extractors import get_extractor
from ..processors import UrlProcessor
from ..data.transformers import NewsTransformer
from ..db import NewsUrlWriter
from ..db.watermarks import NewsSourceWatermarkStore
from ..utils import HttpClient
from ..utils.dates import ensure_utc
from ..monitoring import PerformanceMonitor

logger = logging.getLogger(__name__)


class NewsExtractionPipeline:
    """
    Production-ready pipeline for extracting news URLs.

    Orchestrates the entire extraction workflow from source configuration
    to database storage with concurrent processing and comprehensive monitoring.
    """

    def __init__(
        self,
        config: Optional[FeedConfig] = None,
        config_path: Optional[str] = None,
        writer: Optional[NewsUrlWriter] = None,
        watermark_store: Optional[NewsSourceWatermarkStore] = None,
        http_client: Optional[HttpClient] = None,
        max_workers: Optional[int] = None,
    ):
        """
        Initialize extraction pipeline.

        Args:
            config: Pre-loaded FeedConfig (optional)
            config_path: Path to feeds.yaml (used if config not provided)
            writer: Optional NewsUrlWriter (for testing, dry-run, or request-
                scoped credentials)
            watermark_store: Optional NewsSourceWatermarkStore (for testing or
                request-scoped credentials)
            http_client: Optional pre-built HttpClient. When omitted, one is
                constructed from the config and shared across all sources — this
                gives cross-source connection pooling, cache reuse, and correct
                rate-limit behavior for sources that share a host.
            max_workers: Override for the config's max_workers setting.
        """
        self.config = config or load_feed_config(config_path)
        self.transformer = NewsTransformer()
        self.writer = writer  # Lazily initialized on first real write.
        self.watermarks = watermark_store or NewsSourceWatermarkStore()

        resolved_workers = max_workers if max_workers is not None else getattr(
            self.config, "max_workers", 4
        )
        self.max_workers = resolved_workers

        self._owns_http_client = http_client is None
        if http_client is not None:
            self.http_client = http_client
        else:
            self.http_client = HttpClient(
                user_agent=self.config.user_agent,
                timeout=self.config.timeout_seconds,
                max_requests_per_minute=getattr(
                    self.config, "max_requests_per_minute_per_source", 60
                ),
            )

    def close(self) -> None:
        """Release resources held by the pipeline (HTTP session)."""
        if self._owns_http_client and self.http_client is not None:
            try:
                self.http_client.close()
            except Exception:  # defensive; close() already swallows its own errors
                logger.debug("HttpClient close raised", exc_info=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def extract(
        self,
        source_filter: Optional[str] = None,
        days_back: Optional[int] = None,
        max_articles: Optional[int] = None,
        dry_run: bool = False,
        clear: bool = False,
    ) -> Dict[str, Any]:
        """Run the complete extraction pipeline."""
        monitor = PerformanceMonitor()
        logger.info("Starting news extraction pipeline")

        sources = self.config.get_enabled_sources(source_filter)

        if not sources:
            logger.warning("No enabled sources found")
            return {
                "success": True,
                "sources_processed": 0,
                "items_extracted": 0,
                "items_filtered": 0,
                "records_written": 0,
            }

        logger.info(f"Processing {len(sources)} sources")

        if not dry_run and self.writer is None:
            self.writer = NewsUrlWriter()

        if clear:
            if dry_run:
                logger.info("[DRY RUN] Would clear existing data")
            elif self.writer:
                clear_result = self.writer.clear(dry_run=dry_run)
                if not clear_result["success"]:
                    logger.error("Failed to clear existing data")
                    return {
                        "success": False,
                        "error": "Failed to clear existing data",
                    }

        with monitor.time_operation("source_extraction"):
            extraction_results = self._extract_sources_concurrent(
                sources, days_back, max_articles
            )

        source_watermarks = self.watermarks.fetch_watermarks()

        # Compile items in a deterministic order (input source order, not the
        # nondeterministic as_completed order) so dedup "winner" selection and
        # watermark attribution are stable across runs.
        all_items: List[NewsItem] = []
        item_source_by_url: Dict[str, str] = {}

        for source in sources:
            source_name = source.name
            result = extraction_results.get(
                source_name, {"success": False, "error": "missing result", "items": []}
            )
            filtered_items: List[NewsItem] = []
            if result["success"]:
                filtered_items = self._filter_items_by_watermark(
                    result["items"],
                    source_watermarks.get(source_name),
                )
                for item in filtered_items:
                    item_source_by_url.setdefault(item.url, source_name)
                all_items.extend(filtered_items)

            monitor.record_source_result(
                source_name=source_name,
                success=result["success"],
                items_count=len(filtered_items) if result["success"] else 0,
                error=result.get("error") if not result["success"] else None,
            )

        logger.info(f"Total items extracted: {len(all_items)}")

        # Process items (dedup / validate / filter). UrlProcessor uses local
        # state internally so repeated calls don't leak "seen" URLs.
        processor = UrlProcessor()
        with monitor.time_operation("item_processing"):
            processed_items = processor.process(
                all_items,
                deduplicate=True,
                days_back=days_back,
                nfl_only=None,
            )

        items_filtered = len(all_items) - len(processed_items)
        monitor.record_processing_result(len(processed_items), items_filtered)

        with monitor.time_operation("data_transformation"):
            records = self.transformer.transform(processed_items)

        logger.info(f"Records to write: {len(records)}")

        if dry_run:
            write_result = {"success": True, "dry_run": True, "records_written": len(records)}
            logger.info("[DRY RUN] Skipping database write")
        elif self.writer:
            with monitor.time_operation("database_write"):
                write_result = self.writer.write(records, dry_run=False)
        else:
            write_result = {"success": False, "error": "Writer not initialized"}

        monitor.record_database_result(write_result)

        # Advance watermarks only for sources that actually had a record survive
        # dedup/validation. Prior logic advanced watermarks based on extracted
        # items even when every one of them was later dropped, which could
        # permanently skip that source's backlog.
        processed_sources = {
            item_source_by_url.get(item.url)
            for item in processed_items
            if item_source_by_url.get(item.url)
        }
        new_watermarks: Dict[str, datetime] = {}
        for source_name in processed_sources:
            source_items = [
                item
                for item in processed_items
                if item_source_by_url.get(item.url) == source_name
            ]
            latest = self._get_latest_published_date(source_items)
            if latest is not None:
                new_watermarks[source_name] = latest

        if write_result.get("success") and not dry_run and new_watermarks:
            self.watermarks.update_watermarks(new_watermarks)

        final_metrics = monitor.finish_extraction()

        result = {
            "success": write_result["success"],
            "sources_processed": len(sources),
            "items_extracted": len(all_items),
            "items_filtered": items_filtered,
            "records_written": write_result.get("records_written", 0),
            "new_records": write_result.get("new_records", 0),
            "skipped_records": write_result.get("skipped_records", 0),
            "inserted_ids": write_result.get("inserted_ids", []),
            "total_records": len(records),
            "dry_run": dry_run,
            "metrics": final_metrics.to_dict(),
            "performance": {
                "duration_seconds": final_metrics.duration_seconds,
                "items_per_second": final_metrics.items_per_second,
                "records_per_second": final_metrics.records_per_second,
                "operation_timings": {
                    "source_extraction": monitor.get_operation_timing("source_extraction"),
                    "item_processing": monitor.get_operation_timing("item_processing"),
                    "data_transformation": monitor.get_operation_timing("data_transformation"),
                    "database_write": monitor.get_operation_timing("database_write"),
                },
            },
        }

        if dry_run:
            result["records"] = records

        if not write_result["success"]:
            result["error"] = write_result.get("error")

        return result

    @staticmethod
    def _filter_items_by_watermark(
        items: List[NewsItem], watermark: Optional[datetime]
    ) -> List[NewsItem]:
        """Filter items that are older than the stored watermark."""
        if not watermark:
            return items

        watermark_utc = ensure_utc(watermark)
        filtered: List[NewsItem] = []
        for item in items:
            published = ensure_utc(item.published_date)
            if not published or published > watermark_utc:
                filtered.append(item)

        if len(filtered) != len(items):
            logger.info(
                "Filtered %d items older than watermark %s",
                len(items) - len(filtered),
                watermark_utc.isoformat(),
            )

        return filtered

    @staticmethod
    def _get_latest_published_date(items: List[NewsItem]) -> Optional[datetime]:
        dates = [ensure_utc(item.published_date) for item in items if item.published_date]
        dates = [d for d in dates if d is not None]
        if not dates:
            return None
        return max(dates)

    def _extract_sources_concurrent(
        self,
        sources: List[Any],
        days_back: Optional[int],
        max_articles: Optional[int],
    ) -> Dict[str, Dict[str, Any]]:
        """Extract from multiple sources concurrently."""
        results: Dict[str, Dict[str, Any]] = {}

        # Don't spin up idle threads when there are fewer sources than workers.
        workers = max(1, min(self.max_workers, len(sources)))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_source = {
                executor.submit(
                    self._extract_single_source,
                    source,
                    days_back,
                    max_articles,
                ): source
                for source in sources
            }

            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    results[source.name] = future.result()
                except Exception as e:
                    logger.error(f"Unexpected error processing {source.name}: {e}")
                    results[source.name] = {
                        "success": False,
                        "error": str(e),
                        "items": [],
                    }

        return results

    def _extract_single_source(
        self,
        source: Any,
        days_back: Optional[int],
        max_articles: Optional[int],
    ) -> Dict[str, Any]:
        """Extract from a single source using the shared HTTP client."""
        try:
            extractor = get_extractor(source.type, self.http_client)

            kwargs: Dict[str, Any] = {}
            if days_back:
                kwargs["days_back"] = days_back
            if max_articles:
                kwargs["max_articles"] = max_articles

            items = extractor.extract(source, **kwargs)
            return {
                "success": True,
                "items": items,
                "count": len(items),
            }
        except Exception as e:
            logger.error(f"Error extracting from {source.name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "items": [],
            }
