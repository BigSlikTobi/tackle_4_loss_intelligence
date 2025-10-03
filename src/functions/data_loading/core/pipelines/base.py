"""Common pipeline primitives for dataset ingestion and access."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

import pandas as pd  # type: ignore

from ...core.utils.logging import get_logger


class Writer(Protocol):
    """Protocol describing objects that can persist transformed records."""

    def write(self, records: List[Dict[str, Any]], *, clear: bool = False) -> "PipelineResult":
        ...


@dataclass
class PipelineResult:
    """Aggregated outcome from running a dataset pipeline."""

    success: bool
    processed: int
    written: int = 0
    messages: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation for legacy consumers."""
        payload: Dict[str, Any] = {
            "success": self.success,
            "records_processed": self.processed,
            "records_written": self.written,
        }
        if self.messages:
            payload["messages"] = list(self.messages)
        if self.error:
            payload["error"] = self.error
        return payload


class DatasetPipeline:
    """Coordinates fetch, transform, and optional persistence steps."""

    def __init__(
        self,
        name: str,
        fetcher: Callable[..., pd.DataFrame],
        transformer_factory: Callable[[], Any],
        writer: Optional[Writer] = None,
    ) -> None:
        self.name = name
        self._fetcher = fetcher
        self._transformer_factory = transformer_factory
        self._writer = writer
        self._logger = get_logger(f"DatasetPipeline[{name}]")

    def prepare(self, **params: Any) -> List[Dict[str, Any]]:
        """Fetch raw data and return transformed records without writing."""
        self._logger.debug("Preparing records with params: %s", params)
        raw_df = self._fetcher(**params)
        self._logger.debug("Fetched %d raw rows", len(raw_df))
        transformer = self._transformer_factory()
        records = transformer.transform(raw_df)
        self._logger.debug("Transformed into %d records", len(records))
        return records

    def inspect(self, **params: Any) -> Dict[str, Any]:
        """Return column metadata and a sample of the raw dataset."""
        self._logger.debug("Inspecting dataset with params: %s", params)
        raw_df = self._fetcher(**params)
        columns = list(raw_df.columns)
        dtypes = {column: str(raw_df[column].dtype) for column in columns}
        sample_records = raw_df.head(5).to_dict(orient="records")
        return {
            "columns": columns,
            "dtypes": dtypes,
            "sample": sample_records,
            "rowcount": len(raw_df),
        }

    def run(self, *, dry_run: bool = False, clear: bool = False, **params: Any) -> PipelineResult:
        """Execute the full pipeline and return a structured result."""
        try:
            records = self.prepare(**params)
            processed = len(records)
            if dry_run or self._writer is None:
                message = f"Dry run: {processed} records ready" if dry_run else "Writer not configured; skipping persistence"
                self._logger.info(message)
                return PipelineResult(True, processed, messages=[message])
            result = self._writer.write(records, clear=clear)
            # ensure processed count is preserved inside writer result
            result.processed = processed
            return result
        except Exception as exc:  # pragma: no cover - safety net
            self._logger.exception("Pipeline '%s' failed", self.name)
            return PipelineResult(False, 0, error=str(exc))


class PipelineLoader:
    """Thin adapter that exposes the old loader interface on top of pipelines."""

    def __init__(self, pipeline: DatasetPipeline) -> None:
        self.pipeline = pipeline

    def load_data(self, *, dry_run: bool = False, clear: bool = False, **params: Any) -> Dict[str, Any]:
        """Run the underlying pipeline and return a legacy-style dict."""
        result = self.pipeline.run(dry_run=dry_run, clear=clear, **params)
        return result.to_dict()

    def prepare(self, **params: Any) -> List[Dict[str, Any]]:
        """Expose the transformation step for read-only consumers."""
        return self.pipeline.prepare(**params)

    def inspect(self, **params: Any) -> Dict[str, Any]:
        """Expose dataset column metadata for CLI inspection."""
        return self.pipeline.inspect(**params)

    @property
    def name(self) -> str:
        return self.pipeline.name
