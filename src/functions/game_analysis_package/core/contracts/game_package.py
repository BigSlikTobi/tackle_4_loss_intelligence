"""
Game package input contracts and validation.

This module defines the data structures for game packages that are submitted
for analysis. It includes validation logic to ensure packages are complete
and well-formed.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class PlayData:
    """
    Individual play data structure from play-by-play data.
    
    Contains all relevant fields from a single play including players involved,
    outcomes, and contextual information.
    """
    play_id: str
    game_id: str
    
    # Play context
    quarter: Optional[int] = None
    time: Optional[str] = None
    down: Optional[int] = None
    yards_to_go: Optional[int] = None
    yardline: Optional[str] = None
    
    # Teams
    posteam: Optional[str] = None
    defteam: Optional[str] = None
    
    # Play type and outcome
    play_type: Optional[str] = None
    yards_gained: Optional[float] = None
    touchdown: Optional[int] = None
    
    # Players involved (can be individual IDs or lists)
    passer_player_id: Optional[str] = None
    receiver_player_id: Optional[str] = None
    rusher_player_id: Optional[str] = None
    
    # Defensive players (often lists)
    tackler_player_ids: Optional[List[str]] = None
    assist_tackler_player_ids: Optional[List[str]] = None
    sack_player_ids: Optional[List[str]] = None
    
    # Special teams
    kicker_player_id: Optional[str] = None
    punter_player_id: Optional[str] = None
    returner_player_id: Optional[str] = None
    
    # Turnovers
    interception_player_id: Optional[str] = None
    fumble_recovery_player_id: Optional[str] = None
    forced_fumble_player_id: Optional[str] = None
    
    # Additional fields stored as raw dict
    additional_fields: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate play data after initialization."""
        if not self.play_id:
            raise ValueError("play_id is required")
        if not self.game_id:
            raise ValueError("game_id is required")


@dataclass
class GameInfo:
    """
    Basic game identification information.
    
    Used to identify which game is being analyzed and retrieve additional
    context from upstream sources.
    """
    season: int
    week: int
    game_id: str
    
    # Optional metadata
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    game_date: Optional[str] = None
    
    def __post_init__(self):
        """Validate game info after initialization."""
        if self.season < 1920 or self.season > datetime.now().year + 1:
            raise ValueError(f"Invalid season: {self.season}")
        if self.week < 1 or self.week > 22:
            raise ValueError(f"Invalid week: {self.week}")
        if not self.game_id:
            raise ValueError("game_id is required")
        
        # Try to parse teams from game_id if not provided
        if not self.home_team or not self.away_team:
            parsed_teams = self._parse_teams_from_game_id()
            if parsed_teams:
                if not self.home_team:
                    self.home_team = parsed_teams['home']
                if not self.away_team:
                    self.away_team = parsed_teams['away']
    
    def _parse_teams_from_game_id(self) -> Optional[Dict[str, str]]:
        """
        Parse team abbreviations from game_id.
        
        Expected format: YYYY_WW_AWAY_HOME
        Example: 2024_05_SF_KC means SF (away) at KC (home)
        
        Returns:
            Dict with 'home' and 'away' keys, or None if parsing fails
        """
        try:
            parts = self.game_id.split('_')
            if len(parts) >= 4:
                # Format: YYYY_WW_AWAY_HOME
                away_team = parts[2]
                home_team = parts[3]
                return {'home': home_team, 'away': away_team}
        except Exception:
            pass
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "season": self.season,
            "week": self.week,
            "game_id": self.game_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "game_date": self.game_date
        }


