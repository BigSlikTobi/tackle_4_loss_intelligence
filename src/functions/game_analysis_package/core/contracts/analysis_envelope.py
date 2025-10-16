"""
Analysis envelope data contracts.

This module defines the structure of the compact, LLM-friendly analysis envelope
that is optimized for AI consumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from ..utils.json_safe import clean_nan_values


@dataclass
class GameHeader:
    """
    Compact game header information for the envelope.
    
    Provides essential context about the game without verbose details.
    """
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    
    # Optional metadata
    date: Optional[str] = None
    location: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "game_id": self.game_id,
            "season": self.season,
            "week": self.week,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "date": self.date,
            "location": self.location,
        }
        return clean_nan_values(result)


@dataclass
class CompactTeamSummary:
    """
    One-line team summary for the envelope.
    
    Provides essential team performance metrics in a compact format.
    """
    team: str
    points: int
    total_plays: int
    total_yards: float
    yards_per_play: float
    turnovers: int
    
    # Key stats in compact format
    passing_yards: float = 0.0
    rushing_yards: float = 0.0
    touchdowns: int = 0
    field_goals: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "team": self.team,
            "points": self.points,
            "plays": self.total_plays,
            "yards": self.total_yards,
            "ypp": round(self.yards_per_play, 2),
            "pass_yds": self.passing_yards,
            "rush_yds": self.rushing_yards,
            "tds": self.touchdowns,
            "fgs": self.field_goals,
            "to": self.turnovers,
        }
        return clean_nan_values(result)


@dataclass
class CompactPlayerSummary:
    """
    Compact player summary for the envelope player map.
    
    Provides player identification and key stats in a compact format.
    """
    player_id: str
    name: Optional[str]
    position: Optional[str]
    team: Optional[str]
    
    # Key statistics (only non-zero values included)
    stats: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "id": self.player_id,
            "name": self.name,
            "pos": self.position,
            "team": self.team,
        }
        
        # Only include non-empty stats
        if self.stats:
            result["stats"] = clean_nan_values(self.stats)
        
        return clean_nan_values(result)


@dataclass
class KeySequence:
    """
    Notable game moment with references to underlying plays.
    
    Represents key sequences like scoring drives, turnovers, etc.
    """
    sequence_type: str  # 'score', 'turnover', 'big_play', etc.
    label: str  # Short description
    play_ids: List[str]  # References to underlying plays
    
    # Optional contextual information
    team: Optional[str] = None
    quarter: Optional[int] = None
    time: Optional[str] = None
    description: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "type": self.sequence_type,
            "label": self.label,
            "plays": self.play_ids,
        }
        
        # Add optional fields if present
        if self.team:
            result["team"] = self.team
        if self.quarter:
            result["quarter"] = self.quarter
        if self.time:
            result["time"] = self.time
        if self.description:
            result["desc"] = self.description
        
        return clean_nan_values(result)


@dataclass
class DataPointer:
    """
    Pointer to comprehensive dataset outside the envelope.
    
    Provides links to detailed data that would be too large for the envelope.
    """
    data_type: str  # 'ngs_passing', 'ngs_rushing', 'snap_counts', etc.
    description: str
    location: str  # Path, URL, or identifier where data can be found
    
    # Optional metadata
    player_count: Optional[int] = None
    record_count: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "type": self.data_type,
            "description": self.description,
            "location": self.location,
        }
        
        if self.player_count is not None:
            result["player_count"] = self.player_count
        if self.record_count is not None:
            result["record_count"] = self.record_count
        
        return clean_nan_values(result)


@dataclass
class AnalysisEnvelope:
    """
    Compact, LLM-ready analysis package.
    
    Optimized for AI consumption with essential game information,
    team summaries, player maps, key sequences, and pointers to
    detailed data.
    """
    game_header: GameHeader
    team_summaries: Dict[str, CompactTeamSummary]
    player_map: Dict[str, CompactPlayerSummary]
    
    # Optional components
    key_sequences: List[KeySequence] = field(default_factory=list)
    data_pointers: Dict[str, DataPointer] = field(default_factory=dict)
    
    # Metadata
    correlation_id: Optional[str] = None
    envelope_version: str = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "version": self.envelope_version,
            "correlation_id": self.correlation_id,
            "game": self.game_header.to_dict(),
            "teams": {
                team: summary.to_dict()
                for team, summary in self.team_summaries.items()
            },
            "players": {
                player_id: summary.to_dict()
                for player_id, summary in self.player_map.items()
            },
            "key_moments": [seq.to_dict() for seq in self.key_sequences],
            "data_links": {
                key: pointer.to_dict()
                for key, pointer in self.data_pointers.items()
            },
        }
        return clean_nan_values(result)
