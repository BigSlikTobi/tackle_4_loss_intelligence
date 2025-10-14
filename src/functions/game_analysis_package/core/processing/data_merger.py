"""
Data merging service for creating coherent enriched packages.

This module provides the DataMerger class which:
- Merges normalized data with existing game package
- Keys data by game (season, week, game_id), teams (home/away), and players (unique ID)
- Handles conflicts and missing data gracefully
- Creates a coherent structure for downstream processing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
import logging

from ..contracts.game_package import GamePackageInput, PlayData
from .data_normalizer import NormalizedData

logger = logging.getLogger(__name__)


@dataclass
class MergedData:
    """
    Result of merging normalized data with game package.
    
    Contains a coherent structure with all data organized by:
    - Game (season, week, game_id)
    - Teams (home/away)
    - Players (unique player_id)
    """
    # Core game information
    season: int
    week: int
    game_id: str
    
    # Original plays from package
    plays: List[Dict[str, Any]] = field(default_factory=list)
    
    # Team-level data (keyed by team abbreviation)
    team_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Player-level data (keyed by player_id)
    player_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Additional enriched data
    play_by_play_enrichment: Optional[List[Dict[str, Any]]] = None
    snap_counts: Optional[List[Dict[str, Any]]] = None
    
    # Metadata
    merge_timestamp: Optional[float] = None
    players_enriched: int = 0
    teams_enriched: int = 0
    conflicts_resolved: List[Dict[str, Any]] = field(default_factory=list)
    
    # Provenance tracking
    data_sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "game_info": {
                "season": self.season,
                "week": self.week,
                "game_id": self.game_id,
            },
            "plays": self.plays,
            "team_data": self.team_data,
            "player_data": self.player_data,
            "play_by_play_enrichment": self.play_by_play_enrichment,
            "snap_counts": self.snap_counts,
            "metadata": {
                "merge_timestamp": self.merge_timestamp,
                "players_enriched": self.players_enriched,
                "teams_enriched": self.teams_enriched,
                "conflicts_resolved": self.conflicts_resolved,
            },
            "data_sources": self.data_sources,
        }


class DataMerger:
    """
    Merges normalized data with game package to create enriched package.
    
    The merger:
    1. Preserves original play data from game package
    2. Adds enrichment data from normalized sources
    3. Organizes data by game, team, and player
    4. Handles conflicts gracefully (last-write-wins with logging)
    5. Tracks data provenance
    
    Example:
        merger = DataMerger()
        merged = merger.merge(game_package, normalized_data)
        
        # Access organized data
        player_stats = merged.player_data["00-0036322"]
        team_stats = merged.team_data["SF"]
    """
    
    def __init__(self):
        """Initialize the data merger."""
        pass
    
    def merge(
        self,
        package: GamePackageInput,
        normalized: NormalizedData
    ) -> MergedData:
        """
        Merge normalized data with game package.
        
        Args:
            package: Original game package with plays
            normalized: Normalized data from upstream sources
            
        Returns:
            MergedData with coherent structure
        """
        logger.info(
            f"Merging data for game {package.game_id} "
            f"(season {package.season}, week {package.week})"
        )
        
        import time
        result = MergedData(
            season=package.season,
            week=package.week,
            game_id=package.game_id,
            merge_timestamp=time.time(),
            data_sources=normalized.provenance.copy()
        )
        
        # Step 1: Convert plays to dictionaries
        result.plays = [
            self._play_to_dict(play)
            for play in package.plays
        ]
        
        # Step 2: Merge play-by-play enrichment
        if normalized.play_by_play:
            result.play_by_play_enrichment = self._merge_play_by_play(
                package.plays,
                normalized.play_by_play,
                result
            )
        
        # Step 3: Merge snap counts
        if normalized.snap_counts:
            result.snap_counts = self._merge_snap_counts(
                normalized.snap_counts,
                result
            )
        
        # Step 4: Merge team context
        if normalized.team_context:
            self._merge_team_context(
                normalized.team_context,
                result
            )
        
        # Step 5: Merge NGS data (organized by player)
        self._merge_ngs_data(
            normalized.ngs_data,
            result
        )
        
        # Step 6: Extract player IDs from plays and initialize player_data
        self._initialize_player_data(package.plays, result)
        
        # Log summary
        logger.info(
            f"Merge complete: {result.players_enriched} players enriched, "
            f"{result.teams_enriched} teams enriched, "
            f"{len(result.conflicts_resolved)} conflicts resolved"
        )
        
        return result
    
    def _play_to_dict(self, play: PlayData) -> Dict[str, Any]:
        """Convert PlayData to dictionary for serialization."""
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
    
    def _merge_play_by_play(
        self,
        package_plays: List[PlayData],
        pbp_data: List[Dict[str, Any]],
        result: MergedData
    ) -> List[Dict[str, Any]]:
        """
        Merge play-by-play enrichment data.
        
        Creates a mapping between package plays and fetched PBP data by play_id.
        Enrichment data is kept separate to avoid conflicts with original plays.
        
        Args:
            package_plays: Original plays from package
            pbp_data: Fetched play-by-play data
            result: MergedData to update
            
        Returns:
            List of enriched play data
        """
        logger.debug(
            f"Merging {len(pbp_data)} PBP records with {len(package_plays)} package plays"
        )
        
        # Create index by play_id for fast lookup
        pbp_by_id = {
            record.get("play_id"): record
            for record in pbp_data
            if record.get("play_id")
        }
        
        enriched = []
        for play in package_plays:
            if play.play_id in pbp_by_id:
                enriched.append(pbp_by_id[play.play_id])
            else:
                logger.debug(f"No PBP enrichment found for play {play.play_id}")
        
        logger.info(
            f"Enriched {len(enriched)}/{len(package_plays)} plays with PBP data"
        )
        
        return enriched
    
    def _merge_snap_counts(
        self,
        snap_data: List[Dict[str, Any]],
        result: MergedData
    ) -> List[Dict[str, Any]]:
        """
        Merge snap count data.
        
        Snap counts are already organized by player, so we just filter
        to the relevant game and store them.
        
        Args:
            snap_data: Snap count records
            result: MergedData to update
            
        Returns:
            Filtered snap count data
        """
        logger.debug(f"Processing {len(snap_data)} snap count records")
        
        # Filter to this game
        game_snaps = [
            record for record in snap_data
            if record.get("game_id") == result.game_id
        ]
        
        # Also merge into player_data
        for record in game_snaps:
            player_id = record.get("player_id")
            if player_id:
                if player_id not in result.player_data:
                    result.player_data[player_id] = {}
                
                result.player_data[player_id]["snap_counts"] = record
        
        logger.info(f"Merged snap counts for {len(game_snaps)} players")
        
        return game_snaps
    
    def _merge_team_context(
        self,
        team_data: Dict[str, Any],
        result: MergedData
    ) -> None:
        """
        Merge team context data.
        
        Team context contains season-level stats organized by team.
        We extract and organize by team abbreviation.
        
        Args:
            team_data: Team context data
            result: MergedData to update
        """
        logger.debug("Merging team context data")
        
        # Team data might be nested or flat - handle both
        for key, value in team_data.items():
            if isinstance(value, dict):
                # Nested structure - key is team abbreviation
                if key not in result.team_data:
                    result.team_data[key] = {}
                result.team_data[key]["season_stats"] = value
                result.teams_enriched += 1
            elif key == "teams" and isinstance(value, list):
                # List of team records
                for team_record in value:
                    team_abbr = team_record.get("team")
                    if team_abbr:
                        if team_abbr not in result.team_data:
                            result.team_data[team_abbr] = {}
                        result.team_data[team_abbr]["season_stats"] = team_record
                        result.teams_enriched += 1
        
        logger.info(f"Merged team context for {result.teams_enriched} teams")
    
    def _merge_ngs_data(
        self,
        ngs_data: Dict[str, List[Dict[str, Any]]],
        result: MergedData
    ) -> None:
        """
        Merge Next Gen Stats data.
        
        NGS data is organized by stat type (passing, rushing, receiving).
        We merge it into player_data keyed by player_id.
        
        Args:
            ngs_data: NGS data by stat type
            result: MergedData to update
        """
        logger.debug(f"Merging NGS data for {len(ngs_data)} stat types")
        
        total_records = 0
        for stat_type, records in ngs_data.items():
            logger.debug(f"Processing {len(records)} {stat_type} records")
            
            for record in records:
                player_id = record.get("player_gsis_id") or record.get("player_id")
                if not player_id:
                    logger.warning(
                        f"NGS {stat_type} record missing player_id: {record}"
                    )
                    continue
                
                # Initialize player data if needed
                if player_id not in result.player_data:
                    result.player_data[player_id] = {}
                
                # Add NGS data under stat type key
                if "ngs_stats" not in result.player_data[player_id]:
                    result.player_data[player_id]["ngs_stats"] = {}
                
                result.player_data[player_id]["ngs_stats"][stat_type] = record
                total_records += 1
        
        # Update enrichment count
        result.players_enriched = len([
            p for p in result.player_data.values()
            if "ngs_stats" in p
        ])
        
        logger.info(
            f"Merged {total_records} NGS records for "
            f"{result.players_enriched} players"
        )
    
    def _initialize_player_data(
        self,
        plays: List[PlayData],
        result: MergedData
    ) -> None:
        """
        Initialize player_data entries for all players in plays.
        
        This ensures every player mentioned in plays has an entry in
        player_data, even if we don't have enrichment data for them.
        
        Args:
            plays: Plays from game package
            result: MergedData to update
        """
        logger.debug("Initializing player data from plays")
        
        player_ids: Set[str] = set()
        
        # Collect all player IDs from plays
        for play in plays:
            # Individual player IDs
            for field in [
                "passer_player_id", "receiver_player_id", "rusher_player_id",
                "kicker_player_id", "punter_player_id", "returner_player_id",
                "interception_player_id", "fumble_recovery_player_id",
                "forced_fumble_player_id"
            ]:
                value = getattr(play, field, None)
                if value:
                    player_ids.add(value)
            
            # List fields
            for field in [
                "tackler_player_ids", "assist_tackler_player_ids",
                "sack_player_ids"
            ]:
                values = getattr(play, field, None)
                if values:
                    player_ids.update(values)
        
        # Initialize entries for players not yet in player_data
        for player_id in player_ids:
            if player_id not in result.player_data:
                result.player_data[player_id] = {
                    "player_id": player_id,
                    "in_plays": True,
                }
        
        logger.debug(f"Initialized data for {len(player_ids)} unique players")
    
    def _resolve_conflict(
        self,
        field: str,
        old_value: Any,
        new_value: Any,
        context: str,
        result: MergedData
    ) -> Any:
        """
        Resolve a data conflict between two sources.
        
        Strategy: Last-write-wins with logging of conflicts.
        
        Args:
            field: Field name
            old_value: Existing value
            new_value: New value to merge
            context: Context string for logging
            result: MergedData to update with conflict info
            
        Returns:
            Resolved value (new_value)
        """
        if old_value != new_value:
            logger.debug(
                f"Conflict in {context}.{field}: "
                f"old={old_value}, new={new_value} (using new)"
            )
            
            result.conflicts_resolved.append({
                "context": context,
                "field": field,
                "old_value": str(old_value),
                "new_value": str(new_value),
                "resolution": "last_write_wins",
            })
        
        return new_value
