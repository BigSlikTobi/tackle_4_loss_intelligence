from src.functions.data_loading.functions.request_adapter import normalize_package_request
from src.functions.data_loading.core.contracts.package import (
    Provenance,
    ProvenanceSource,
    Scope,
    Subject,
    TemporalScope,
)
from src.functions.data_loading.core.providers.package_builder import (
    BundleSpec,
    build_package_envelope,
)


def test_normalize_legacy_payload_maps_to_canonical_shape():
    legacy_payload = {
        "schema_version": "1.0.0",
        "producer": "data-analyst-agent",
        "subject": {"entity_type": "team", "entity_id": "CHI"},
        "scope": {"temporal": {"season": 2025, "week": 18}},
        "provenance": {"sources": ["injuries"]},
        "bundles": [{"provider": "injuries", "stream": "injury_reports"}],
    }

    normalized, meta = normalize_package_request(legacy_payload)

    assert normalized["subject"]["ids"]["team_abbr"] == "CHI"
    assert normalized["scope"]["granularity"] == "week"
    assert normalized["scope"]["competition"] == "regular"
    assert normalized["bundles"][0]["provider"] == "injuries"
    assert normalized["bundles"][0]["filters"]["team_abbr"] == "CHI"
    assert meta["warnings"]


def test_build_package_envelope_collects_bundle_errors_when_not_strict():
    subject = Subject(entity_type="team", ids={"team_abbr": "CHI"}, display={"team_abbr": "CHI"})
    scope = Scope(
        granularity="week",
        competition="regular",
        temporal=TemporalScope(season=2025, week=18),
    )
    provenance = Provenance(sources=[ProvenanceSource(name="nfl.test", version="1.0.0")])
    bundles = [
        BundleSpec(
            name="missing_bundle",
            schema_ref="missing.v1",
            record_grain="record",
            provider="this_provider_does_not_exist",
            provider_filters={},
        )
    ]

    envelope = build_package_envelope(
        schema_version="1.0.0",
        producer="test",
        subject=subject,
        scope=scope,
        provenance=provenance,
        bundles=bundles,
        strict_mode=False,
    )
    payload = envelope.to_dict()["payload"]
    assert "missing_bundle" in payload
    assert "error" in payload["missing_bundle"]
    assert envelope.links is not None
    assert envelope.links.get("bundle_errors")
