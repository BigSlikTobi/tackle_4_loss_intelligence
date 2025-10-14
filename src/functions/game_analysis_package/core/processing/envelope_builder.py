"""
Analysis envelope builder service.

This module creates compact, LLM-friendly analysis envelopes from game summaries
and merged data. The envelope is optimized for AI consumption while maintaining
analytical richness.
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional
import logging

from ..contracts.analysis_envelope import (
    AnalysisEnvelope,
    GameHeader,
    CompactTeamSummary,
    CompactPlayerSummary,
    KeySequence,
    DataPointer,
)
from ..contracts.game_package import PlayData
from .game_summarizer import GameSummaries, TeamSummary, PlayerSummary
from .data_merger import MergedData

logger = logging.getLogger(__name__)


class AnalysisEnvelopeBuilder:
    """
    Creates compact, LLM-friendly analysis envelopes.
    
    The builder transforms detailed game summaries and merged data into
    a compact format optimized for AI consumption, including:
    - Game header with essential context
    - One-line team summaries
    - Compact player map with key stats
    - Key sequences for notable game moments
    - Pointers to comprehensive datasets
    
    Example:
        builder = AnalysisEnvelopeBuilder()
        envelope = builder.build_envelope(
            merged_data=merged_data,
            summaries=summaries,
            correlation_id="2024_01_SF_KC"
        )
    """
    
    def __init__(self):
        """Initialize the envelope builder."""
        pass
    
    def build_envelope(
        self,
        merged_data: MergedData,
        summaries: GameSummaries,
        correlation_id: Optional[str] = None
    ) -> AnalysisEnvelope:
        """
        Build a compact analysis envelope from summaries and merged data.
        
        Args:
            merged_data: Merged game data with plays and enrichment
            summaries: Pre-computed team and player summaries
            correlation_id: Optional correlation ID for tracking
            
        Returns:
            AnalysisEnvelope optimized for LLM consumption
        """
        logger.info(f"Building analysis envelope for game {merged_data.game_id}")
        
        # Create envelope components
        game_header = self._create_game_header(merged_data)
        team_summaries = self._create_team_summaries(summaries.team_summaries)
        player_map = self._create_player_map(summaries.player_summaries)
        key_sequences = self._extract_key_sequences(merged_data.plays)
        data_pointers = self._create_data_pointers(merged_data)
        
        envelope = AnalysisEnvelope(
            game_header=game_header,
            team_summaries=team_summaries,
            player_map=player_map,
            key_sequences=key_sequences,
            data_pointers=data_pointers,
            correlation_id=correlation_id or merged_data.game_id,
        )
        
        logger.info(
            f"Envelope created: {len(team_summaries)} teams, "
            f"{len(player_map)} players, {len(key_sequences)} key moments"
        )
        
        return envelope
    
    def _create_game_header(self, merged_data: MergedData) -> GameHeader:
        """
        Create compact game header from merged data.
        
        Args:
            merged_data: Merged game data
            
        Returns:
            GameHeader with essential context
        """
        # Extract home/away teams from merged data
        # In play data, we need to infer home/away from the plays
        teams = set()
        for play in merged_data.plays:
            if play.get("posteam"):
                teams.add(play.get("posteam"))
            if play.get("defteam"):
                teams.add(play.get("defteam"))
        
        teams_list = sorted(teams)
        
        # Try to determine home/away (convention: first team alphabetically is away)
        away_team = teams_list[0] if len(teams_list) > 0 else "UNKNOWN"
        home_team = teams_list[1] if len(teams_list) > 1 else "UNKNOWN"
        
        return GameHeader(
            game_id=merged_data.game_id,
            season=merged_data.season,
            week=merged_data.week,
            home_team=home_team,
            away_team=away_team,
        )
    
    def _create_team_summaries(
        self,
        team_summaries: Dict[str, TeamSummary]
    ) -> Dict[str, CompactTeamSummary]:
        """
        Create compact team summaries for the envelope.
        
        Args:
            team_summaries: Detailed team summaries
            
        Returns:
            Dictionary of compact team summaries
        """
        compact_summaries = {}
        
        for team, summary in team_summaries.items():
            compact_summaries[team] = CompactTeamSummary(
                team=summary.team,
                points=summary.points_scored,
                total_plays=summary.offensive_plays,
                total_yards=summary.total_yards,
                yards_per_play=summary.yards_per_play,
                turnovers=summary.turnovers,
                passing_yards=summary.passing_yards,
                rushing_yards=summary.rushing_yards,
                touchdowns=summary.touchdowns,
                field_goals=summary.field_goals,
            )
        
        return compact_summaries
    
    def _create_player_map(
        self,
        player_summaries: Dict[str, PlayerSummary]
    ) -> Dict[str, CompactPlayerSummary]:
        """
        Create compact player map for the envelope.
        
        Args:
            player_summaries: Detailed player summaries
            
        Returns:
            Dictionary of compact player summaries
        """
        compact_players = {}
        
        for player_id, summary in player_summaries.items():
            # Build stats dict with only non-zero values
            stats = {}
            
            # Offensive stats
            if summary.touches > 0:
                stats["touches"] = summary.touches
            if summary.rushing_attempts > 0:
                stats["rush_att"] = summary.rushing_attempts
            if summary.rushing_yards != 0:
                stats["rush_yds"] = round(summary.rushing_yards, 1)
            if summary.receptions > 0:
                stats["rec"] = summary.receptions
            if summary.targets > 0:
                stats["tgt"] = summary.targets
            if summary.receiving_yards != 0:
                stats["rec_yds"] = round(summary.receiving_yards, 1)
            
            # Passing stats
            if summary.pass_attempts and summary.pass_attempts > 0:
                stats["pass_att"] = summary.pass_attempts
                stats["pass_cmp"] = summary.completions or 0
                if summary.passing_yards:
                    stats["pass_yds"] = round(summary.passing_yards, 1)
            
            # Scoring
            if summary.touchdowns > 0:
                stats["tds"] = summary.touchdowns
            
            # Defensive stats
            if summary.tackles > 0:
                stats["tkl"] = round(summary.tackles, 1)
            if summary.sacks > 0:
                stats["sack"] = round(summary.sacks, 1)
            if summary.interceptions_caught > 0:
                stats["int"] = summary.interceptions_caught
            if summary.forced_fumbles > 0:
                stats["ff"] = summary.forced_fumbles
            
            # Add relevance score if available
            if summary.relevance_score is not None:
                stats["rel_score"] = round(summary.relevance_score, 2)
            
            compact_players[player_id] = CompactPlayerSummary(
                player_id=player_id,
                name=summary.player_name,
                position=summary.position,
                team=summary.team,
                stats=stats,
            )
        
        return compact_players
    
    def _extract_key_sequences(
        self,
        plays: List[Dict[str, Any]]
    ) -> List[KeySequence]:
        """
        Identify and label notable game moments.
        
        Args:
            plays: List of play dictionaries
            
        Returns:
            List of key sequences representing notable moments
        """
        key_sequences = []
        
        # Extract scoring plays
        for play in plays:
            play_id = str(play.get("play_id", ""))
            posteam = play.get("posteam")
            
            # Touchdowns
            if play.get("touchdown") == 1:
                key_sequences.append(KeySequence(
                    sequence_type="score",
                    label=f"TD by {posteam}",
                    play_ids=[play_id],
                    team=posteam,
                    quarter=play.get("quarter"),
                    time=play.get("time"),
                ))
            
            # Field goals
            elif play.get("play_type") == "field_goal" and play.get("kicker_player_id"):
                key_sequences.append(KeySequence(
                    sequence_type="score",
                    label=f"FG by {posteam}",
                    play_ids=[play_id],
                    team=posteam,
                    quarter=play.get("quarter"),
                    time=play.get("time"),
                ))
            
            # Safeties
            elif play.get("safety") == 1:
                defteam = play.get("defteam")
                key_sequences.append(KeySequence(
                    sequence_type="score",
                    label=f"Safety by {defteam}",
                    play_ids=[play_id],
                    team=defteam,
                    quarter=play.get("quarter"),
                    time=play.get("time"),
                ))
            
            # Turnovers
            if play.get("interception_player_id"):
                defteam = play.get("defteam")
                key_sequences.append(KeySequence(
                    sequence_type="turnover",
                    label=f"INT by {defteam}",
                    play_ids=[play_id],
                    team=defteam,
                    quarter=play.get("quarter"),
                    time=play.get("time"),
                ))
            
            # Big plays (20+ yards)
            yards = play.get("yards_gained", 0)
            if isinstance(yards, (int, float)) and yards >= 20:
                play_type = play.get("play_type", "play")
                key_sequences.append(KeySequence(
                    sequence_type="big_play",
                    label=f"{int(yards)}yd {play_type} by {posteam}",
                    play_ids=[play_id],
                    team=posteam,
                    quarter=play.get("quarter"),
                    time=play.get("time"),
                ))
        
        logger.debug(f"Extracted {len(key_sequences)} key sequences")
        
        return key_sequences
    
    def _create_data_pointers(
        self,
        merged_data: MergedData
    ) -> Dict[str, DataPointer]:
        """
        Create pointers to comprehensive datasets outside the envelope.
        
        Args:
            merged_data: Merged game data
            
        Returns:
            Dictionary of data pointers
        """
        pointers = {}
        
        # Pointer to full play-by-play data
        if merged_data.plays:
            pointers["play_by_play"] = DataPointer(
                data_type="play_by_play",
                description="Complete play-by-play data with all fields",
                location=f"merged_data.plays[{len(merged_data.plays)} plays]",
                record_count=len(merged_data.plays),
            )
        
        # Pointer to enriched player data
        if merged_data.player_data:
            pointers["player_data"] = DataPointer(
                data_type="player_enrichment",
                description="Detailed player stats and NGS data",
                location=f"merged_data.player_data[{len(merged_data.player_data)} players]",
                player_count=len(merged_data.player_data),
            )
        
        # Pointer to team data
        if merged_data.team_data:
            pointers["team_data"] = DataPointer(
                data_type="team_context",
                description="Team-level context and statistics",
                location=f"merged_data.team_data[{len(merged_data.team_data)} teams]",
            )
        
        # Pointer to snap counts if available
        if merged_data.snap_counts:
            pointers["snap_counts"] = DataPointer(
                data_type="snap_counts",
                description="Player snap count data",
                location=f"merged_data.snap_counts[{len(merged_data.snap_counts)} records]",
                record_count=len(merged_data.snap_counts),
            )
        
        logger.debug(f"Created {len(pointers)} data pointers")
        
        return pointers
