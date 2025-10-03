"""Service layer for assembling downstream data packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence

from ...core.contracts import (
    DataQuality,
    LocationScope,
    PackageEnvelope,
    Provenance,
    ProvenanceSource,
    ProvenanceTransform,
    Scope,
    Subject,
    TemporalScope,
)
from ...core.providers import BundleSpec, build_package_envelope


@dataclass(frozen=True)
class PackageRequest:
    """Canonical representation of an inbound package assembly request."""

    schema_version: str
    producer: str
    subject: Dict[str, Any]
    scope: Dict[str, Any]
    provenance: Dict[str, Any]
    bundles: Sequence[Dict[str, Any]]
    payload: Dict[str, Any] | None = None
    links: Dict[str, Any] | None = None

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> "PackageRequest":
        try:
            return PackageRequest(
                schema_version=data["schema_version"],
                producer=data["producer"],
                subject=dict(data["subject"]),
                scope=dict(data["scope"]),
                provenance=dict(data["provenance"]),
                bundles=list(data["bundles"]),
                payload=dict(data.get("payload", {})) if data.get("payload") else None,
                links=dict(data.get("links", {})) if data.get("links") else None,
            )
        except KeyError as exc:  # pragma: no cover - user input validation
            raise ValueError(f"Missing required request field: {exc.args[0]}") from exc


# ---------------------------------------------------------------------------
# Assembly helpers


def assemble_package(request_data: Mapping[str, Any] | PackageRequest) -> PackageEnvelope:
    """Assemble a data package from a request mapping or ``PackageRequest``."""

    request = (
        request_data
        if isinstance(request_data, PackageRequest)
        else PackageRequest.from_mapping(request_data)
    )

    subject = _build_subject(request.subject)
    scope = _build_scope(request.scope)
    provenance = _build_provenance(request.provenance)
    bundles = [_build_bundle_spec(bundle) for bundle in request.bundles]

    envelope = build_package_envelope(
        schema_version=request.schema_version,
        producer=request.producer,
        subject=subject,
        scope=scope,
        provenance=provenance,
        bundles=bundles,
        base_payload=request.payload,
        links=request.links,
    )

    if request.payload:
        for key, value in request.payload.items():
            envelope.payload.setdefault(key, value)

    return envelope


def assemble_package_json(payload: Mapping[str, Any] | PackageRequest, *, indent: int | None = 2) -> str:
    """Return the assembled package as a JSON string."""
    envelope = assemble_package(payload)
    return json.dumps(envelope.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Private builders


def _build_subject(data: Mapping[str, Any]) -> Subject:
    return Subject(
        entity_type=data["entity_type"],
        ids=dict(data.get("ids", {})),
        display=dict(data.get("display", {})),
    )


def _build_scope(data: Mapping[str, Any]) -> Scope:
    temporal_raw = data["temporal"]
    temporal = TemporalScope(
        season=temporal_raw["season"],
        week=temporal_raw.get("week"),
        games=list(temporal_raw.get("games", [])) or None,
        date_range_utc=temporal_raw.get("date_range_utc"),
    )
    location_raw = data.get("location")
    location = None
    if location_raw:
        location = LocationScope(
            timezone=location_raw["timezone"],
            venues=list(location_raw.get("venues", [])) or None,
        )
    return Scope(
        granularity=data["granularity"],
        competition=data["competition"],
        temporal=temporal,
        location=location,
    )


def _build_provenance(data: Mapping[str, Any]) -> Provenance:
    sources = [
        ProvenanceSource(
            name=item["name"],
            version=item["version"],
            fetched_at_utc=item.get("fetched_at_utc"),
        )
        for item in data.get("sources", [])
    ]
    if not sources:
        raise ValueError("At least one provenance source is required")

    transforms = [
        ProvenanceTransform(name=item["name"], version=item.get("version"))
        for item in data.get("transforms", [])
    ] or None

    data_quality_raw = data.get("data_quality")
    data_quality = None
    if data_quality_raw:
        data_quality = DataQuality(
            missing_fields=list(data_quality_raw.get("missing_fields", [])) or None,
            assumptions=list(data_quality_raw.get("assumptions", [])) or None,
            row_counts=dict(data_quality_raw.get("row_counts", {})) or None,
        )

    return Provenance(
        sources=sources,
        transforms=transforms,
        data_quality=data_quality,
        license_notes=data.get("license_notes"),
    )


def _build_bundle_spec(data: Mapping[str, Any]) -> BundleSpec:
    if "provider" not in data:
        raise ValueError("Bundle specification missing 'provider'")
    return BundleSpec(
        name=data["name"],
        schema_ref=data["schema_ref"],
        record_grain=data["record_grain"],
        provider=data["provider"],
        provider_filters=dict(data.get("filters", {})),
        provider_options=dict(data.get("provider_options", {})),
        storage_mode=data.get("storage_mode", "inlined"),
        pointer=data.get("pointer"),
        description=data.get("description"),
    )


__all__ = [
    "PackageRequest",
    "assemble_package",
    "assemble_package_json",
]
