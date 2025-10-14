"""
Game summarization service for computing team and player summaries.

This module provides the GameSummarizer class which:
- Calculates team-level metrics (plays, yards, yards per play, success rate)
- Calculates player-level metrics (touches, yards, TDs, notable events)
- Ensures accuracy and consistency with underlying play-by-play data
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
import logging

from ..contracts.game_package import PlayData
from .data_merger import MergedData

logger = logging.getLogger(__name__)


@dataclass
class TeamSummary:
    """
    Team-level summary metrics for a game.
    
    Calculated from play-by-play data and enrichment sources.
    """
    team: str
    
    # Play counts
    total_plays: int = 0
    offensive_plays: int = 0
    defensive_plays: int = 0
    
    # Yardage
    total_yards: float = 0.0
    passing_yards: float = 0.0
    rushing_yards: float = 0.0
    yards_per_play: float = 0.0
    
    # Scoring
    touchdowns: int = 0
    field_goals: int = 0
    points_scored: int = 0
    
    # Success metrics
    third_down_attempts: int = 0
    third_down_conversions: int = 0
    third_down_pct: float = 0.0
    
    fourth_down_attempts: int = 0
    fourth_down_conversions: int = 0
    fourth_down_pct: float = 0.0
    
    # Turnovers
    turnovers: int = 0
    interceptions_thrown: int = 0
    fumbles_lost: int = 0
    
    # Time of possession (if available)
    time_of_possession: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "team": self.team,
            "total_plays": self.total_plays,
            "offensive_plays": self.offensive_plays,
            "defensive_plays": self.defensive_plays,
            "total_yards": self.total_yards,
            "passing_yards": self.passing_yards,
            "rushing_yards": self.rushing_yards,
            "yards_per_play": self.yards_per_play,
            "touchdowns": self.touchdowns,
            "field_goals": self.field_goals,
            "points_scored": self.points_scored,
            "third_down_attempts": self.third_down_attempts,
            "third_down_conversions": self.third_down_conversions,
            "third_down_pct": self.third_down_pct,
            "fourth_down_attempts": self.fourth_down_attempts,
            "fourth_down_conversions": self.fourth_down_conversions,
            "fourth_down_pct": self.fourth_down_pct,
            "turnovers": self.turnovers,
            "interceptions_thrown": self.interceptions_thrown,
            "fumbles_lost": self.fumbles_lost,
            "time_of_possession": self.time_of_possession,
        }


@dataclass
class PlayerSummary:
    """
    Player-level summary metrics for a game.
    
    Calculated from play-by-play data and enrichment sources.
    """
    player_id: str
    player_name: Optional[str] = None
    position: Optional[str] = None
    team: Optional[str] = None
    
    # Participation
    plays_involved: int = 0
    snaps_played: Optional[int] = None
    snap_percentage: Optional[float] = None
    
    # Touches (rushing + receiving)
    touches: int = 0
    rushing_attempts: int = 0
    receptions: int = 0
    targets: int = 0
    
    # Yardage
    total_yards: float = 0.0
    rushing_yards: float = 0.0
    receiving_yards: float = 0.0
    passing_yards: float = 0.0
    
    # Scoring
    touchdowns: int = 0
    rushing_tds: int = 0
    receiving_tds: int = 0
    passing_tds: int = 0
    
    # Passing (if QB)
    pass_attempts: Optional[int] = None
    completions: Optional[int] = None
    completion_pct: Optional[float] = None
    interceptions: Optional[int] = None
    
    # Defense
    tackles: int = 0
    sacks: float = 0.0
    interceptions_caught: int = 0
    forced_fumbles: int = 0
    fumble_recoveries: int = 0
    
    # Notable events
    notable_events: List[str] = field(default_factory=list)
    
    # Relevance (from RelevanceScorer)
    relevance_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "position": self.position,
            "team": self.team,
            "plays_involved": self.plays_involved,
            "snaps_played": self.snaps_played,
            "snap_percentage": self.snap_percentage,
            "touches": self.touches,
            "rushing_attempts": self.rushing_attempts,
            "receptions": self.receptions,
            "targets": self.targets,
            "total_yards": self.total_yards,
            "rushing_yards": self.rushing_yards,
            "receiving_yards": self.receiving_yards,
            "passing_yards": self.passing_yards,
            "touchdowns": self.touchdowns,
            "rushing_tds": self.rushing_tds,
            "receiving_tds": self.receiving_tds,
            "passing_tds": self.passing_tds,
            "pass_attempts": self.pass_attempts,
            "completions": self.completions,
            "completion_pct": self.completion_pct,
            "interceptions": self.interceptions,
            "tackles": self.tackles,
            "sacks": self.sacks,
            "interceptions_caught": self.interceptions_caught,
            "forced_fumbles": self.forced_fumbles,
            "fumble_recoveries": self.fumble_recoveries,
            "notable_events": self.notable_events,
            "relevance_score": self.relevance_score,
        }


@dataclass
class GameSummaries:
    """
    Complete game summaries including team and player metrics.
    """
    game_id: str
    season: int
    week: int
    
    # Team summaries (keyed by team abbreviation)
    team_summaries: Dict[str, TeamSummary] = field(default_factory=dict)
    
    # Player summaries (keyed by player_id)
    player_summaries: Dict[str, PlayerSummary] = field(default_factory=dict)
    
    # Summary metadata
    summary_timestamp: Optional[float] = None
    plays_analyzed: int = 0
    players_summarized: int = 0
    teams_summarized: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "game_info": {
                "game_id": self.game_id,
                "season": self.season,
                "week": self.week,
            },
            "team_summaries": {
                team: summary.to_dict()
                for team, summary in self.team_summaries.items()
            },
            "player_summaries": {
                player_id: summary.to_dict()
                for player_id, summary in self.player_summaries.items()
            },
            "metadata": {
                "summary_timestamp": self.summary_timestamp,
                "plays_analyzed": self.plays_analyzed,
                "players_summarized": self.players_summarized,
                "teams_summarized": self.teams_summarized,
            },
        }


class GameSummarizer:
    """
    Computes team and player summaries from enriched game data.
    
    The summarizer:
    1. Analyzes play-by-play data to compute team metrics
    2. Aggregates player stats from plays and enrichment data
    3. Calculates derived metrics (yards per play, completion %, etc.)
    4. Identifies notable events for players
    5. Ensures all calculations match underlying data
    
    Example:
        summarizer = GameSummarizer()
        summaries = summarizer.summarize(merged_data, relevant_players)
        
        # Access summaries
        team_stats = summaries.team_summaries["SF"]
        player_stats = summaries.player_summaries["00-0036322"]
    """
    
    def __init__(self):
        """Initialize the game summarizer."""
        pass
    
    def summarize(
        self,
        merged_data: MergedData,
        relevant_players: Optional[List[Any]] = None
    ) -> GameSummaries:
        """
        Compute team and player summaries from merged data.
        
        Args:
            merged_data: Merged game data with plays and enrichment
            relevant_players: Optional list of RelevantPlayer objects with scores
            
        Returns:
            GameSummaries with team and player metrics
        """
        import time
        
        logger.info(
            f"Computing summaries for game {merged_data.game_id} "
            f"({len(merged_data.plays)} plays)"
        )
        
        summaries = GameSummaries(
            game_id=merged_data.game_id,
            season=merged_data.season,
            week=merged_data.week,
            summary_timestamp=time.time(),
            plays_analyzed=len(merged_data.plays)
        )
        
        # Convert plays to PlayData objects for easier processing
        plays = self._convert_plays(merged_data.plays)
        
        # Compute team summaries
        self._compute_team_summaries(plays, summaries)
        
        # Compute player summaries
        self._compute_player_summaries(
            plays,
            merged_data.player_data,
            summaries,
            relevant_players
        )
        
        # Log summary
        logger.info(
            f"Summaries complete: {summaries.teams_summarized} teams, "
            f"{summaries.players_summarized} players"
        )
        
        return summaries
    
    def _convert_plays(self, plays: List[Dict[str, Any]]) -> List[PlayData]:
        """Convert play dictionaries back to PlayData objects."""
        play_objects = []
        
        for play_dict in plays:
            try:
                # Extract known fields
                play = PlayData(
                    play_id=play_dict.get("play_id", ""),
                    game_id=play_dict.get("game_id", ""),
                    quarter=play_dict.get("quarter"),
                    time=play_dict.get("time"),
                    down=play_dict.get("down"),
                    yards_to_go=play_dict.get("yards_to_go"),
                    yardline=play_dict.get("yardline"),
                    posteam=play_dict.get("posteam"),
                    defteam=play_dict.get("defteam"),
                    play_type=play_dict.get("play_type"),
                    yards_gained=play_dict.get("yards_gained"),
                    touchdown=play_dict.get("touchdown"),
                    safety=play_dict.get("safety"),
                    passer_player_id=play_dict.get("passer_player_id"),
                    receiver_player_id=play_dict.get("receiver_player_id"),
                    rusher_player_id=play_dict.get("rusher_player_id"),
                    tackler_player_ids=play_dict.get("tackler_player_ids"),
                    assist_tackler_player_ids=play_dict.get("assist_tackler_player_ids"),
                    sack_player_ids=play_dict.get("sack_player_ids"),
                    kicker_player_id=play_dict.get("kicker_player_id"),
                    punter_player_id=play_dict.get("punter_player_id"),
                    returner_player_id=play_dict.get("returner_player_id"),
                    interception_player_id=play_dict.get("interception_player_id"),
                    fumble_recovery_player_id=play_dict.get("fumble_recovery_player_id"),
                    forced_fumble_player_id=play_dict.get("forced_fumble_player_id"),
                )
                play_objects.append(play)
            except Exception as e:
                logger.warning(f"Error converting play {play_dict.get('play_id')}: {e}")
        
        return play_objects
    
    def _compute_team_summaries(
        self,
        plays: List[PlayData],
        summaries: GameSummaries
    ) -> None:
        """
        Compute team-level summary metrics.
        
        Args:
            plays: List of plays to analyze
            summaries: GameSummaries object to populate
        """
        logger.debug("Computing team summaries")
        
        # Identify teams from plays
        teams: Set[str] = set()
        for play in plays:
            if play.posteam:
                teams.add(play.posteam)
            if play.defteam:
                teams.add(play.defteam)
        
        # Initialize team summaries
        for team in teams:
            summaries.team_summaries[team] = TeamSummary(team=team)
        
        # Analyze each play
        for play in plays:
            if not play.posteam:
                continue
            
            offense = play.posteam
            defense = play.defteam
            
            # Get team summary objects
            off_summary = summaries.team_summaries.get(offense)
            def_summary = summaries.team_summaries.get(defense) if defense else None
            
            if not off_summary:
                continue
            
            # Count plays
            off_summary.total_plays += 1
            off_summary.offensive_plays += 1
            
            if def_summary:
                def_summary.total_plays += 1
                def_summary.defensive_plays += 1
            
            # Add yards
            yards = play.yards_gained or 0.0
            if isinstance(yards, (int, float)):
                off_summary.total_yards += yards
                
                # Categorize by play type
                if play.play_type == "pass":
                    off_summary.passing_yards += yards
                elif play.play_type == "run":
                    off_summary.rushing_yards += yards
            
            # Count touchdowns
            if play.touchdown == 1:
                off_summary.touchdowns += 1
                off_summary.points_scored += 6  # TD worth 6 points
            
            # Count field goals
            if play.play_type == "field_goal":
                # Check if field goal was successful
                # Field goals typically have yards_gained == 0 and are marked successful
                # or can be detected by kicker_player_id being present
                if play.kicker_player_id:
                    # Assume successful if kicker is present (failed FGs may have different patterns)
                    # More accurate detection would require additional fields like "field_goal_result"
                    off_summary.field_goals += 1
                    off_summary.points_scored += 3
            
            # Count extra points (PAT attempts after touchdowns)
            if play.play_type == "extra_point":
                # Extra point is worth 1 point if successful
                # Check for successful PAT (typically yards_gained == 0 for kicks)
                if play.kicker_player_id:
                    off_summary.points_scored += 1
            
            # Count two-point conversions
            if play.play_type == "two_point_attempt":
                # Two-point conversion is worth 2 points if successful (touchdown == 1)
                if play.touchdown == 1:
                    off_summary.points_scored += 2
            
            # Handle safeties - scored by the DEFENSE
            if play.safety == 1:
                # When offense (posteam) takes a safety, defense (defteam) gets 2 points
                if def_summary:
                    def_summary.points_scored += 2
                else:
                    logger.warning(f"Safety play {play.play_id} has no defense team")
            
            # Track turnovers
            if play.interception_player_id:
                off_summary.interceptions_thrown += 1
                off_summary.turnovers += 1
            
            # Note: Fumbles lost would need additional data to distinguish
            # from fumbles recovered by offense
            
            # Track down conversions (would need additional fields like first_down)
            # This is a placeholder for when we have more detailed play data
        
        # Calculate derived metrics
        for team, summary in summaries.team_summaries.items():
            if summary.offensive_plays > 0:
                summary.yards_per_play = summary.total_yards / summary.offensive_plays
            
            if summary.third_down_attempts > 0:
                summary.third_down_pct = (
                    summary.third_down_conversions / summary.third_down_attempts * 100
                )
            
            if summary.fourth_down_attempts > 0:
                summary.fourth_down_pct = (
                    summary.fourth_down_conversions / summary.fourth_down_attempts * 100
                )
        
        summaries.teams_summarized = len(summaries.team_summaries)
        
        logger.info(
            f"Computed summaries for {summaries.teams_summarized} teams"
        )
    
    def _compute_player_summaries(
        self,
        plays: List[PlayData],
        player_data: Dict[str, Dict[str, Any]],
        summaries: GameSummaries,
        relevant_players: Optional[List[Any]] = None
    ) -> None:
        """
        Compute player-level summary metrics.
        
        Args:
            plays: List of plays to analyze
            player_data: Player enrichment data
            summaries: GameSummaries object to populate
            relevant_players: Optional list with relevance scores
        """
        logger.debug(f"Computing player summaries for {len(player_data)} players")
        
        # Build relevance score mapping if provided
        relevance_map = {}
        if relevant_players:
            relevance_map = {
                player.player_id: player.relevance_score
                for player in relevant_players
            }
        
        # Initialize player summaries
        for player_id in player_data.keys():
            summaries.player_summaries[player_id] = PlayerSummary(
                player_id=player_id,
                relevance_score=relevance_map.get(player_id)
            )
        
        # Analyze each play for player involvement
        for play in plays:
            self._process_play_for_players(play, summaries.player_summaries)
        
        # Enrich with player data (NGS stats, snap counts, etc.)
        for player_id, data in player_data.items():
            if player_id not in summaries.player_summaries:
                continue
            
            summary = summaries.player_summaries[player_id]
            
            # Add NGS stats if available
            if "ngs_stats" in data:
                self._add_ngs_stats(summary, data["ngs_stats"])
            
            # Add snap counts if available
            if "snap_counts" in data:
                self._add_snap_counts(summary, data["snap_counts"])
            
            # Identify notable events
            self._identify_notable_events(summary)
        
        # Calculate derived metrics
        for player_id, summary in summaries.player_summaries.items():
            # Calculate touches
            summary.touches = summary.rushing_attempts + summary.receptions
            
            # Calculate total yards
            summary.total_yards = (
                summary.rushing_yards +
                summary.receiving_yards +
                summary.passing_yards
            )
            
            # Calculate total touchdowns
            summary.touchdowns = (
                summary.rushing_tds +
                summary.receiving_tds +
                summary.passing_tds
            )
            
            # Calculate completion percentage
            if summary.pass_attempts and summary.pass_attempts > 0:
                summary.completion_pct = (
                    summary.completions / summary.pass_attempts * 100
                    if summary.completions else 0.0
                )
        
        summaries.players_summarized = len(summaries.player_summaries)
        
        logger.info(
            f"Computed summaries for {summaries.players_summarized} players"
        )
    
    def _process_play_for_players(
        self,
        play: PlayData,
        player_summaries: Dict[str, PlayerSummary]
    ) -> None:
        """
        Process a single play to update player summaries.
        
        Args:
            play: Play to process
            player_summaries: Player summaries to update
        """
        yards = play.yards_gained or 0.0
        is_td = play.touchdown == 1
        
        # Passing play
        # NOTE: pass_attempts includes all passes (complete and incomplete)
        # because passer_player_id is set on all pass plays.
        # Completions are only counted when receiver_player_id is present.
        if play.passer_player_id:
            passer = player_summaries.get(play.passer_player_id)
            if passer:
                passer.plays_involved += 1
                if not passer.pass_attempts:
                    passer.pass_attempts = 0
                    passer.completions = 0
                passer.pass_attempts += 1
                
                if play.receiver_player_id:  # Completed pass
                    passer.completions += 1
                    passer.passing_yards += yards
                    if is_td:
                        passer.passing_tds += 1
        
        # Receiving
        # NOTE: In nflreadpy data, receiver_player_id is only set on COMPLETED passes.
        # Incomplete passes have receiver_player_id = None, so we cannot attribute
        # incomplete targets to specific players. Therefore:
        # - receptions = completions (correct)
        # - targets = completions (data limitation - true targets would include incompletions)
        # - yards/TDs = only from completions (correct)
        if play.receiver_player_id:
            receiver = player_summaries.get(play.receiver_player_id)
            if receiver:
                receiver.plays_involved += 1
                receiver.receptions += 1
                receiver.targets += 1  # Note: This equals receptions due to data limitation
                receiver.receiving_yards += yards
                if is_td:
                    receiver.receiving_tds += 1
        
        # Rushing
        if play.rusher_player_id:
            rusher = player_summaries.get(play.rusher_player_id)
            if rusher:
                rusher.plays_involved += 1
                rusher.rushing_attempts += 1
                rusher.rushing_yards += yards
                if is_td:
                    rusher.rushing_tds += 1
        
        # Defense - tackles
        if play.tackler_player_ids:
            for tackler_id in play.tackler_player_ids:
                tackler = player_summaries.get(tackler_id)
                if tackler:
                    tackler.plays_involved += 1
                    tackler.tackles += 1
        
        if play.assist_tackler_player_ids:
            for tackler_id in play.assist_tackler_player_ids:
                tackler = player_summaries.get(tackler_id)
                if tackler:
                    tackler.plays_involved += 1
                    tackler.tackles += 0.5  # Assisted tackle
        
        # Sacks
        if play.sack_player_ids:
            for sacker_id in play.sack_player_ids:
                sacker = player_summaries.get(sacker_id)
                if sacker:
                    sacker.plays_involved += 1
                    sacker.sacks += 1.0
        
        # Interceptions
        if play.interception_player_id:
            interceptor = player_summaries.get(play.interception_player_id)
            if interceptor:
                interceptor.plays_involved += 1
                interceptor.interceptions_caught += 1
        
        # Fumbles
        if play.forced_fumble_player_id:
            forcer = player_summaries.get(play.forced_fumble_player_id)
            if forcer:
                forcer.plays_involved += 1
                forcer.forced_fumbles += 1
        
        if play.fumble_recovery_player_id:
            recoverer = player_summaries.get(play.fumble_recovery_player_id)
            if recoverer:
                recoverer.plays_involved += 1
                recoverer.fumble_recoveries += 1
    
    def _add_ngs_stats(
        self,
        summary: PlayerSummary,
        ngs_stats: Dict[str, Any]
    ) -> None:
        """
        Add Next Gen Stats to player summary.
        
        Args:
            summary: Player summary to update
            ngs_stats: NGS stats dictionary
        """
        # NGS stats can have multiple types (passing, rushing, receiving)
        for stat_type, stats in ngs_stats.items():
            if not isinstance(stats, dict):
                continue
            
            # Extract player metadata if available
            if not summary.player_name and "player_display_name" in stats:
                summary.player_name = stats["player_display_name"]
            
            if not summary.position and "player_position" in stats:
                summary.position = stats["player_position"]
            
            if not summary.team and "team_abbr" in stats:
                summary.team = stats["team_abbr"]
    
    def _add_snap_counts(
        self,
        summary: PlayerSummary,
        snap_data: Dict[str, Any]
    ) -> None:
        """
        Add snap count data to player summary.
        
        Args:
            summary: Player summary to update
            snap_data: Snap count data dictionary
        """
        if "snaps" in snap_data:
            summary.snaps_played = snap_data["snaps"]
        
        if "snap_pct" in snap_data:
            summary.snap_percentage = snap_data["snap_pct"]
    
    def _identify_notable_events(self, summary: PlayerSummary) -> None:
        """
        Identify notable events for a player.
        
        Args:
            summary: Player summary to analyze
        """
        events = []
        
        # Scoring events
        if summary.touchdowns >= 3:
            events.append(f"{summary.touchdowns} TDs")
        elif summary.touchdowns >= 1:
            events.append(f"{summary.touchdowns} TD")
        
        # Big yardage games
        if summary.rushing_yards >= 100:
            events.append(f"{summary.rushing_yards:.0f} rush yds")
        if summary.receiving_yards >= 100:
            events.append(f"{summary.receiving_yards:.0f} rec yds")
        if summary.passing_yards and summary.passing_yards >= 300:
            events.append(f"{summary.passing_yards:.0f} pass yds")
        
        # Defensive events
        if summary.sacks >= 2:
            events.append(f"{summary.sacks:.1f} sacks")
        if summary.interceptions_caught >= 1:
            events.append(f"{summary.interceptions_caught} INT")
        if summary.forced_fumbles >= 1:
            events.append(f"{summary.forced_fumbles} FF")
        
        summary.notable_events = events
