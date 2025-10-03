"""
News extraction pipeline.

Orchestrates the complete flow: load config → extract → process → transform → write.
Optimized for production with concurrent processing and comprehensive monitoring.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
import logging

from ..config import load_feed_config, FeedConfig
from ..contracts import NewsItem
from ..extractors import get_extractor
from ..processors import UrlProcessor
from ..data.transformers import NewsTransformer
from ..db import NewsUrlWriter
from ..utils import HttpClient
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
        max_workers: int = 4,
    ):
        """
        Initialize extraction pipeline.

        Args:
            config: Pre-loaded FeedConfig (optional)
            config_path: Path to feeds.yaml (used if config not provided)
            writer: Optional NewsUrlWriter (for testing or dry-run mode)
            max_workers: Maximum concurrent workers for source extraction
        """
        self.config = config or load_feed_config(config_path)
        self.processor = UrlProcessor()
        self.transformer = NewsTransformer()
        self.writer = writer  # Will be lazily initialized if needed
        self.max_workers = max_workers

    def extract(
        self,
        source_filter: Optional[str] = None,
        days_back: Optional[int] = None,
        max_articles: Optional[int] = None,
        dry_run: bool = False,
        clear: bool = False,
    ) -> Dict[str, Any]:
        """
        Run the complete extraction pipeline.

        Args:
            source_filter: Optional filter for source names (substring match)
            days_back: Override days_back filter from config
            max_articles: Override max_articles from config
            dry_run: Simulate without writing to database
            clear: Clear existing records before writing

        Returns:
            Dictionary with extraction results and comprehensive metrics
        """
        # Initialize performance monitoring
        monitor = PerformanceMonitor()
        logger.info("Starting news extraction pipeline")

        # Get enabled sources
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

        # Initialize writer only when needed (not for dry-run without credentials)
        if not dry_run and self.writer is None:
            self.writer = NewsUrlWriter()

        # Clear existing data if requested
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

        # Extract from all sources concurrently
        with monitor.time_operation("source_extraction"):
            extraction_results = self._extract_sources_concurrent(
                sources, days_back, max_articles
            )
        
        # Compile all items and record metrics
        all_items: List[NewsItem] = []
        
        for source_name, result in extraction_results.items():
            monitor.record_source_result(
                source_name=source_name,
                success=result["success"],
                items_count=len(result["items"]) if result["success"] else 0,
                error=result.get("error") if not result["success"] else None
            )
            
            if result["success"]:
                all_items.extend(result["items"])

        logger.info(f"Total items extracted: {len(all_items)}")

        # Process items (deduplicate, validate, filter)
        with monitor.time_operation("item_processing"):
            processed_items = self.processor.process(
                all_items,
                deduplicate=True,
                days_back=days_back,
                nfl_only=None,  # Use per-source nfl_only setting
            )

        # Record processing metrics
        items_filtered = len(all_items) - len(processed_items)
        monitor.record_processing_result(len(processed_items), items_filtered)

        # Transform to database records
        with monitor.time_operation("data_transformation"):
            records = self.transformer.transform(processed_items)

        logger.info(f"Records to write: {len(records)}")

        # Write to database
        if dry_run:
            write_result = {"success": True, "dry_run": True, "records_written": len(records)}
            logger.info("[DRY RUN] Skipping database write")
        elif self.writer:
            with monitor.time_operation("database_write"):
                write_result = self.writer.write(records, dry_run=False)
        else:
            # Should not happen, but handle gracefully
            write_result = {"success": False, "error": "Writer not initialized"}

        # Record database metrics
        monitor.record_database_result(write_result)

        # Finish monitoring and get final metrics
        final_metrics = monitor.finish_extraction()

        # Compile results with enhanced metrics
        result = {
            "success": write_result["success"],
            "sources_processed": len(sources),
            "items_extracted": len(all_items),
            "items_filtered": items_filtered,
            "records_written": write_result.get("records_written", 0),
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
                }
            }
        }

        if dry_run:
            result["records"] = records

        if not write_result["success"]:
            result["error"] = write_result.get("error")

        return result

    def _extract_sources_concurrent(
        self, 
        sources: List[Any], 
        days_back: Optional[int], 
        max_articles: Optional[int]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract from multiple sources concurrently.

        Args:
            sources: List of source configurations
            days_back: Days back filter
            max_articles: Max articles filter

        Returns:
            Dictionary mapping source names to extraction results
        """
        results = {}
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all extraction tasks
            future_to_source = {
                executor.submit(
                    self._extract_single_source, 
                    source, 
                    days_back, 
                    max_articles
                ): source
                for source in sources
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    source_result = future.result()
                    results[source.name] = source_result
                except Exception as e:
                    logger.error(f"Unexpected error processing {source.name}: {e}")
                    results[source.name] = {
                        "success": False,
                        "error": str(e),
                        "items": []
                    }
        
        return results

    def _extract_single_source(
        self, 
        source: Any, 
        days_back: Optional[int], 
        max_articles: Optional[int]
    ) -> Dict[str, Any]:
        """
        Extract from a single source.

        Args:
            source: Source configuration
            days_back: Days back filter
            max_articles: Max articles filter

        Returns:
            Dictionary with extraction result
        """
        try:
            with HttpClient(
                user_agent=self.config.user_agent,
                timeout=self.config.timeout_seconds,
                max_requests_per_minute=self.config.max_parallel_fetches,
            ) as http_client:
                
                # Get appropriate extractor
                extractor = get_extractor(source.type, http_client)
                
                # Prepare extraction arguments
                kwargs = {}
                if days_back:
                    kwargs["days_back"] = days_back
                if max_articles:
                    kwargs["max_articles"] = max_articles
                
                # Extract items
                items = extractor.extract(source, **kwargs)
                
                return {
                    "success": True,
                    "items": items,
                    "count": len(items)
                }
                
        except Exception as e:
            logger.error(f"Error extracting from {source.name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "items": []
            }
