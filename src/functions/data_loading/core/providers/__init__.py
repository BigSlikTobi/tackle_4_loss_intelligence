"""Public provider API for on-demand datasets."""

from .base import DataProvider, PipelineDataProvider
from .package_builder import BundleSpec, build_package_envelope
from .pbp import PlayByPlayProvider
from .ngs import NextGenStatsProvider
from .pfr import PfrPlayerSeasonProvider
from .snap_counts import SnapCountsGameProvider
from .registry import get_provider, list_providers

__all__ = [
    "DataProvider",
    "PipelineDataProvider",
    "BundleSpec",
    "build_package_envelope",
    "PlayByPlayProvider",
    "NextGenStatsProvider",
    "PfrPlayerSeasonProvider",
    "SnapCountsGameProvider",
    "get_provider",
    "list_providers",
]
