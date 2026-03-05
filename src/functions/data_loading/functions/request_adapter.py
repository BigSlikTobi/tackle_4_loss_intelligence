"""Compatibility adapter for package-handler request payloads."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Mapping


LEGACY_ADAPTER_VERSION = "legacy-adapter.v1"


def normalize_package_request(payload: Mapping[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Normalize inbound payloads to the canonical package contract.

    Returns:
        (normalized_payload, adapter_meta)
    """
    data = deepcopy(dict(payload))
    if not _is_legacy_payload(data):
        return data, {}

    normalized = _legacy_to_canonical(data)
    meta = {
        "warnings": [
            (
                "Legacy package payload accepted via compatibility adapter. "
                "Please migrate to canonical bundle format."
            )
        ],
        "adapter": {
            "name": "legacy_payload_adapter",
            "version": LEGACY_ADAPTER_VERSION,
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    }
    return normalized, meta


def _is_legacy_payload(payload: Mapping[str, Any]) -> bool:
    subject = payload.get("subject")
    bundles = payload.get("bundles")
    provenance = payload.get("provenance")

    if not isinstance(subject, Mapping) or not isinstance(bundles, list):
        return False
    if "entity_id" in subject:
        return True
    if any(isinstance(bundle, Mapping) and "stream" in bundle for bundle in bundles):
        return True
    if isinstance(provenance, Mapping):
        sources = provenance.get("sources", [])
        if sources and isinstance(sources, list) and all(isinstance(v, str) for v in sources):
            return True
    return False


def _legacy_to_canonical(payload: Mapping[str, Any]) -> Dict[str, Any]:
    subject_raw = dict(payload.get("subject", {}))
    scope_raw = dict(payload.get("scope", {}))
    temporal_raw = dict(scope_raw.get("temporal", {}))
    provenance_raw = dict(payload.get("provenance", {}))
    bundles_raw = payload.get("bundles", [])

    entity_type = str(subject_raw.get("entity_type", "")).strip() or "team"
    entity_id = str(subject_raw.get("entity_id", "")).strip()
    season_raw = temporal_raw.get("season")
    if season_raw is None:
        raise ValueError("Legacy payload must include scope.temporal.season")
    season = int(season_raw)
    week = int(temporal_raw.get("week") or 0) if temporal_raw.get("week") is not None else None
    if season <= 0:
        raise ValueError("Legacy payload season must be a positive integer")
    if week is not None and week <= 0:
        raise ValueError("Legacy payload week must be a positive integer")

    canonical_subject = _build_subject(entity_type=entity_type, entity_id=entity_id)
    canonical_scope = {
        "granularity": "week",
        "competition": "regular",
        "temporal": {
            "season": season,
            "week": week,
        },
    }
    canonical_provenance = _build_provenance(provenance_raw)
    canonical_bundles = _build_bundles(
        bundles=bundles_raw,
        entity_type=entity_type,
        entity_id=entity_id,
        season=season,
        week=week,
    )

    return {
        "schema_version": str(payload.get("schema_version", "1.0.0")),
        "producer": str(payload.get("producer", "legacy-client")),
        "subject": canonical_subject,
        "scope": canonical_scope,
        "provenance": canonical_provenance,
        "bundles": canonical_bundles,
        "payload": dict(payload.get("payload", {})) if payload.get("payload") else None,
        "links": dict(payload.get("links", {})) if payload.get("links") else None,
    }


def _build_subject(*, entity_type: str, entity_id: str) -> Dict[str, Any]:
    if entity_type == "player":
        return {
            "entity_type": "player",
            "ids": {"player_id": entity_id},
            "display": {"name": entity_id},
        }
    return {
        "entity_type": "team",
        "ids": {"team_abbr": entity_id.upper()},
        "display": {"team_abbr": entity_id.upper()},
    }


def _build_provenance(provenance: Mapping[str, Any]) -> Dict[str, Any]:
    sources_raw = provenance.get("sources", [])
    sources: list[Dict[str, str]] = []
    if isinstance(sources_raw, list):
        for item in sources_raw:
            if isinstance(item, str):
                sources.append({"name": f"legacy.{item}", "version": LEGACY_ADAPTER_VERSION})
            elif isinstance(item, Mapping) and item.get("name") and item.get("version"):
                sources.append({"name": str(item["name"]), "version": str(item["version"])})

    if not sources:
        sources = [{"name": "legacy.unknown", "version": LEGACY_ADAPTER_VERSION}]

    return {
        "sources": sources,
        "transforms": [
            {
                "name": "legacy_payload_adapter",
                "version": LEGACY_ADAPTER_VERSION,
            }
        ],
    }


def _build_bundles(
    *,
    bundles: Any,
    entity_type: str,
    entity_id: str,
    season: int,
    week: int | None,
) -> list[Dict[str, Any]]:
    if not isinstance(bundles, list):
        return []

    canonical: list[Dict[str, Any]] = []
    for raw in bundles:
        if not isinstance(raw, Mapping):
            continue

        provider = str(raw.get("provider", "")).strip()
        stream = str(raw.get("stream", "")).strip()
        mapped_provider = _map_provider(provider=provider, stream=stream, entity_type=entity_type)
        mapped_name = _bundle_name(mapped_provider, entity_type=entity_type)

        filters: Dict[str, Any] = {"season": season}
        if week is not None:
            filters["week"] = week
        if entity_type == "team":
            filters["team_abbr"] = entity_id.upper()
        elif entity_type == "player":
            filters["player_id"] = entity_id

        canonical.append(
            {
                "name": mapped_name,
                "schema_ref": _schema_ref_for_provider(mapped_provider),
                "record_grain": _record_grain_for_provider(mapped_provider),
                "provider": mapped_provider,
                "filters": filters,
                "storage_mode": "inlined",
                "description": f"Converted from legacy bundle provider={provider} stream={stream}",
            }
        )
    return canonical


def _map_provider(*, provider: str, stream: str, entity_type: str) -> str:
    if provider == "injuries" or stream == "injury_reports":
        return "injuries"
    if provider == "player_weekly_stats" and entity_type == "team":
        return "team_weekly_stats"
    if provider == "player_weekly_stats":
        return "player_weekly_stats"
    return provider


def _bundle_name(provider: str, *, entity_type: str) -> str:
    if provider == "team_weekly_stats":
        return "team_weekly_stats"
    if provider == "player_weekly_stats":
        return "player_weekly_stats"
    if provider == "injuries":
        return "injuries"
    return f"{entity_type}_{provider}"


def _schema_ref_for_provider(provider: str) -> str:
    if provider == "team_weekly_stats":
        return "team.weekly_stats.v1"
    if provider == "player_weekly_stats":
        return "player.weekly_stats.v1"
    if provider == "injuries":
        return "team.injuries.v1"
    if provider == "player_lookup":
        return "player.lookup.v1"
    return f"{provider}.v1"


def _record_grain_for_provider(provider: str) -> str:
    if provider == "team_weekly_stats":
        return "team_week"
    if provider == "player_weekly_stats":
        return "player_week"
    if provider == "injuries":
        return "team_week_player"
    if provider == "player_lookup":
        return "player_match"
    return "record"
