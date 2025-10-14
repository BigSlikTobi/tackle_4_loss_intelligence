"""
Data request bundling for fetching data from multiple upstream sources.

This module builds combined data requests to efficiently fetch all required
data in a single batch from multiple providers (play-by-play, snap counts,
team context, Next Gen Stats).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Any
import logging

from ..contracts.game_package import GameInfo

logger = logging.getLogger(__name__)


@dataclass
class NGSRequest:
    """Request for Next Gen Stats data for specific players."""
    player_ids: List[str]
    stat_type: str  # 'rushing', 'receiving', 'passing'
    season: int
    week: int


@dataclass
class CombinedDataRequest:
    """
    Combined request for all data sources needed for game analysis.
    
    Bundles requests for play-by-play, snap counts, team context, and
    position-appropriate Next Gen Stats into a single structure.
    """
    # Game identification
    season: int
    week: int
    game_id: str
    
    # Teams
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    
    # Data source requests
    include_play_by_play: bool = True
    include_snap_counts: bool = True
    include_team_context: bool = True
    
    # Player-specific NGS requests
    ngs_requests: List[NGSRequest] = field(default_factory=list)
    
    # Player IDs for reference
    player_ids: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "season": self.season,
            "week": self.week,
            "game_id": self.game_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "include_play_by_play": self.include_play_by_play,
            "include_snap_counts": self.include_snap_counts,
            "include_team_context": self.include_team_context,
            "ngs_requests": [
                {
                    "player_ids": req.player_ids,
                    "stat_type": req.stat_type,
                    "season": req.season,
                    "week": req.week
                }
                for req in self.ngs_requests
            ],
            "player_ids": list(self.player_ids)
        }


@dataclass
class RelevantPlayer:
    """
    Player selected for detailed analysis.
    
    Contains player identification and metadata needed to determine
    which stats to fetch.
    """
    player_id: str
    name: Optional[str] = None
    position: Optional[str] = None
    team: Optional[str] = None
    relevance_score: float = 0.0


class DataRequestBuilder:
    """
    Builds combined data requests for upstream sources.
    
    Creates a single request structure that bundles all required data sources:
    - Full game play-by-play
    - Team snap counts for both teams
    - Contextual team information
    - Position-appropriate Next Gen Stats for selected players
    """
    
    def __init__(self):
        """Initialize the request builder."""
        # Position to NGS stat type mapping
        self.position_to_ngs_type = {
            'QB': 'passing',
            'RB': 'rushing',
            'FB': 'rushing',
            'WR': 'receiving',
            'TE': 'receiving',
        }
    
    def build_request(
        self,
        game_info: GameInfo,
        relevant_players: List[RelevantPlayer],
        home_team: Optional[str] = None,
        away_team: Optional[str] = None
    ) -> CombinedDataRequest:
        """
        Create single request for all required data sources.
        
        Args:
            game_info: Game identification information
            relevant_players: Players selected for detailed analysis
            home_team: Home team abbreviation (optional)
            away_team: Away team abbreviation (optional)
            
        Returns:
            CombinedDataRequest with all data source requests bundled
        """
        logger.info(
            f"Building data request for game {game_info.game_id} "
            f"with {len(relevant_players)} relevant players"
        )
        
        # Build NGS requests based on player positions
        ngs_requests = self._build_ngs_requests(relevant_players, game_info)
        
        # Extract player IDs
        player_ids = {player.player_id for player in relevant_players}
        
        # Create combined request
        request = CombinedDataRequest(
            season=game_info.season,
            week=game_info.week,
            game_id=game_info.game_id,
            home_team=home_team or game_info.home_team,
            away_team=away_team or game_info.away_team,
            include_play_by_play=True,
            include_snap_counts=True,
            include_team_context=True,
            ngs_requests=ngs_requests,
            player_ids=player_ids
        )
        
        logger.info(
            f"Built request with {len(ngs_requests)} NGS requests "
            f"for {len(player_ids)} players"
        )
        
        return request
    
    def _build_ngs_requests(
        self,
        players: List[RelevantPlayer],
        game_info: GameInfo
    ) -> List[NGSRequest]:
        """
        Build position-appropriate NGS requests for players.
        
        Groups players by position category and creates requests for each
        stat type. For players without clear positions, includes both primary
        and secondary stat types.
        
        Args:
            players: List of relevant players
            game_info: Game information for season/week context
            
        Returns:
            List of NGSRequest objects grouped by stat type
        """
        # Group players by NGS stat type
        players_by_stat_type: Dict[str, List[str]] = {}
        
        for player in players:
            # Determine primary stat type based on position
            primary_stat_type = self._get_primary_stat_type(player.position)
            
            if primary_stat_type:
                if primary_stat_type not in players_by_stat_type:
                    players_by_stat_type[primary_stat_type] = []
                players_by_stat_type[primary_stat_type].append(player.player_id)
                
                # Add secondary stat types for versatile positions
                secondary_types = self._get_secondary_stat_types(player.position)
                for stat_type in secondary_types:
                    if stat_type not in players_by_stat_type:
                        players_by_stat_type[stat_type] = []
                    if player.player_id not in players_by_stat_type[stat_type]:
                        players_by_stat_type[stat_type].append(player.player_id)
        
        # Create NGS requests for each stat type
        ngs_requests = []
        for stat_type, player_ids in players_by_stat_type.items():
            if player_ids:
                request = NGSRequest(
                    player_ids=player_ids,
                    stat_type=stat_type,
                    season=game_info.season,
                    week=game_info.week
                )
                ngs_requests.append(request)
                logger.debug(
                    f"Created NGS request for {stat_type} with {len(player_ids)} players"
                )
        
        return ngs_requests
    
    def _get_primary_stat_type(self, position: Optional[str]) -> Optional[str]:
        """
        Get primary NGS stat type for a position.
        
        Args:
            position: Player position abbreviation
            
        Returns:
            Primary stat type ('passing', 'rushing', 'receiving') or None
        """
        if not position:
            return None
        
        position = position.upper()
        return self.position_to_ngs_type.get(position)
    
    def _get_secondary_stat_types(self, position: Optional[str]) -> List[str]:
        """
        Get secondary NGS stat types for versatile positions.
        
        Some positions may have secondary stat types. For example:
        - RBs may also have receiving stats
        - TEs may also have rushing stats (though rare)
        
        Args:
            position: Player position abbreviation
            
        Returns:
            List of secondary stat types to fetch
        """
        if not position:
            return []
        
        position = position.upper()
        
        # RBs also get receiving stats (common for pass-catching backs)
        if position in ['RB', 'FB']:
            return ['receiving']
        
        # TEs sometimes get rushing stats (trick plays, jet sweeps)
        if position == 'TE':
            return ['rushing']
        
        # WRs sometimes get rushing stats (jet sweeps, reverses, wildcat)
        if position == 'WR':
            return ['rushing']
        
        # QBs get rushing stats (scrambles, designed runs)
        if position == 'QB':
            return ['rushing']
        
        return []
    
    def build_minimal_request(self, game_info: GameInfo) -> CombinedDataRequest:
        """
        Build minimal request with just basic game data (no NGS).
        
        Useful for initial validation or when player-specific data isn't needed.
        
        Args:
            game_info: Game identification information
            
        Returns:
            CombinedDataRequest with only basic data sources
        """
        return CombinedDataRequest(
            season=game_info.season,
            week=game_info.week,
            game_id=game_info.game_id,
            home_team=game_info.home_team,
            away_team=game_info.away_team,
            include_play_by_play=True,
            include_snap_counts=True,
            include_team_context=True,
            ngs_requests=[],
            player_ids=set()
        )
