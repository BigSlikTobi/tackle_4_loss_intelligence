"""Helpers to assemble package envelopes from provider bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from ...core.contracts import PackageBundle, PackageEnvelope, Provenance, Scope, Subject
from .registry import get_provider


@dataclass
class BundleSpec:
    """Describe how to materialise a bundle for a package."""

    name: str
    schema_ref: str
    record_grain: str
    provider: str
    provider_filters: Dict[str, Any] = field(default_factory=dict)
    provider_options: Dict[str, Any] = field(default_factory=dict)
    storage_mode: str = "inlined"
    pointer: Optional[str] = None
    description: Optional[str] = None


def build_package_envelope(
    *,
    schema_version: str,
    producer: str,
    subject: Subject,
    scope: Scope,
    provenance: Provenance,
    bundles: Iterable[BundleSpec],
    base_payload: Optional[Dict[str, Any]] = None,
    links: Optional[Dict[str, Any]] = None,
) -> PackageEnvelope:
    """Materialise a package envelope from bundle specifications."""
    package_bundles: List[PackageBundle] = []
    payload: Dict[str, Any] = dict(base_payload or {})

    for spec in bundles:
        storage_mode = spec.storage_mode.lower()
        bundle = PackageBundle(
            name=spec.name,
            schema_ref=spec.schema_ref,
            record_grain=spec.record_grain,
            storage_mode=storage_mode,
            pointer=spec.pointer,
            description=spec.description,
        )
        package_bundles.append(bundle)

        if storage_mode == "inlined":
            if spec.name in payload:
                continue

            provider = get_provider(spec.provider, **spec.provider_options)
            payload[spec.name] = provider.get(**spec.provider_filters)
        elif storage_mode == "pointer":
            if not spec.pointer:
                raise ValueError(f"Bundle '{spec.name}' uses pointer storage but no pointer provided")
        else:
            raise ValueError(f"Unsupported storage_mode '{spec.storage_mode}' for bundle '{spec.name}'")

    return PackageEnvelope(
        schema_version=schema_version,
        producer=producer,
        subject=subject,
        scope=scope,
        provenance=provenance,
        bundles=package_bundles,
        payload=payload,
        links=links,
    )


__all__ = ["BundleSpec", "build_package_envelope"]
