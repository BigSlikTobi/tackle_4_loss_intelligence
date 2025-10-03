"""Base data transformation utilities for NFL datasets."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd  # type: ignore


class BaseDataTransformer:
    """Abstract base class for transforming raw DataFrame rows into records."""

    required_fields: List[str] = []  # a list of keys that must be present

    def transform(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Convert a pandas DataFrame into a list of records."""
        records: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            record = self.sanitize_record(row.to_dict())
            if self.validate_record(record):
                records.append(record)
        return self.deduplicate_records(records)

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Return a cleaned version of ``record``."""
        return record

    def validate_record(self, record: Dict[str, Any]) -> bool:
        """Return ``True`` if ``record`` contains all required fields."""
        for field in self.required_fields:
            if not record.get(field):
                return False
        return True

    def deduplicate_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate records based on their dictionary representation."""
        seen = set()
        unique_records: List[Dict[str, Any]] = []
        for record in records:
            key = tuple(sorted(record.items()))
            if key not in seen:
                seen.add(key)
                unique_records.append(record)
        return unique_records
