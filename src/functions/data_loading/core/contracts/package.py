"""Package contract definitions for downstream data consumers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def _utc_now() -> str:
    """Return an ISO-8601 timestamp with UTC designator."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _prune(value: Any) -> Any:
    """Recursively drop ``None`` values from nested structures."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if item is None:
                continue
            pruned = _prune(item)
            if pruned is not None:
                cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        return [item for item in (_prune(i) for i in value) if item is not None]
    return value


def _canonical_hash(payload: Dict[str, Any]) -> str:
    """Generate a deterministic hash for the supplied payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Subject:
    entity_type: str
    ids: Dict[str, str]
    display: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "ids": dict(sorted(self.ids.items())),
            "display": _prune(self.display),
        }

    def identity(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "ids": dict(sorted(self.ids.items())),
        }


@dataclass(frozen=True)
class TemporalScope:
    season: int
    week: Optional[int] = None
    games: Optional[List[str]] = None
    date_range_utc: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return _prune({
            "season": self.season,
            "week": self.week,
            "games": self.games,
            "date_range_utc": self.date_range_utc,
        })


@dataclass(frozen=True)
class LocationScope:
    timezone: str
    venues: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return _prune({
            "timezone": self.timezone,
            "venues": self.venues,
        })


@dataclass(frozen=True)
class Scope:
    granularity: str
    competition: str
    temporal: TemporalScope
    location: Optional[LocationScope] = None

    def to_dict(self) -> Dict[str, Any]:
        return _prune({
            "granularity": self.granularity,
            "competition": self.competition,
            "temporal": self.temporal.to_dict(),
            "location": self.location.to_dict() if self.location else None,
        })

    def identity(self) -> Dict[str, Any]:
        payload = {
            "granularity": self.granularity,
            "competition": self.competition,
            "temporal": self.temporal.to_dict(),
        }
        if self.location:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass(frozen=True)
class ProvenanceSource:
    name: str
    version: str
    fetched_at_utc: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _prune({
            "name": self.name,
            "version": self.version,
            "fetched_at_utc": self.fetched_at_utc,
        })

    def identity(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True)
class ProvenanceTransform:
    name: str
    version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _prune({"name": self.name, "version": self.version})


@dataclass(frozen=True)
class DataQuality:
    missing_fields: Optional[List[str]] = None
    assumptions: Optional[List[str]] = None
    row_counts: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return _prune({
            "missing_fields": self.missing_fields,
            "assumptions": self.assumptions,
            "row_counts": self.row_counts,
        })


@dataclass(frozen=True)
class Provenance:
    sources: List[ProvenanceSource]
    transforms: Optional[List[ProvenanceTransform]] = None
    data_quality: Optional[DataQuality] = None
    license_notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _prune({
            "sources": [source.to_dict() for source in self.sources],
            "transforms": [transform.to_dict() for transform in self.transforms] if self.transforms else None,
            "data_quality": self.data_quality.to_dict() if self.data_quality else None,
            "license_notes": self.license_notes,
        })

    def identity(self) -> Dict[str, Any]:
        return {
            "sources": [source.identity() for source in self.sources],
        }


@dataclass(frozen=True)
class PackageBundle:
    name: str
    schema_ref: str
    record_grain: str
    storage_mode: str
    pointer: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _prune({
            "name": self.name,
            "schema_ref": self.schema_ref,
            "record_grain": self.record_grain,
            "storage_mode": self.storage_mode,
            "pointer": self.pointer,
            "description": self.description,
        })

    def identity(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "schema_ref": self.schema_ref,
            "record_grain": self.record_grain,
            "storage_mode": self.storage_mode,
            "pointer": self.pointer,
        }


def compute_package_id(
    *,
    schema_version: str,
    subject: Subject,
    scope: Scope,
    bundles: Iterable[PackageBundle],
    provenance: Provenance,
) -> str:
    """Compute the deterministic package identifier."""
    identity_payload = {
        "schema_version": schema_version,
        "subject": subject.identity(),
        "scope": scope.identity(),
        "bundles": [bundle.identity() for bundle in bundles],
        "sources": provenance.identity()["sources"],
    }
    return _canonical_hash(identity_payload)


@dataclass
class PackageEnvelope:
    schema_version: str
    producer: str
    subject: Subject
    scope: Scope
    provenance: Provenance
    bundles: List[PackageBundle]
    payload: Dict[str, Any] = field(default_factory=dict)
    links: Optional[Dict[str, Any]] = None
    created_at_utc: str = field(default_factory=_utc_now)
    package_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.bundles:
            raise ValueError("At least one bundle is required")
        self._validate_payload()
        object.__setattr__(
            self,
            "package_id",
            compute_package_id(
                schema_version=self.schema_version,
                subject=self.subject,
                scope=self.scope,
                bundles=self.bundles,
                provenance=self.provenance,
            ),
        )

    def _validate_payload(self) -> None:
        payload_keys = set(self.payload.keys())
        for bundle in self.bundles:
            if bundle.storage_mode.lower() == "inlined" and bundle.name not in payload_keys:
                raise ValueError(f"Inline bundle '{bundle.name}' requires payload['{bundle.name}']")
            if bundle.storage_mode.lower() == "pointer" and not bundle.pointer:
                raise ValueError(f"Pointer bundle '{bundle.name}' requires a pointer value")

    def to_dict(self) -> Dict[str, Any]:
        return _prune({
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "created_at_utc": self.created_at_utc,
            "producer": self.producer,
            "subject": self.subject.to_dict(),
            "scope": self.scope.to_dict(),
            "provenance": self.provenance.to_dict(),
            "bundles": [bundle.to_dict() for bundle in self.bundles],
            "payload": self.payload,
            "links": self.links,
        })


__all__ = [
    "Subject",
    "TemporalScope",
    "LocationScope",
    "Scope",
    "ProvenanceSource",
    "ProvenanceTransform",
    "DataQuality",
    "Provenance",
    "PackageBundle",
    "PackageEnvelope",
    "compute_package_id",
]

