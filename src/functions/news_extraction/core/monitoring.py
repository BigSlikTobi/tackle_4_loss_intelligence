"""
Production monitoring and metrics for news extraction.

Provides structured logging, performance metrics, and monitoring capabilities
for production deployments.
"""

from __future__ import annotations

import time
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExtractionMetrics:
    """Metrics for a single extraction run."""
    
    # Execution metadata
    run_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    
    # Source processing
    sources_total: int = 0
    sources_successful: int = 0
    sources_failed: int = 0
    
    # Item processing
    items_extracted: int = 0
    items_filtered: int = 0
    items_processed: int = 0
    
    # Database operations
    records_written: int = 0
    database_batches: int = 0
    database_failures: int = 0
    write_time_seconds: Optional[float] = None
    
    # Performance metrics
    items_per_second: Optional[float] = None
    records_per_second: Optional[float] = None
    
    # Error tracking
    errors: List[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
    
    def finish(self, end_time: Optional[datetime] = None):
        """Mark the extraction as finished and calculate derived metrics."""
        self.end_time = end_time or datetime.now(timezone.utc)
        self.duration_seconds = (self.end_time - self.start_time).total_seconds()
        
        if self.duration_seconds > 0:
            self.items_per_second = self.items_extracted / self.duration_seconds
            if self.write_time_seconds and self.write_time_seconds > 0:
                self.records_per_second = self.records_written / self.write_time_seconds
    
    def add_error(self, error: str):
        """Add an error to the metrics."""
        self.errors.append(error)
        logger.error(f"Extraction error: {error}")
    
    def add_warning(self, warning: str):
        """Add a warning to the metrics."""
        self.warnings.append(warning)
        logger.warning(f"Extraction warning: {warning}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data


class PerformanceMonitor:
    """
    Performance monitoring and structured logging for news extraction.
    
    Tracks timing, success rates, error patterns, and resource utilization.
    """
    
    def __init__(self, run_id: Optional[str] = None):
        """
        Initialize performance monitor.
        
        Args:
            run_id: Unique identifier for this extraction run
        """
        self.run_id = run_id or f"extraction_{int(time.time())}"
        self.metrics = ExtractionMetrics(
            run_id=self.run_id,
            start_time=datetime.now(timezone.utc)
        )
        self._operation_timers: Dict[str, float] = {}
    
    @contextmanager
    def time_operation(self, operation_name: str):
        """
        Context manager to time individual operations.
        
        Args:
            operation_name: Name of the operation being timed
        """
        start_time = time.time()
        logger.debug(f"Starting operation: {operation_name}")
        
        try:
            yield
        finally:
            duration = time.time() - start_time
            self._operation_timers[operation_name] = duration
            logger.debug(f"Completed operation: {operation_name} in {duration:.2f}s")
    
    def record_source_result(self, source_name: str, success: bool, items_count: int = 0, error: Optional[str] = None):
        """
        Record the result of processing a source.
        
        Args:
            source_name: Name of the source processed
            success: Whether the source was processed successfully
            items_count: Number of items extracted from source
            error: Error message if processing failed
        """
        self.metrics.sources_total += 1
        
        if success:
            self.metrics.sources_successful += 1
            self.metrics.items_extracted += items_count
            logger.info(f"Source {source_name}: SUCCESS - {items_count} items extracted")
        else:
            self.metrics.sources_failed += 1
            error_msg = f"Source {source_name} failed: {error or 'Unknown error'}"
            self.metrics.add_error(error_msg)
    
    def record_processing_result(self, items_processed: int, items_filtered: int):
        """
        Record the result of item processing.
        
        Args:
            items_processed: Number of items that passed processing
            items_filtered: Number of items filtered out
        """
        self.metrics.items_processed = items_processed
        self.metrics.items_filtered = items_filtered
        
        filter_rate = (items_filtered / (items_processed + items_filtered)) * 100 if (items_processed + items_filtered) > 0 else 0
        logger.info(f"Processing complete: {items_processed} processed, {items_filtered} filtered ({filter_rate:.1f}% filter rate)")
    
    def record_database_result(self, result: Dict[str, Any]):
        """
        Record the result of database operations.
        
        Args:
            result: Database write result dictionary
        """
        self.metrics.records_written = result.get("records_written", 0)
        self.metrics.database_batches = result.get("batches_processed", 0)
        self.metrics.database_failures = result.get("failed_batches", 0)
        self.metrics.write_time_seconds = result.get("write_time_seconds")
        
        if not result.get("success", False):
            error_msg = f"Database write failed: {result.get('error', 'Unknown error')}"
            self.metrics.add_error(error_msg)
        else:
            success_rate = result.get("success_rate_percent", 100)
            records_per_sec = result.get("records_per_second", 0)
            write_time = self.metrics.write_time_seconds or 0
            logger.info(f"Database write: {self.metrics.records_written} records in {write_time:.2f}s ({records_per_sec:.1f} rec/s, {success_rate:.1f}% success)")
    
    def finish_extraction(self) -> ExtractionMetrics:
        """
        Finish the extraction and return final metrics.
        
        Returns:
            Final extraction metrics
        """
        self.metrics.finish()
        
        # Log final summary with structured data
        summary = {
            "run_id": self.run_id,
            "duration_seconds": self.metrics.duration_seconds,
            "sources": {
                "total": self.metrics.sources_total,
                "successful": self.metrics.sources_successful,
                "failed": self.metrics.sources_failed,
                "success_rate_percent": (self.metrics.sources_successful / self.metrics.sources_total) * 100 if self.metrics.sources_total > 0 else 0
            },
            "items": {
                "extracted": self.metrics.items_extracted,
                "processed": self.metrics.items_processed,
                "filtered": self.metrics.items_filtered,
                "records_written": self.metrics.records_written
            },
            "performance": {
                "items_per_second": self.metrics.items_per_second,
                "records_per_second": self.metrics.records_per_second,
                "operation_timings": self._operation_timers
            },
            "errors": len(self.metrics.errors),
            "warnings": len(self.metrics.warnings)
        }
        
        logger.info(f"Extraction complete: {json.dumps(summary, default=str, indent=2)}")
        
        # Log any errors or warnings
        if self.metrics.errors:
            logger.error(f"Extraction errors ({len(self.metrics.errors)}): {self.metrics.errors}")
        if self.metrics.warnings:
            logger.warning(f"Extraction warnings ({len(self.metrics.warnings)}): {self.metrics.warnings}")
        
        return self.metrics
    
    def get_operation_timing(self, operation_name: str) -> Optional[float]:
        """Get timing for a specific operation."""
        return self._operation_timers.get(operation_name)


class StructuredLogger:
    """
    Structured logging wrapper for consistent log formatting.
    
    Provides consistent structured logging with contextual information
    and proper log levels for production monitoring.
    """
    
    def __init__(self, logger_name: str, run_id: Optional[str] = None):
        """
        Initialize structured logger.
        
        Args:
            logger_name: Name of the logger
            run_id: Optional run ID for correlation
        """
        self.logger = logging.getLogger(logger_name)
        self.run_id = run_id
        self.context = {}
    
    def set_context(self, **kwargs):
        """Set persistent context for all log messages."""
        self.context.update(kwargs)
    
    def _log_with_context(self, level: int, message: str, **kwargs):
        """Log message with structured context."""
        log_data = {
            "message": message,
            "run_id": self.run_id,
            **self.context,
            **kwargs
        }
        
        # Filter out None values
        log_data = {k: v for k, v in log_data.items() if v is not None}
        
        structured_message = f"{message} | {json.dumps(log_data, default=str)}"
        self.logger.log(level, structured_message)
    
    def info(self, message: str, **kwargs):
        """Log info message with context."""
        self._log_with_context(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message with context."""
        self._log_with_context(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message with context."""
        self._log_with_context(logging.ERROR, message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        """Log debug message with context."""
        self._log_with_context(logging.DEBUG, message, **kwargs)