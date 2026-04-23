"""Terminal result payload for news_extraction jobs.

This service is pure extraction — it never writes to the database.
Downstream consumers receive the extracted items in the poll response
and are responsible for any persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class JobResult:
    """Pure-extraction result.

    ``items`` is the list of dicts produced by the legacy
    ``NewsTransformer.transform()`` step — one dict per article with
    ``url``, ``title``, ``description``, ``publication_date``,
    ``source_name``, ``publisher``. Stable across the legacy/new contract
    so downstream callers can swap from the old DB-write path to the new
    response-driven path without re-mapping fields.
    """

    sources_processed: int = 0
    items_extracted: int = 0
    items_filtered: int = 0
    items: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    performance: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @classmethod
    def from_pipeline_dict(cls, raw: Dict[str, Any]) -> "JobResult":
        """Build a JobResult from the legacy pipeline's return value.

        The pipeline runs in forced-dry-run mode so it returns a
        ``records`` field that we surface as ``items``.
        """
        return cls(
            sources_processed=int(raw.get("sources_processed", 0) or 0),
            items_extracted=int(raw.get("items_extracted", 0) or 0),
            items_filtered=int(raw.get("items_filtered", 0) or 0),
            items=list(raw.get("records") or []),
            metrics=dict(raw.get("metrics") or {}),
            performance=dict(raw.get("performance") or {}),
            errors=list(raw.get("errors") or []),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sources_processed": self.sources_processed,
            "items_extracted": self.items_extracted,
            "items_filtered": self.items_filtered,
            "items_count": len(self.items),
            "items": self.items,
            "metrics": self.metrics,
            "performance": self.performance,
            "errors": self.errors,
        }
