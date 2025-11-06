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
    rank: Optional[int] = None  # Importance ranking (1=main, 2=secondary, 3+=minor)
    
    # Player-specific disambiguation fields (passed through from extraction)
    position: Optional[str] = None  # QB, RB, WR, etc.
    team_abbr: Optional[str] = None  # BUF, KC, SF, etc.
    team_name: Optional[str] = None  # Bills, Chiefs, 49ers, etc.


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
    
    def _normalize_position(self, position: str) -> str:
        """
        Normalize position strings to standard abbreviations.
        
        Maps both full names and variations to standard NFL position codes.
        
        Args:
            position: Position string from LLM (e.g., "Defensive Tackle", "DT", "defensive tackle")
            
        Returns:
            Normalized position abbreviation (e.g., "DT")
        """
        if not position:
            return ""
        
        # Convert to uppercase and strip whitespace
        pos = position.upper().strip()
        
        # Position mapping dictionary
        position_map = {
            # Quarterback
            "QUARTERBACK": "QB",
            "QB": "QB",
            
            # Running Back
            "RUNNING BACK": "RB",
            "RUNNINGBACK": "RB",
            "HALFBACK": "RB",
            "HALF BACK": "RB",
            "RB": "RB",
            "HB": "RB",
            
            # Wide Receiver
            "WIDE RECEIVER": "WR",
            "WIDERECEIVER": "WR",
            "RECEIVER": "WR",
            "WR": "WR",
            
            # Tight End
            "TIGHT END": "TE",
            "TIGHTEND": "TE",
            "TE": "TE",
            
            # Offensive Line
            "OFFENSIVE LINEMAN": "OL",
            "OFFENSIVE LINE": "OL",
            "OFFENSIVELINEMAN": "OL",
            "OFFENSIVE TACKLE": "OT",
            "OFFENSIVETACKLE": "OT",
            "LEFT TACKLE": "OT",
            "RIGHT TACKLE": "OT",
            "TACKLE": "OT",
            "GUARD": "G",
            "OFFENSIVE GUARD": "G",
            "LEFT GUARD": "G",
            "RIGHT GUARD": "G",
            "CENTER": "C",
            "OT": "OT",
            "OG": "G",
            "OL": "OL",
            "G": "G",
            "C": "C",
            
            # Defensive Line
            "DEFENSIVE LINEMAN": "DL",
            "DEFENSIVE LINE": "DL",
            "DEFENSIVELINEMAN": "DL",
            "DEFENSIVE END": "DE",
            "DEFENSIVEEND": "DE",
            "DEFENSIVE TACKLE": "DT",
            "DEFENSIVETACKLE": "DT",
            "NOSE TACKLE": "NT",
            "NOSETACKLE": "NT",
            "EDGE": "EDGE",
            "EDGE RUSHER": "EDGE",
            "DL": "DL",
            "DE": "DE",
            "DT": "DT",
            "NT": "NT",
            
            # Linebacker
            "LINEBACKER": "LB",
            "INSIDE LINEBACKER": "LB",
            "OUTSIDE LINEBACKER": "LB",
            "MIDDLE LINEBACKER": "LB",
            "LB": "LB",
            "ILB": "LB",
            "OLB": "LB",
            "MLB": "LB",
            
            # Defensive Back
            "CORNERBACK": "CB",
            "CORNER BACK": "CB",
            "CORNER": "CB",
            "SAFETY": "S",
            "FREE SAFETY": "S",
            "STRONG SAFETY": "S",
            "DEFENSIVE BACK": "DB",
            "CB": "CB",
            "S": "S",
            "FS": "S",
            "SS": "S",
            "DB": "DB",
            
            # Special Teams
            "KICKER": "K",
            "PLACEKICKER": "K",
            "PUNTER": "P",
            "LONG SNAPPER": "LS",
            "LONGSNAPPER": "LS",
            "KICK RETURNER": "KR",
            "PUNT RETURNER": "PR",
            "K": "K",
            "P": "P",
            "LS": "LS",
            "KR": "KR",
            "PR": "PR",
        }
        
        # Return mapped position or original if not found
        return position_map.get(pos, pos)
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching (lowercase, remove punctuation)."""
        # Convert to lowercase
        text = text.lower()
        # Remove possessives
        text = text.replace("'s", "").replace("'", "")
        # Remove extra whitespace
        text = " ".join(text.split())
        return text.strip()
    
    def resolve_player(
        self,
        mention_text: str,
        context: Optional[str] = None,
        position: Optional[str] = None,
        team_abbr: Optional[str] = None,
        team_name: Optional[str] = None
    ) -> Optional[ResolvedEntity]:
        """
        Resolve a player mention to a player_id.
        
        Args:
            mention_text: Player name/nickname from extraction
            context: Context around the mention (helps with disambiguation)
            position: Player position if known (QB, RB, etc.) - used for disambiguation
            team_abbr: Team abbreviation if known (BUF, KC, etc.) - used for disambiguation
            team_name: Team name if known (Bills, Chiefs, etc.) - used for disambiguation
            
        Returns:
            ResolvedEntity if match found, None otherwise
        """
        if not self._players_cache:
            self._load_players_cache()
        
        # Log what we're trying to resolve
        logger.debug(
            f"Resolving player: '{mention_text}' with disambiguation: "
            f"position={position}, team_abbr={team_abbr}, team_name={team_name}"
        )
        
        # Clean the mention text
        clean_mention = self._normalize_text(mention_text)
        
        # Build list of candidate matches
        candidates = []
        
        # Try exact match first (case-insensitive)
        for player_id, player in self._players_cache.items():
            if self._exact_match(clean_mention, player):
                candidates.append((player_id, player, 1.0))
        
        # If no exact matches, try fuzzy matching
        if not candidates:
            fuzzy_match = self._fuzzy_match_player(clean_mention)
            if fuzzy_match and fuzzy_match.confidence >= self.confidence_threshold:
                # Get player data from cache
                player = self._players_cache.get(fuzzy_match.entity_id)
                if player:
                    candidates.append((fuzzy_match.entity_id, player, fuzzy_match.confidence))
        
        logger.debug(f"Found {len(candidates)} initial candidates for '{mention_text}'")
        
        # If we have disambiguation info (position or team), filter candidates
        # BUT: Only filter if BOTH extracted AND database have the field populated
        if candidates and (position or team_abbr or team_name):
            filtered_candidates = []
            
            for player_id, player, confidence in candidates:
                should_keep = True
                mismatch_reasons = []
                
                # Check position match - ONLY if BOTH provided AND player has position in DB
                if position:
                    player_position_raw = player.get("position", "").strip()
                    
                    # Only filter if player has position data in DB
                    if player_position_raw:
                        # Normalize both positions to standard abbreviations
                        player_position = self._normalize_position(player_position_raw)
                        provided_position = self._normalize_position(position)
                        
                        if player_position != provided_position:
                            should_keep = False
                            mismatch_reasons.append(f"position mismatch: player={player_position} (from {player_position_raw}) vs provided={provided_position} (from {position})")
                    else:
                        # Player has no position in database - can't validate, so allow it
                        logger.debug(f"Player {player.get('display_name')} has no position in DB, skipping position check")
                
                # Check team match - ONLY if BOTH provided AND player has team in DB
                if should_keep and (team_abbr or team_name):
                    # Try both 'team_abbr' and 'latest_team' fields
                    player_team = (player.get("team_abbr") or player.get("latest_team", "")).upper().strip()
                    
                    # Only filter if player has team data in DB
                    if player_team:
                        if team_abbr:
                            provided_team = team_abbr.upper().strip()
                            if player_team != provided_team:
                                should_keep = False
                                mismatch_reasons.append(f"team mismatch: player={player_team} vs provided={provided_team}")
                        
                        elif team_name:
                            # Try to resolve team name to abbreviation
                            provided_team_lower = team_name.lower().strip()
                            if not self._teams_cache:
                                self._load_teams_cache()
                            
                            # Find matching team abbreviation
                            matched_team_abbr = None
                            for abbr, team_data in self._teams_cache.items():
                                team_full_name = team_data.get("team_name", "").lower().strip()
                                if provided_team_lower in team_full_name or team_full_name in provided_team_lower:
                                    matched_team_abbr = abbr.upper()
                                    break
                            
                            if matched_team_abbr:
                                if player_team != matched_team_abbr:
                                    should_keep = False
                                    mismatch_reasons.append(f"team mismatch: player={player_team} vs provided={matched_team_abbr}")
                            else:
                                logger.debug(f"Could not resolve team name '{team_name}' to abbreviation")
                    else:
                        # Player has no team in database - can't validate, so allow it
                        logger.debug(f"Player {player.get('display_name')} has no team in DB, skipping team check")
                
                # Keep or filter this candidate
                if should_keep:
                    filtered_candidates.append((player_id, player, confidence))
                else:
                    logger.debug(
                        f"Filtered out player {player.get('display_name', player_id)} "
                        f"({', '.join(mismatch_reasons)})"
                    )
            
            # Update candidates with filtered list
            if filtered_candidates:
                candidates = filtered_candidates
                logger.debug(f"Kept {len(filtered_candidates)} candidates after disambiguation filtering")
            else:
                logger.warning(
                    f"No players matched after disambiguation filtering for '{mention_text}' "
                    f"with position={position}, team_abbr={team_abbr}, team_name={team_name}"
                )
                return None
        
        # Return the best candidate
        if candidates:
            # Sort by confidence (highest first)
            candidates.sort(key=lambda x: x[2], reverse=True)
            player_id, player, confidence = candidates[0]
            
            return ResolvedEntity(
                entity_type="player",
                entity_id=player_id,
                mention_text=mention_text,
                matched_name=player["display_name"],
                confidence=confidence,
            )
        
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
