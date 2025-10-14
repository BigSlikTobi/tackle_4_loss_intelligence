"""
Player extraction service for identifying players from play-by-play data.

This module scans through all plays in a game and extracts unique player IDs
from various play action fields (rusher, receiver, passer, tackler, etc.).
"""

from typing import Set, List, Optional
import logging

from ..contracts.game_package import PlayData

logger = logging.getLogger(__name__)


class PlayerExtractor:
    """
    Extracts all unique player IDs from play-by-play data.
    
    Scans every play and collects player IDs from all action fields including
    offensive players (passer, receiver, rusher), defensive players (tacklers, 
    sackers), and special teams players (kickers, punters, returners).
    """
    
    def __init__(self):
        """Initialize the player extractor."""
        self.player_id_fields = [
            # Offensive players
            'passer_player_id',
            'receiver_player_id',
            'rusher_player_id',
            
            # Special teams
            'kicker_player_id',
            'punter_player_id',
            'returner_player_id',
            
            # Turnovers
            'interception_player_id',
            'fumble_recovery_player_id',
            'forced_fumble_player_id',
        ]
        
        self.player_id_list_fields = [
            # Defensive players (often multiple per play)
            'tackler_player_ids',
            'assist_tackler_player_ids',
            'sack_player_ids',
        ]
    
    def extract_players(self, plays: List[PlayData]) -> Set[str]:
        """
        Scan all plays and collect unique player IDs.
        
        Args:
            plays: List of PlayData instances to scan
            
        Returns:
            Set of unique player IDs found across all plays
        """
        if not plays:
            logger.warning("No plays provided for player extraction")
            return set()
        
        player_ids = set()
        
        for play in plays:
            play_ids = self._extract_from_play(play)
            player_ids.update(play_ids)
        
        logger.info(f"Extracted {len(player_ids)} unique players from {len(plays)} plays")
        return player_ids
    
    def _extract_from_play(self, play: PlayData) -> Set[str]:
        """
        Extract player IDs from a single play.
        
        Handles both individual player ID fields and fields that contain
        lists of player IDs (like tacklers).
        
        Args:
            play: PlayData instance to extract from
            
        Returns:
            Set of player IDs found in this play
        """
        play_player_ids = set()
        
        # Extract from single-value fields
        for field in self.player_id_fields:
            value = getattr(play, field, None)
            if value and isinstance(value, str):
                play_player_ids.add(value)
        
        # Extract from list fields
        for field in self.player_id_list_fields:
            value = getattr(play, field, None)
            if value:
                if isinstance(value, list):
                    # Filter out None values and ensure strings
                    ids = [str(pid) for pid in value if pid is not None]
                    play_player_ids.update(ids)
                elif isinstance(value, str):
                    # Sometimes these might be single values instead of lists
                    play_player_ids.add(value)
        
        # Check additional_fields for any other player ID patterns
        if play.additional_fields:
            for key, value in play.additional_fields.items():
                if 'player_id' in key.lower() and value:
                    if isinstance(value, str):
                        play_player_ids.add(value)
                    elif isinstance(value, list):
                        ids = [str(pid) for pid in value if pid is not None]
                        play_player_ids.update(ids)
        
        return play_player_ids
    
    def extract_players_by_team(
        self, 
        plays: List[PlayData],
        home_team: str,
        away_team: str
    ) -> dict:
        """
        Extract players grouped by team.
        
        Args:
            plays: List of PlayData instances to scan
            home_team: Home team abbreviation
            away_team: Away team abbreviation
            
        Returns:
            Dictionary with 'home', 'away', and 'unknown' player ID sets
        """
        home_players = set()
        away_players = set()
        unknown_players = set()
        
        for play in plays:
            play_ids = self._extract_from_play(play)
            
            # Try to determine team based on offensive/defensive context
            if play.posteam:
                if play.posteam == home_team:
                    # Offensive players belong to home team
                    offensive_ids = self._get_offensive_players(play)
                    home_players.update(offensive_ids & play_ids)
                    away_players.update((play_ids - offensive_ids))
                elif play.posteam == away_team:
                    # Offensive players belong to away team
                    offensive_ids = self._get_offensive_players(play)
                    away_players.update(offensive_ids & play_ids)
                    home_players.update((play_ids - offensive_ids))
                else:
                    unknown_players.update(play_ids)
            else:
                unknown_players.update(play_ids)
        
        return {
            'home': home_players,
            'away': away_players,
            'unknown': unknown_players
        }
    
    def _get_offensive_players(self, play: PlayData) -> Set[str]:
        """Get player IDs that are clearly offensive players from a play."""
        offensive_ids = set()
        
        offensive_fields = [
            'passer_player_id',
            'receiver_player_id',
            'rusher_player_id',
            'kicker_player_id',
            'punter_player_id',
            'returner_player_id',
        ]
        
        for field in offensive_fields:
            value = getattr(play, field, None)
            if value and isinstance(value, str):
                offensive_ids.add(value)
        
        return offensive_ids
