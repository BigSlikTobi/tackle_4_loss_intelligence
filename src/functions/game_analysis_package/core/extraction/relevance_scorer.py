"""
Relevance scoring for identifying the most impactful players in a game.

This module computes player relevance scores based on multiple impact signals:
- Play frequency (how often they were involved)
- Production metrics (yards, touchdowns)
- High-leverage events (sacks, turnovers, explosive plays)

It then selects a balanced set of players for detailed analysis.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple
import logging

from ..contracts.game_package import PlayData

logger = logging.getLogger(__name__)


@dataclass
class ImpactSignals:
    """
    Impact metrics for a player in a game.
    
    Used to compute overall relevance score.
    """
    # Basic involvement
    play_frequency: int = 0  # Number of plays involved in
    touches: int = 0  # Rushes + receptions + pass attempts
    
    # Production
    yards: float = 0.0  # Total yards (rushing + receiving + passing)
    touchdowns: int = 0  # Total TDs scored
    
    # High-leverage events
    turnovers_caused: int = 0  # Interceptions + forced fumbles
    turnovers_committed: int = 0  # Interceptions thrown + fumbles lost
    sacks: int = 0  # Sacks recorded
    sacks_allowed: int = 0  # Times sacked (for QBs)
    explosive_plays: int = 0  # Plays with 20+ yards
    
    # Special teams
    kick_attempts: int = 0  # FG/punt attempts
    return_yards: float = 0.0  # Return yards
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'play_frequency': self.play_frequency,
            'touches': self.touches,
            'yards': self.yards,
            'touchdowns': self.touchdowns,
            'turnovers_caused': self.turnovers_caused,
            'turnovers_committed': self.turnovers_committed,
            'sacks': self.sacks,
            'sacks_allowed': self.sacks_allowed,
            'explosive_plays': self.explosive_plays,
            'kick_attempts': self.kick_attempts,
            'return_yards': self.return_yards
        }


@dataclass
class RelevantPlayer:
    """
    Player selected for detailed analysis with relevance information.
    """
    player_id: str
    relevance_score: float
    impact_signals: ImpactSignals
    
    # Metadata (populated from play analysis)
    name: Optional[str] = None
    position: Optional[str] = None
    team: Optional[str] = None
    
    # Play summary
    key_plays: List[str] = field(default_factory=list)  # Notable play IDs
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'player_id': self.player_id,
            'name': self.name,
            'position': self.position,
            'team': self.team,
            'relevance_score': round(self.relevance_score, 3),
            'impact_signals': self.impact_signals.to_dict(),
            'key_plays': self.key_plays
        }


class RelevanceScorer:
    """
    Computes player relevance scores and selects balanced sets.
    
    Uses multiple impact signals to identify the most important players
    in a game for detailed analysis. Applies selection rules to ensure
    a balanced representation from both teams.
    """
    
    def __init__(
        self,
        min_play_frequency: int = 1,
        explosive_play_threshold: float = 20.0,
        max_players_per_team: int = 15,
        top_players_per_team: int = 5
    ):
        """
        Initialize the relevance scorer.
        
        Args:
            min_play_frequency: Minimum plays to be considered
            explosive_play_threshold: Yards threshold for explosive plays
            max_players_per_team: Maximum total players per team
            top_players_per_team: Top N players guaranteed from each team
        """
        self.min_play_frequency = min_play_frequency
        self.explosive_play_threshold = explosive_play_threshold
        self.max_players_per_team = max_players_per_team
        self.top_players_per_team = top_players_per_team
    
    def score_and_select(
        self,
        player_ids: Set[str],
        plays: List[PlayData],
        home_team: Optional[str] = None,
        away_team: Optional[str] = None
    ) -> List[RelevantPlayer]:
        """
        Score all players and return balanced selection.
        
        Args:
            player_ids: Set of all player IDs to consider
            plays: List of all plays in the game
            home_team: Home team abbreviation
            away_team: Away team abbreviation
            
        Returns:
            List of RelevantPlayer objects, sorted by relevance score
        """
        logger.info(f"Scoring {len(player_ids)} players across {len(plays)} plays")
        
        # Compute impact signals for each player
        player_signals = self._compute_all_impact_signals(player_ids, plays)
        
        # Calculate relevance scores
        player_scores = {}
        for player_id, signals in player_signals.items():
            score = self._calculate_relevance_score(signals)
            player_scores[player_id] = score
        
        # Select balanced set
        selected_players = self._select_balanced_set(
            player_scores,
            player_signals,
            plays,
            home_team,
            away_team
        )
        
        logger.info(
            f"Selected {len(selected_players)} players "
            f"(avg score: {sum(p.relevance_score for p in selected_players) / len(selected_players):.2f})"
        )
        
        return selected_players
    
    def _compute_all_impact_signals(
        self,
        player_ids: Set[str],
        plays: List[PlayData]
    ) -> Dict[str, ImpactSignals]:
        """
        Compute impact signals for all players.
        
        Args:
            player_ids: Set of player IDs
            plays: List of all plays
            
        Returns:
            Dictionary mapping player_id to ImpactSignals
        """
        signals_map = {pid: ImpactSignals() for pid in player_ids}
        
        for play in plays:
            self._update_signals_from_play(play, signals_map)
        
        return signals_map
    
    def _update_signals_from_play(
        self,
        play: PlayData,
        signals_map: Dict[str, ImpactSignals]
    ):
        """Update impact signals based on a single play."""
        yards = play.yards_gained or 0.0
        is_td = play.touchdown == 1
        is_explosive = abs(yards) >= self.explosive_play_threshold
        
        # Offensive players
        if play.passer_player_id and play.passer_player_id in signals_map:
            signals = signals_map[play.passer_player_id]
            signals.play_frequency += 1
            signals.touches += 1
            signals.yards += yards
            if is_td:
                signals.touchdowns += 1
            if is_explosive:
                signals.explosive_plays += 1
        
        if play.rusher_player_id and play.rusher_player_id in signals_map:
            signals = signals_map[play.rusher_player_id]
            signals.play_frequency += 1
            signals.touches += 1
            signals.yards += yards
            if is_td:
                signals.touchdowns += 1
            if is_explosive:
                signals.explosive_plays += 1
        
        if play.receiver_player_id and play.receiver_player_id in signals_map:
            signals = signals_map[play.receiver_player_id]
            signals.play_frequency += 1
            signals.touches += 1
            signals.yards += yards
            if is_td:
                signals.touchdowns += 1
            if is_explosive:
                signals.explosive_plays += 1
        
        # Defensive players - turnovers
        if play.interception_player_id and play.interception_player_id in signals_map:
            signals = signals_map[play.interception_player_id]
            signals.play_frequency += 1
            signals.turnovers_caused += 1
            if yards != 0:  # Return yards
                signals.return_yards += abs(yards)
            if is_explosive:
                signals.explosive_plays += 1
        
        if play.forced_fumble_player_id and play.forced_fumble_player_id in signals_map:
            signals = signals_map[play.forced_fumble_player_id]
            signals.play_frequency += 1
            signals.turnovers_caused += 1
        
        if play.fumble_recovery_player_id and play.fumble_recovery_player_id in signals_map:
            signals = signals_map[play.fumble_recovery_player_id]
            signals.play_frequency += 1
            signals.turnovers_caused += 1
        
        # Sacks
        if play.sack_player_ids:
            for sacker_id in play.sack_player_ids:
                if sacker_id in signals_map:
                    signals = signals_map[sacker_id]
                    signals.play_frequency += 1
                    signals.sacks += 1
            
            # QB being sacked
            if play.passer_player_id and play.passer_player_id in signals_map:
                signals = signals_map[play.passer_player_id]
                signals.sacks_allowed += 1
        
        # Tacklers
        if play.tackler_player_ids:
            for tackler_id in play.tackler_player_ids:
                if tackler_id in signals_map:
                    signals = signals_map[tackler_id]
                    signals.play_frequency += 1
        
        if play.assist_tackler_player_ids:
            for tackler_id in play.assist_tackler_player_ids:
                if tackler_id in signals_map:
                    signals = signals_map[tackler_id]
                    signals.play_frequency += 1
        
        # Special teams
        if play.kicker_player_id and play.kicker_player_id in signals_map:
            signals = signals_map[play.kicker_player_id]
            signals.play_frequency += 1
            signals.kick_attempts += 1
        
        if play.punter_player_id and play.punter_player_id in signals_map:
            signals = signals_map[play.punter_player_id]
            signals.play_frequency += 1
            signals.kick_attempts += 1
        
        if play.returner_player_id and play.returner_player_id in signals_map:
            signals = signals_map[play.returner_player_id]
            signals.play_frequency += 1
            signals.touches += 1
            if yards != 0:
                signals.return_yards += abs(yards)
            if is_explosive:
                signals.explosive_plays += 1
    
    def _calculate_relevance_score(self, signals: ImpactSignals) -> float:
        """
        Calculate overall relevance score from impact signals.
        
        Scoring formula combines:
        - Base participation (play frequency)
        - Production (yards, TDs)
        - High-leverage events (turnovers, sacks, explosive plays)
        
        Args:
            signals: Impact signals for a player
            
        Returns:
            Relevance score (higher is more relevant)
        """
        score = 0.0
        
        # Base participation (1 point per play)
        score += signals.play_frequency * 1.0
        
        # Touches/involvement (0.5 points per touch)
        score += signals.touches * 0.5
        
        # Yards (0.1 points per yard)
        score += abs(signals.yards) * 0.1
        
        # Touchdowns (20 points each - very impactful)
        score += signals.touchdowns * 20.0
        
        # Turnovers caused (15 points each - game-changing)
        score += signals.turnovers_caused * 15.0
        
        # Sacks (10 points each - high impact)
        score += signals.sacks * 10.0
        
        # Explosive plays (5 points each - momentum shifters)
        score += signals.explosive_plays * 5.0
        
        # Return yards (0.05 points per yard - lower than offense)
        score += signals.return_yards * 0.05
        
        # Special teams (2 points per attempt)
        score += signals.kick_attempts * 2.0
        
        # Penalties for negative events
        score -= signals.turnovers_committed * 10.0
        score -= signals.sacks_allowed * 3.0
        
        return max(0.0, score)  # Ensure non-negative
    
    def _select_balanced_set(
        self,
        player_scores: Dict[str, float],
        player_signals: Dict[str, ImpactSignals],
        plays: List[PlayData],
        home_team: Optional[str],
        away_team: Optional[str]
    ) -> List[RelevantPlayer]:
        """
        Select balanced set of players using selection rules.
        
        Rules:
        1. Include all players who scored TDs
        2. Include all QBs with significant attempts (5+)
        3. Include top N players per team by score
        4. Fill remaining slots with highest scored players
        
        Args:
            player_scores: Mapping of player_id to relevance score
            player_signals: Mapping of player_id to impact signals
            plays: All plays (for position inference)
            home_team: Home team abbreviation
            away_team: Away team abbreviation
            
        Returns:
            List of RelevantPlayer objects
        """
        # Infer player teams and positions from plays
        player_metadata = self._infer_player_metadata(plays, home_team, away_team)
        
        selected: Dict[str, RelevantPlayer] = {}
        
        # Rule 1: Include all players who scored TDs
        for player_id, signals in player_signals.items():
            if signals.touchdowns > 0:
                selected[player_id] = self._create_relevant_player(
                    player_id,
                    player_scores[player_id],
                    signals,
                    player_metadata.get(player_id, {})
                )
        
        logger.debug(f"Rule 1: Selected {len(selected)} players with TDs")
        
        # Rule 2: Include QBs with significant attempts
        qb_threshold = 5
        for player_id, signals in player_signals.items():
            if player_id not in selected and signals.touches >= qb_threshold:
                metadata = player_metadata.get(player_id, {})
                if metadata.get('position') == 'QB':
                    selected[player_id] = self._create_relevant_player(
                        player_id,
                        player_scores[player_id],
                        signals,
                        metadata
                    )
        
        logger.debug(f"Rule 2: Total {len(selected)} players after QBs")
        
        # Rule 3: Top N players per team
        players_by_team = self._group_players_by_team(
            player_scores,
            player_signals,
            player_metadata
        )
        
        for team, team_players in players_by_team.items():
            # Sort by score
            sorted_players = sorted(
                team_players,
                key=lambda x: player_scores[x],
                reverse=True
            )
            
            # Take top N
            for player_id in sorted_players[:self.top_players_per_team]:
                if player_id not in selected:
                    selected[player_id] = self._create_relevant_player(
                        player_id,
                        player_scores[player_id],
                        player_signals[player_id],
                        player_metadata.get(player_id, {})
                    )
        
        logger.debug(f"Rule 3: Total {len(selected)} players after top per team")
        
        # Rule 4: Fill remaining slots with highest scored players
        remaining_players = [
            pid for pid in player_scores.keys()
            if pid not in selected and player_signals[pid].play_frequency >= self.min_play_frequency
        ]
        
        sorted_remaining = sorted(
            remaining_players,
            key=lambda x: player_scores[x],
            reverse=True
        )
        
        max_total = self.max_players_per_team * 2  # Both teams
        slots_remaining = max_total - len(selected)
        
        for player_id in sorted_remaining[:slots_remaining]:
            selected[player_id] = self._create_relevant_player(
                player_id,
                player_scores[player_id],
                player_signals[player_id],
                player_metadata.get(player_id, {})
            )
        
        logger.debug(f"Rule 4: Total {len(selected)} players after filling slots")
        
        # Sort by relevance score
        result = sorted(
            selected.values(),
            key=lambda x: x.relevance_score,
            reverse=True
        )
        
        return result
    
    def _infer_player_metadata(
        self,
        plays: List[PlayData],
        home_team: Optional[str],
        away_team: Optional[str]
    ) -> Dict[str, Dict]:
        """
        Infer player metadata (team, position) from plays.
        
        Args:
            plays: All plays in game
            home_team: Home team abbreviation
            away_team: Away team abbreviation
            
        Returns:
            Dictionary mapping player_id to metadata dict
        """
        metadata: Dict[str, Dict] = {}
        
        for play in plays:
            posteam = play.posteam
            defteam = play.defteam
            
            # Offensive positions
            if play.passer_player_id:
                self._update_metadata(
                    metadata, play.passer_player_id,
                    position='QB', team=posteam
                )
            
            if play.rusher_player_id:
                self._update_metadata(
                    metadata, play.rusher_player_id,
                    position='RB', team=posteam
                )
            
            if play.receiver_player_id:
                self._update_metadata(
                    metadata, play.receiver_player_id,
                    position='WR', team=posteam
                )
            
            # Defensive positions
            if play.sack_player_ids:
                for sacker_id in play.sack_player_ids:
                    self._update_metadata(
                        metadata, sacker_id,
                        position='DL', team=defteam
                    )
            
            if play.interception_player_id:
                self._update_metadata(
                    metadata, play.interception_player_id,
                    position='DB', team=defteam
                )
            
            # Tacklers
            if play.tackler_player_ids:
                for tackler_id in play.tackler_player_ids:
                    self._update_metadata(
                        metadata, tackler_id,
                        position='DEF', team=defteam
                    )
        
        return metadata
    
    def _update_metadata(
        self,
        metadata: Dict[str, Dict],
        player_id: str,
        position: Optional[str] = None,
        team: Optional[str] = None
    ):
        """Update player metadata, preferring more specific information."""
        if player_id not in metadata:
            metadata[player_id] = {}
        
        if position:
            # Prefer more specific positions
            current_pos = metadata[player_id].get('position')
            if not current_pos or len(position) < len(current_pos):
                metadata[player_id]['position'] = position
        
        if team and 'team' not in metadata[player_id]:
            metadata[player_id]['team'] = team
    
    def _group_players_by_team(
        self,
        player_scores: Dict[str, float],
        player_signals: Dict[str, ImpactSignals],
        player_metadata: Dict[str, Dict]
    ) -> Dict[str, List[str]]:
        """Group player IDs by team."""
        by_team: Dict[str, List[str]] = {}
        
        for player_id in player_scores.keys():
            metadata = player_metadata.get(player_id, {})
            team = metadata.get('team', 'UNKNOWN')
            
            if team not in by_team:
                by_team[team] = []
            by_team[team].append(player_id)
        
        return by_team
    
    def _create_relevant_player(
        self,
        player_id: str,
        score: float,
        signals: ImpactSignals,
        metadata: Dict
    ) -> RelevantPlayer:
        """Create RelevantPlayer instance from components."""
        return RelevantPlayer(
            player_id=player_id,
            relevance_score=score,
            impact_signals=signals,
            name=metadata.get('name'),
            position=metadata.get('position'),
            team=metadata.get('team')
        )
