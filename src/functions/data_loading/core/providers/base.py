"""Provider utilities for on-demand access to transformed datasets."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, List, Sequence

import pandas as pd  # type: ignore

from ...core.pipelines import DatasetPipeline, NullWriter


class DataProvider:
    """Expose a unified interface for fetching dataset records on demand."""

    def __init__(self, name: str, pipeline: DatasetPipeline, fetch_keys: Sequence[str]) -> None:
        self.name = name
        self.pipeline = pipeline
        self.fetch_keys = set(fetch_keys)

    def get(self, *, output: str = "dict", **filters: Any) -> Any:
        """Return dataset records filtered according to ``filters``.

        Parameters
        ----------
        output: str
            Desired output format: ``dict`` (default), ``dataframe`` or ``json``.
        filters: dict
            Keyword arguments mapped to fetch parameters or applied as
            post-transformation equality filters.
        """
        fetch_kwargs = {key: filters.pop(key) for key in list(filters) if key in self.fetch_keys}
        records = self.pipeline.prepare(**fetch_kwargs)
        if filters:
            records = self._apply_filters(records, filters)
        return self._serialise(records, output)

    # ------------------------------------------------------------------
    # Hooks for subclasses / custom behaviour
    def _apply_filters(self, records: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Perform simple equality-based filtering on the record set."""
        if not records or not filters:
            return records

        def matches(record: Dict[str, Any]) -> bool:
            for key, value in filters.items():
                candidate = record.get(key)

                if isinstance(candidate, Iterable) and not isinstance(candidate, (str, bytes, dict)):
                    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
                        if not any(item == candidate_item for candidate_item in candidate for item in value):
                            return False
                    else:
                        if value not in candidate:
                            return False
                    continue

                if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
                    if candidate not in value:
                        return False
                else:
                    if candidate != value:
                        return False
            return True

        return [record for record in records if matches(record)]

    def _serialise(self, records: List[Dict[str, Any]], output: str) -> Any:
        if output in {"dict", "records"}:
            return records
        if output == "dataframe":
            return pd.DataFrame.from_records(records)
        if output == "json":
            return json.dumps(records, default=str)
        raise ValueError(f"Unsupported output format '{output}' for provider '{self.name}'")


class PipelineDataProvider(DataProvider):
    """Concrete provider that wraps a dataset pipeline with a ``NullWriter``."""

    def __init__(self, name: str, pipeline_builder: Callable[..., DatasetPipeline], fetch_keys: Sequence[str]) -> None:
        pipeline = pipeline_builder(writer=NullWriter())
        super().__init__(name=name, pipeline=pipeline, fetch_keys=fetch_keys)

__all__ = ["DataProvider", "PipelineDataProvider"]
