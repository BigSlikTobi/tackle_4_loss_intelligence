"""
Player metadata enrichment service for fetching player names, positions, and teams.

This module enables enriching player summaries with metadata from nflreadpy,
providing complete player information for downstream AI/LLM analysis without
requiring database dependencies or additional cross-references.
"""

import logging
from typing import Dict, Set, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PlayerMetadata:
    """
    Player metadata from nflreadpy.
    
    Attributes:
        player_id: NFL GSIS player ID
        name: Player display name
        position: Player position
        team: Current team abbreviation
    """
    player_id: str
    name: Optional[str] = None
    position: Optional[str] = None
    team: Optional[str] = None


class PlayerMetadataEnricher:
    """
    Fetches player metadata from nflreadpy to enrich player summaries.
    
    This service uses nflreadpy to get player names, positions, and teams
    for all players involved in a game. This provides complete player 
    information for downstream analysis without database coupling.
    
    Example:
        >>> enricher = PlayerMetadataEnricher()
        >>> metadata = enricher.fetch_player_metadata(
        ...     player_ids={"00-0039732", "00-0038783"},
        ...     season=2024
        ... )
        >>> print(metadata["00-0039732"].name)
        "Bo Nix"
    """
    
    def __init__(self):
        """Initialize player metadata enricher."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self._roster_cache = {}  # Cache rosters by season
    
    def fetch_player_metadata(
        self,
        player_ids: Set[str],
        season: int
    ) -> Dict[str, PlayerMetadata]:
        """
        Fetch player metadata from nflreadpy for given player IDs.
        
        Uses nflreadpy's roster data to get name, position, and team for each
        player ID. Caches roster data per season to avoid redundant fetches.
        
        Args:
            player_ids: Set of NFL GSIS player IDs to fetch metadata for
            season: NFL season year (e.g., 2024)
            
        Returns:
            Dictionary mapping player_id to PlayerMetadata
        """
        if not player_ids:
            self.logger.debug("No player IDs to fetch metadata for")
            return {}
        
        self.logger.info(
            f"Fetching metadata for {len(player_ids)} players from nflreadpy "
            f"(season {season})"
        )
        
        try:
            # Import nflreadpy
            try:
                import nflreadpy as nfl
            except ImportError:
                self.logger.error(
                    "nflreadpy not available. "
                    "Install with: pip install nflreadpy"
                )
                return {}
            
            # Fetch roster data for the season (cached)
            if season not in self._roster_cache:
                self.logger.debug(f"Fetching roster data for season {season}...")
                roster_df = nfl.load_rosters([season])
                self._roster_cache[season] = roster_df
                self.logger.debug(f"✓ Cached {len(roster_df)} roster records")
            else:
                roster_df = self._roster_cache[season]
                self.logger.debug(f"Using cached roster data ({len(roster_df)} records)")
            
            # Convert player IDs to set for faster lookup
            player_ids_set = set(player_ids)
            
            # Filter roster to only requested players (using gsis_id column)
            # nflreadpy returns a Polars DataFrame
            player_roster = roster_df.filter(
                roster_df['gsis_id'].is_in(player_ids_set)
            )
            
            # Build metadata dictionary
            metadata = {}
            for row_dict in player_roster.iter_rows(named=True):
                player_id = row_dict.get('gsis_id')
                if not player_id or player_id not in player_ids_set:
                    continue
                
                metadata[player_id] = PlayerMetadata(
                    player_id=player_id,
                    name=row_dict.get('full_name'),
                    position=row_dict.get('position'),
                    team=row_dict.get('team')
                )
            
            found_count = len(metadata)
            missing_count = len(player_ids) - found_count
            
            if missing_count > 0:
                self.logger.warning(
                    f"Found metadata for {found_count}/{len(player_ids)} players. "
                    f"{missing_count} players not in {season} rosters."
                )
            else:
                self.logger.info(
                    f"✓ Fetched metadata for all {found_count} players"
                )
            
            return metadata
            
        except Exception as e:
            self.logger.error(
                f"Failed to fetch player metadata from nflreadpy: {e}",
                exc_info=True
            )
            # Return empty dict rather than failing - metadata is optional
            self.logger.warning(
                "Continuing without player metadata due to fetch error"
            )
            return {}
    
    def enrich_player_summaries(
        self,
        player_summaries: Dict[str, Any],
        metadata: Dict[str, PlayerMetadata]
    ) -> None:
        """
        Enrich player summaries with metadata in-place.
        
        Updates each player summary's name, position, and team fields with
        data from the metadata dictionary. Only updates fields that are
        currently None.
        
        Args:
            player_summaries: Dictionary of player summaries to enrich
            metadata: Dictionary of player metadata fetched from database
        """
        if not metadata:
            self.logger.warning("No metadata available for enrichment")
            return
        
        enriched_count = 0
        
        for player_id, summary in player_summaries.items():
            player_meta = metadata.get(player_id)
            if not player_meta:
                continue
            
            # Update name if not already set
            if not summary.player_name and player_meta.name:
                summary.player_name = player_meta.name
                enriched_count += 1
            
            # Update position if not already set
            if not summary.position and player_meta.position:
                summary.position = player_meta.position
            
            # Update team if not already set
            if not summary.team and player_meta.team:
                summary.team = player_meta.team
        
        self.logger.info(
            f"✓ Enriched {enriched_count}/{len(player_summaries)} player summaries with metadata"
        )


__all__ = ["PlayerMetadataEnricher", "PlayerMetadata"]
