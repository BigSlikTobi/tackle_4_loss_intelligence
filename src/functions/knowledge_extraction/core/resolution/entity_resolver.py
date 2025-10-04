"""
Entity resolution service for matching extracted entities to database IDs.

Handles fuzzy matching, nicknames, and aliases for players, teams, and games.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)


@dataclass
class ResolvedEntity:
    """Represents a resolved entity with database ID."""
    
    entity_type: str  # 'player', 'team', 'game'
    entity_id: str  # player_id, team_abbr, or game_id
    mention_text: str  # Original mention from extraction
    matched_name: str  # Canonical name from database
    confidence: float  # Resolution confidence score
    is_primary: bool = False  # From extraction


class EntityResolver:
    """
    Resolves extracted entity mentions to database IDs.
    
    Uses fuzzy matching and caching to efficiently match players, teams, and games.
    """
    
    def __init__(self, confidence_threshold: float = 0.7):
        """
        Initialize the entity resolver.
        
        Args:
            confidence_threshold: Minimum confidence score for matches (0.0-1.0)
        """
        self.confidence_threshold = confidence_threshold
        self.client = get_supabase_client()
        
        # Caches for database lookups
        self._players_cache: Optional[Dict[str, Dict]] = None
        self._teams_cache: Optional[Dict[str, Dict]] = None
        self._games_cache: Optional[Dict[str, Dict]] = None
        
        # Common team abbreviations and aliases
        self._team_aliases = {
            # Full names to abbreviations
            "kansas city chiefs": "KC",
            "los angeles chargers": "LAC",
            "san francisco 49ers": "SF",
            "new england patriots": "NE",
            "green bay packers": "GB",
            "dallas cowboys": "DAL",
            "pittsburgh steelers": "PIT",
            # Add more as needed...
            
            # Nicknames
            "niners": "SF",
            "pack": "GB",
            "pats": "NE",
            "hawks": "SEA",
            "birds": "PHI",  # Could be multiple teams, handle with context
            "fins": "MIA",
            "bolts": "LAC",
        }
        
        logger.info(f"Initialized EntityResolver with threshold={confidence_threshold}")
    
    def resolve_player(
        self,
        mention_text: str,
        context: Optional[str] = None
    ) -> Optional[ResolvedEntity]:
        """
        Resolve a player mention to a player_id.
        
        Args:
            mention_text: Player name/nickname from extraction
            context: Context around the mention (helps with disambiguation)
            
        Returns:
            ResolvedEntity if match found, None otherwise
        """
        if not self._players_cache:
            self._load_players_cache()
        
        # Clean the mention text
        clean_mention = self._normalize_text(mention_text)
        
        # Try exact match first (case-insensitive)
        for player_id, player in self._players_cache.items():
            if self._exact_match(clean_mention, player):
                return ResolvedEntity(
                    entity_type="player",
                    entity_id=player_id,
                    mention_text=mention_text,
                    matched_name=player["display_name"],
                    confidence=1.0,
                )
        
        # Try fuzzy matching
        best_match = self._fuzzy_match_player(clean_mention)
        
        if best_match and best_match.confidence >= self.confidence_threshold:
            return best_match
        
        logger.debug(f"No player match for: {mention_text}")
        return None
    
    def resolve_team(
        self,
        mention_text: str,
        context: Optional[str] = None
    ) -> Optional[ResolvedEntity]:
        """
        Resolve a team mention to a team_abbr.
        
        Args:
            mention_text: Team name/nickname from extraction
            context: Context around the mention
            
        Returns:
            ResolvedEntity if match found, None otherwise
        """
        if not self._teams_cache:
            self._load_teams_cache()
        
        # Clean the mention text
        clean_mention = self._normalize_text(mention_text)
        
        # Check aliases first
        if clean_mention in self._team_aliases:
            team_abbr = self._team_aliases[clean_mention]
            team = self._teams_cache.get(team_abbr)
            if team:
                return ResolvedEntity(
                    entity_type="team",
                    entity_id=team_abbr,
                    mention_text=mention_text,
                    matched_name=team.get("team_name", team_abbr),
                    confidence=1.0,
                )
        
        # Try exact match
        for team_abbr, team in self._teams_cache.items():
            if self._exact_match_team(clean_mention, team, team_abbr):
                return ResolvedEntity(
                    entity_type="team",
                    entity_id=team_abbr,
                    mention_text=mention_text,
                    matched_name=team.get("team_name", team_abbr),
                    confidence=1.0,
                )
        
        # Try fuzzy matching
        best_match = self._fuzzy_match_team(clean_mention)
        
        if best_match and best_match.confidence >= self.confidence_threshold:
            return best_match
        
        logger.debug(f"No team match for: {mention_text}")
        return None
    
    def resolve_game(
        self,
        mention_text: str,
        context: Optional[str] = None,
        season: Optional[int] = None,
        week: Optional[int] = None
    ) -> Optional[ResolvedEntity]:
        """
        Resolve a game mention to a game_id.
        
        Args:
            mention_text: Game description (e.g., "Chiefs vs Chargers")
            context: Context around the mention
            season: Season year (helps narrow search)
            week: Week number (helps narrow search)
            
        Returns:
            ResolvedEntity if match found, None otherwise
        """
        if not self._games_cache:
            self._load_games_cache(season)
        
        # Extract team names from mention
        teams = self._extract_teams_from_game_mention(mention_text)
        
        if not teams or len(teams) < 2:
            logger.debug(f"Could not extract two teams from game mention: {mention_text}")
            return None
        
        # Try to find matching game
        for game_id, game in self._games_cache.items():
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")
            
            # Check if both teams match (order doesn't matter)
            if (teams[0] in (home_team, away_team) and 
                teams[1] in (home_team, away_team)):
                
                # Apply season/week filters if provided
                if season and game.get("season") != season:
                    continue
                if week and game.get("week") != week:
                    continue
                
                game_desc = f"{away_team} at {home_team}"
                return ResolvedEntity(
                    entity_type="game",
                    entity_id=game_id,
                    mention_text=mention_text,
                    matched_name=game_desc,
                    confidence=0.9,  # Slightly lower for game matches
                )
        
        logger.debug(f"No game match for: {mention_text}")
        return None
    
    def _load_players_cache(self):
        """Load all players from database into cache."""
        logger.info("Loading players cache from database...")
        
        try:
            players = {}
            page_size = 1000
            offset = 0
            
            while True:
                response = (
                    self.client.table("players")
                    .select("player_id, display_name, first_name, last_name, "
                           "short_name, football_name, latest_team, position")
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                
                for row in response.data:
                    players[row["player_id"]] = row
                
                if len(response.data) < page_size:
                    break
                
                offset += page_size
            
            self._players_cache = players
            logger.info(f"Loaded {len(players)} players into cache")
            
        except Exception as e:
            logger.error(f"Failed to load players cache: {e}", exc_info=True)
            self._players_cache = {}
    
    def _load_teams_cache(self):
        """Load all teams from database into cache."""
        logger.info("Loading teams cache from database...")
        
        try:
            response = self.client.table("teams").select("*").execute()
            
            teams = {row["team_abbr"]: row for row in response.data}
            self._teams_cache = teams
            logger.info(f"Loaded {len(teams)} teams into cache")
            
        except Exception as e:
            logger.error(f"Failed to load teams cache: {e}", exc_info=True)
            self._teams_cache = {}
    
    def _load_games_cache(self, season: Optional[int] = None):
        """Load games from database into cache."""
        logger.info(f"Loading games cache from database (season: {season or 'all'})...")
        
        try:
            games = {}
            page_size = 1000
            offset = 0
            
            while True:
                query = self.client.table("games").select(
                    "game_id, season, week, home_team, away_team, "
                    "game_type, gameday"
                )
                
                if season:
                    query = query.eq("season", season)
                
                response = query.range(offset, offset + page_size - 1).execute()
                
                for row in response.data:
                    games[row["game_id"]] = row
                
                if len(response.data) < page_size:
                    break
                
                offset += page_size
            
            self._games_cache = games
            logger.info(f"Loaded {len(games)} games into cache")
            
        except Exception as e:
            logger.error(f"Failed to load games cache: {e}", exc_info=True)
            self._games_cache = {}
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching (lowercase, remove punctuation)."""
        # Convert to lowercase
        text = text.lower()
        # Remove possessives
        text = text.replace("'s", "").replace("'", "")
        # Remove extra whitespace
        text = " ".join(text.split())
        return text.strip()
    
    def _exact_match(self, mention: str, player: Dict) -> bool:
        """Check if mention exactly matches any player name field."""
        fields = [
            player.get("display_name", ""),
            player.get("first_name", ""),
            player.get("last_name", ""),
            player.get("short_name", ""),
            player.get("football_name", ""),
        ]
        
        normalized_fields = [self._normalize_text(f) for f in fields if f]
        
        return mention in normalized_fields
    
    def _exact_match_team(self, mention: str, team: Dict, team_abbr: str) -> bool:
        """Check if mention exactly matches team name or abbreviation."""
        fields = [
            team.get("team_name", ""),
            team.get("team_nick", ""),
            team_abbr,
            team_abbr.lower(),
        ]
        
        normalized_fields = [self._normalize_text(f) for f in fields if f]
        
        return mention in normalized_fields
    
    def _fuzzy_match_player(self, mention: str) -> Optional[ResolvedEntity]:
        """Fuzzy match player mention against cache."""
        # Build list of (player_id, searchable_text) pairs
        choices = []
        for player_id, player in self._players_cache.items():
            # Create searchable strings from multiple name fields
            names = [
                player.get("display_name", ""),
                player.get("last_name", ""),
                f"{player.get('first_name', '')} {player.get('last_name', '')}",
                player.get("short_name", ""),
            ]
            
            for name in names:
                if name:
                    choices.append((player_id, self._normalize_text(name), name))
        
        # Use rapidfuzz to find best match
        result = process.extractOne(
            mention,
            choices,
            scorer=fuzz.token_sort_ratio,
            processor=lambda x: x[1],  # Use normalized name for matching
            score_cutoff=70,  # Minimum score
        )
        
        if result:
            matched_choice, score, _ = result
            player_id, _, original_name = matched_choice
            player = self._players_cache[player_id]
            
            # Convert score (0-100) to confidence (0-1)
            confidence = score / 100.0
            
            logger.debug(f"Fuzzy matched '{mention}' to '{player['display_name']}' "
                        f"(confidence: {confidence:.2f})")
            
            return ResolvedEntity(
                entity_type="player",
                entity_id=player_id,
                mention_text=mention,
                matched_name=player["display_name"],
                confidence=confidence,
            )
        
        return None
    
    def _fuzzy_match_team(self, mention: str) -> Optional[ResolvedEntity]:
        """Fuzzy match team mention against cache."""
        if not mention or len(mention) < 2:
            return None
            
        choices = []
        for team_abbr, team in self._teams_cache.items():
            names = [
                team.get("team_name", ""),
                team.get("team_nick", ""),
                team_abbr,
            ]
            
            for name in names:
                if name and len(str(name)) >= 2:
                    choices.append((team_abbr, self._normalize_text(name), name))
        
        if not choices:
            return None
        
        try:
            result = process.extractOne(
                mention,
                choices,
                scorer=fuzz.token_sort_ratio,
                processor=lambda x: x[1],
                score_cutoff=70,
            )
        except Exception as e:
            logger.debug(f"Fuzzy match failed for '{mention}': {e}")
            return None
        
        if result:
            matched_choice, score, _ = result
            team_abbr, _, original_name = matched_choice
            team = self._teams_cache.get(team_abbr)
            
            if not team:
                return None
            
            confidence = score / 100.0
            
            logger.debug(
                f"Fuzzy matched '{mention}' to '{team.get('team_name', team_abbr)}' "
                f"(confidence: {confidence:.2f})"
            )
            
            return ResolvedEntity(
                entity_type="team",
                entity_id=team_abbr,
                mention_text=mention,
                matched_name=team.get("team_name", team_abbr),
                confidence=confidence,
            )
        
        return None
    
    def _extract_teams_from_game_mention(self, mention: str) -> List[str]:
        """Extract team abbreviations from game mention text."""
        # Look for patterns like "Chiefs vs Chargers" or "KC at LAC"
        teams = []
        
        # Clean up the mention - remove extra info like "Week 5"
        mention = mention.split(",")[0].strip()  # Remove ", Week 5" part
        
        # Try to resolve each word/phrase as a team
        words = mention.split()
        for word in words:
            # Skip common words and numbers
            if word.lower() in ("vs", "at", "versus", "v", "game", "matchup", "week"):
                continue
            
            # Skip numbers
            if word.isdigit():
                continue
            
            # Skip very short words (likely punctuation)
            if len(word) < 2:
                continue
            
            # Try to resolve as team
            try:
                resolved = self.resolve_team(word)
                if resolved:
                    teams.append(resolved.entity_id)
            except Exception as e:
                logger.debug(f"Failed to resolve '{word}' as team: {e}")
                continue
        
        return teams