@dataclass
class GamePackageInput:
    """
    Complete input game package structure.
    
    This is the top-level structure that clients submit for analysis.
    It includes all play-by-play data and optional metadata.
    """
    season: int
    week: int
    game_id: str
    plays: List[PlayData]
    
    # Optional tracking and metadata
    correlation_id: Optional[str] = None
    schema_version: str = "1.0.0"
    producer: Optional[str] = None
    
    def __post_init__(self):
        """Validate game package after initialization."""
        # Validate basic fields
        if self.season < 1920 or self.season > datetime.now().year + 1:
            raise ValueError(f"Invalid season: {self.season}")
        if self.week < 1 or self.week > 22:
            raise ValueError(f"Invalid week: {self.week}")
        if not self.game_id:
            raise ValueError("game_id is required")
        
        # Validate plays
        if not self.plays:
            raise ValueError("At least one play is required")
        
        if not isinstance(self.plays, list):
            raise ValueError("plays must be a list")
        
        # Validate all plays belong to this game
        for i, play in enumerate(self.plays):
            if not isinstance(play, PlayData):
                raise ValueError(f"Play at index {i} is not a PlayData instance")
            if play.game_id != self.game_id:
                raise ValueError(
                    f"Play {play.play_id} has mismatched game_id: "
                    f"expected {self.game_id}, got {play.game_id}"
                )
    
    def get_game_info(self) -> GameInfo:
        """Extract GameInfo from this package."""
        return GameInfo(
            season=self.season,
            week=self.week,
            game_id=self.game_id
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "season": self.season,
            "week": self.week,
            "game_id": self.game_id,
            "plays": [self._play_to_dict(play) for play in self.plays],
            "correlation_id": self.correlation_id,
            "schema_version": self.schema_version,
            "producer": self.producer
        }
    
    @staticmethod
    def _play_to_dict(play: PlayData) -> Dict[str, Any]:
        """Convert a PlayData instance to dictionary."""
        result = {
            "play_id": play.play_id,
            "game_id": play.game_id,
            "quarter": play.quarter,
            "time": play.time,
            "down": play.down,
            "yards_to_go": play.yards_to_go,
            "yardline": play.yardline,
            "posteam": play.posteam,
            "defteam": play.defteam,
            "play_type": play.play_type,
            "yards_gained": play.yards_gained,
            "touchdown": play.touchdown,
            "passer_player_id": play.passer_player_id,
            "receiver_player_id": play.receiver_player_id,
            "rusher_player_id": play.rusher_player_id,
            "tackler_player_ids": play.tackler_player_ids,
            "assist_tackler_player_ids": play.assist_tackler_player_ids,
            "sack_player_ids": play.sack_player_ids,
            "kicker_player_id": play.kicker_player_id,
            "punter_player_id": play.punter_player_id,
            "returner_player_id": play.returner_player_id,
            "interception_player_id": play.interception_player_id,
            "fumble_recovery_player_id": play.fumble_recovery_player_id,
            "forced_fumble_player_id": play.forced_fumble_player_id,
        }
        
        # Add additional fields
        if play.additional_fields:
            result.update(play.additional_fields)
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GamePackageInput':
        """
        Create GamePackageInput from a dictionary.
        
        Args:
            data: Dictionary containing game package data
            
        Returns:
            GamePackageInput instance
            
        Raises:
            ValueError: If required fields are missing or invalid
        """
        # Extract required fields
        try:
            season = data["season"]
            week = data["week"]
            game_id = data["game_id"]
            plays_data = data["plays"]
        except KeyError as e:
            raise ValueError(f"Missing required field: {e}")
        
        # Parse plays
        plays = []
        for i, play_data in enumerate(plays_data):
            try:
                play = cls._play_from_dict(play_data)
                plays.append(play)
            except Exception as e:
                raise ValueError(f"Error parsing play at index {i}: {e}")
        
        # Extract optional fields
        correlation_id = data.get("correlation_id")
        schema_version = data.get("schema_version", "1.0.0")
        producer = data.get("producer")
        
        return cls(
            season=season,
            week=week,
            game_id=game_id,
            plays=plays,
            correlation_id=correlation_id,
            schema_version=schema_version,
            producer=producer
        )
    
    @staticmethod
    def _play_from_dict(data: Dict[str, Any]) -> PlayData:
        """Create PlayData from a dictionary."""
        # Extract known fields
        known_fields = {
            "play_id", "game_id", "quarter", "time", "down", "yards_to_go",
            "yardline", "posteam", "defteam", "play_type", "yards_gained",
            "touchdown", "passer_player_id", "receiver_player_id",
            "rusher_player_id", "tackler_player_ids", "assist_tackler_player_ids",
            "sack_player_ids", "kicker_player_id", "punter_player_id",
            "returner_player_id", "interception_player_id",
            "fumble_recovery_player_id", "forced_fumble_player_id"
        }
        
        # Separate known and additional fields
        play_fields = {k: v for k, v in data.items() if k in known_fields}
        additional_fields = {k: v for k, v in data.items() if k not in known_fields}
        
        return PlayData(
            **play_fields,
            additional_fields=additional_fields
        )


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


def validate_game_package(data: Dict[str, Any]) -> GamePackageInput:
    """
    Validate and parse a game package from raw dictionary data.
    
    Args:
        data: Raw dictionary data from JSON input
        
    Returns:
        Validated GamePackageInput instance
        
    Raises:
        ValidationError: If the package is invalid with descriptive error message
    """
    try:
        # Handle nested game_package structure if present
        if "game_package" in data:
            package_data = data["game_package"]
        else:
            package_data = data
        
        # Parse and validate
        package = GamePackageInput.from_dict(package_data)
        return package
        
    except ValueError as e:
        game_id = data.get("game_package", {}).get("game_id") or data.get("game_id", "unknown")
        raise ValidationError(
            f"Game package validation failed for game {game_id}: {str(e)}"
        )
    except Exception as e:
        raise ValidationError(f"Unexpected error validating game package: {str(e)}")
