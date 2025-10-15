"""
Play fetching service for retrieving play-by-play data from database.

This module enables dynamic play fetching, allowing users to request game
analysis without providing play data. The API automatically fetches plays
from the data_loading module's pbp provider.
"""

import logging
import time
from typing import List, Dict, Any
from dataclasses import dataclass

from ..contracts.game_package import PlayData


logger = logging.getLogger(__name__)


@dataclass
class PlayFetchResult:
    """
    Result of fetching plays from database.
    
    Attributes:
        plays: List of PlayData objects fetched
        total_count: Number of plays retrieved
        source: Source provider used
        retrieval_time: Time taken to fetch (seconds)
        season: Season fetched
        week: Week fetched
        game_id: Game ID fetched
    """
    plays: List[PlayData]
    total_count: int
    source: str
    retrieval_time: float
    
    # Metadata
    season: int
    week: int
    game_id: str


class PlayFetcher:
    """
    Fetches play-by-play data from the data_loading module.
    
    Uses the 'pbp' provider to retrieve all plays for a given game from
    the database. This enables dynamic play fetching where users can
    send empty plays arrays and have the API fetch data automatically.
    
    Example:
        >>> fetcher = PlayFetcher()
        >>> result = fetcher.fetch_plays(
        ...     season=2024,
        ...     week=5,
        ...     game_id="2024_05_SF_KC"
        ... )
        >>> print(f"Fetched {result.total_count} plays")
    """
    
    def __init__(self):
        """Initialize play fetcher."""
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def fetch_plays(
        self,
        season: int,
        week: int,
        game_id: str
    ) -> PlayFetchResult:
        """
        Fetch all plays for a game from database.
        
        Retrieves play-by-play data using the data_loading module's pbp
        provider. Fetches all plays for the specified season/week, then
        filters to the specific game.
        
        Args:
            season: NFL season year (e.g., 2024)
            week: Week number (1-22)
            game_id: Game identifier (e.g., "2024_05_SF_KC")
            
        Returns:
            PlayFetchResult with all plays for the game
            
        Raises:
            ValueError: If game not found or no plays available
            ImportError: If data_loading module not available
        """
        start_time = time.time()
        
        self.logger.info(
            f"Fetching plays for game {game_id} "
            f"(season={season}, week={week})"
        )
        
        try:
            # Lazy import to avoid circular dependencies
            from src.functions.data_loading.core.providers import get_provider
            
            # Get PBP provider
            self.logger.debug("Getting pbp provider")
            pbp_provider = get_provider("pbp")
            
            # Fetch plays for specific game (pbp provider requires game_id filter)
            self.logger.debug(f"Querying pbp provider for game {game_id}")
            plays_data = pbp_provider.get(
                game_id=game_id,  # Provider requires game_id filter!
                season=season,
                week=week,
                output="dict"
            )
            
            # plays_data should already be filtered to this game by provider
            self.logger.debug(
                f"Retrieved {len(plays_data)} plays for game {game_id}"
            )
            
            if not plays_data:
                error_msg = (
                    f"No plays found for game {game_id} "
                    f"in week {week} of {season} season. "
                    f"The game may not exist in the database or has no play data."
                )
                
                self.logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Convert to PlayData objects
            self.logger.debug(f"Converting {len(plays_data)} plays to PlayData objects")
            play_objects = []
            
            for i, play_dict in enumerate(plays_data):
                try:
                    play_obj = self._dict_to_play_data(play_dict)
                    play_objects.append(play_obj)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to convert play {i+1}/{len(plays_data)} "
                        f"(play_id={play_dict.get('play_id')}): {e}"
                    )
                    # Continue processing other plays
                    continue
            
            retrieval_time = time.time() - start_time
            
            self.logger.info(
                f"✓ Fetched {len(play_objects)} plays for {game_id} "
                f"in {retrieval_time:.2f}s"
            )
            
            return PlayFetchResult(
                plays=play_objects,
                total_count=len(play_objects),
                source="pbp_provider",
                retrieval_time=retrieval_time,
                season=season,
                week=week,
                game_id=game_id
            )
            
        except ImportError as e:
            error_msg = (
                f"Could not import data_loading module: {e}. "
                "Make sure the data_loading module is available."
            )
            self.logger.error(error_msg)
            raise ImportError(error_msg) from e
            
        except Exception as e:
            self.logger.error(
                f"Failed to fetch plays for {game_id}: {e}",
                exc_info=True
            )
            raise ValueError(
                f"Could not fetch plays for game {game_id}: {e}"
            ) from e
    
    def _dict_to_play_data(self, play_dict: Dict[str, Any]) -> PlayData:
        """
        Convert dictionary to PlayData object.
        
        Maps fields from pbp provider format to PlayData dataclass.
        Handles both individual player IDs and lists of IDs.
        
        NOTE: Supports both old and new field names for backward compatibility:
        - OLD: "clock" → NEW: "time"
        - OLD: "distance" → NEW: "yards_to_go"
        - OLD: "yardline_100" → NEW: "yardline"
        - NEW: "quarter" (derived from "qtr" in raw data)
        
        Args:
            play_dict: Dictionary from pbp provider
            
        Returns:
            PlayData object
            
        Raises:
            ValueError: If required fields missing
        """
        # Validate required fields
        if "play_id" not in play_dict:
            raise ValueError("Missing required field: play_id")
        if "game_id" not in play_dict:
            raise ValueError("Missing required field: game_id")
        
        # Extract known fields (supporting both old and new field names)
        play_data = PlayData(
            play_id=play_dict["play_id"],
            game_id=play_dict["game_id"],
            
            # Play context (check new names first, fall back to old names)
            quarter=play_dict.get("quarter"),
            time=play_dict.get("time") or play_dict.get("clock"),
            down=play_dict.get("down"),
            yards_to_go=play_dict.get("yards_to_go") or play_dict.get("distance"),
            yardline=play_dict.get("yardline") or play_dict.get("yardline_100"),
            
            # Teams
            posteam=play_dict.get("posteam"),
            defteam=play_dict.get("defteam"),
            
            # Play type and outcome
            play_type=play_dict.get("play_type"),
            yards_gained=play_dict.get("yards_gained"),
            touchdown=play_dict.get("touchdown"),
            safety=play_dict.get("safety"),
            
            # Offensive players
            passer_player_id=play_dict.get("passer_player_id"),
            receiver_player_id=play_dict.get("receiver_player_id"),
            rusher_player_id=play_dict.get("rusher_player_id"),
            
            # Special teams
            kicker_player_id=play_dict.get("kicker_player_id"),
            punter_player_id=play_dict.get("punter_player_id"),
            returner_player_id=play_dict.get("returner_player_id"),
            
            # Turnovers
            interception_player_id=play_dict.get("interception_player_id"),
            fumble_recovery_player_id=play_dict.get("fumble_recovery_player_id"),
            forced_fumble_player_id=play_dict.get("forced_fumble_player_id"),
        )
        
        # Handle list fields (defensive players)
        if "tackler_player_ids" in play_dict and play_dict["tackler_player_ids"]:
            play_data.tackler_player_ids = play_dict["tackler_player_ids"]
        
        if "assist_tackler_player_ids" in play_dict and play_dict["assist_tackler_player_ids"]:
            play_data.assist_tackler_player_ids = play_dict["assist_tackler_player_ids"]
        
        if "sack_player_ids" in play_dict and play_dict["sack_player_ids"]:
            play_data.sack_player_ids = play_dict["sack_player_ids"]
        
        # Store remaining fields in additional_fields
        known_fields = {
            "play_id", "game_id", "quarter", "time", "down", "yards_to_go",
            "yardline", "posteam", "defteam", "play_type", "yards_gained",
            "touchdown", "safety", "passer_player_id", "receiver_player_id",
            "rusher_player_id", "kicker_player_id", "punter_player_id",
            "returner_player_id", "interception_player_id",
            "fumble_recovery_player_id", "forced_fumble_player_id",
            "tackler_player_ids", "assist_tackler_player_ids", "sack_player_ids"
        }
        
        play_data.additional_fields = {
            k: v for k, v in play_dict.items()
            if k not in known_fields and v is not None
        }
        
        return play_data
