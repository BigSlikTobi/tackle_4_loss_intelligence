"""Data contracts and types for game analysis."""

from .game_package import (
    GamePackageInput,
    PlayData,
    GameInfo,
    validate_game_package,
    ValidationError,
)
from .analysis_envelope import (
    AnalysisEnvelope,
    GameHeader,
    CompactTeamSummary,
    CompactPlayerSummary,
    KeySequence,
    DataPointer,
)

__all__ = [
    # Game package contracts
    "GamePackageInput",
    "PlayData",
    "GameInfo",
    "validate_game_package",
    "ValidationError",
    # Analysis envelope contracts
    "AnalysisEnvelope",
    "GameHeader",
    "CompactTeamSummary",
    "CompactPlayerSummary",
    "KeySequence",
    "DataPointer",
]
