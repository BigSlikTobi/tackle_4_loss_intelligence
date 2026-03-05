"""Public provider API for on-demand datasets."""

from .base import DataProvider, PipelineDataProvider
from .injuries import InjuriesProvider
from .player_lookup import PlayerLookupProvider
from .package_builder import BundleSpec, build_package_envelope
from .pbp import PlayByPlayProvider
from .ngs import NextGenStatsProvider
from .pfr import PfrPlayerSeasonProvider
from .snap_counts import SnapCountsGameProvider
from .team_season_stats import TeamSeasonStatsProvider
from .team_weekly_stats import TeamWeeklyStatsProvider
from .registry import get_provider, list_providers

__all__ = [
    "DataProvider",
    "PipelineDataProvider",
    "InjuriesProvider",
    "PlayerLookupProvider",
    "BundleSpec",
    "build_package_envelope",
    "PlayByPlayProvider",
    "NextGenStatsProvider",
    "PfrPlayerSeasonProvider",
    "SnapCountsGameProvider",
    "TeamSeasonStatsProvider",
    "TeamWeeklyStatsProvider",
    "get_provider",
    "list_providers",
]
