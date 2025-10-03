"""Registry of dataset providers for on-demand consumption."""

from __future__ import annotations

from typing import Any, Callable, Dict

from ...core.data.loaders.player.ftn import build_ftn_pipeline
from .base import DataProvider, PipelineDataProvider
from .pbp import PlayByPlayProvider
from .player_weekly_stats import PlayerWeeklyStatsProvider
from .ngs import NextGenStatsProvider
from .pfr import PfrPlayerSeasonProvider
from .snap_counts import SnapCountsGameProvider


ProviderFactory = Callable[..., DataProvider]
def _pfr_provider(**_: Any) -> DataProvider:
    return PfrPlayerSeasonProvider()


def _ftn_provider(**_: Any) -> DataProvider:
    return PipelineDataProvider(
        name="ftn_stats",
        pipeline_builder=build_ftn_pipeline,
        fetch_keys=("season", "week"),
    )


def _snap_counts_provider(**_: Any) -> DataProvider:
    return SnapCountsGameProvider()


def _pbp_provider(**_: Any) -> DataProvider:
    return PlayByPlayProvider()


def _ngs_provider(*, stat_type: str, **_: Any) -> DataProvider:
    return NextGenStatsProvider(stat_type=stat_type)


_PROVIDER_FACTORIES: Dict[str, ProviderFactory] = {
    "pfr": _pfr_provider,
    "ftn": _ftn_provider,
    "snap_counts": _snap_counts_provider,
    "pbp": _pbp_provider,
    "ngs": _ngs_provider,
    "player_weekly_stats": lambda **_: PlayerWeeklyStatsProvider(),
}


def get_provider(name: str, **options: Any) -> DataProvider:
    """Return a provider instance registered under ``name``."""
    try:
        factory = _PROVIDER_FACTORIES[name]
    except KeyError as exc:  # pragma: no cover - defensive
        available = ", ".join(sorted(_PROVIDER_FACTORIES))
        raise KeyError(f"Unknown provider '{name}'. Available providers: {available}") from exc
    return factory(**options)


def list_providers() -> Dict[str, ProviderFactory]:
    """Expose available provider factories for discovery."""
    return dict(_PROVIDER_FACTORIES)


__all__ = ["get_provider", "list_providers"]
