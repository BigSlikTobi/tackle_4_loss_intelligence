"""Entity resolution service for matching extracted entities to database IDs.

Handles fuzzy matching, nicknames, and aliases for players, teams, and games.

This module lives in `src/shared/` so both the fact-level `knowledge_extraction`
module and the article-level `article_knowledge_extraction` module can reuse it
without cross-module imports. `knowledge_extraction` keeps a re-export shim at
`knowledge_extraction/core/resolution/entity_resolver.py` for backwards
compatibility.
"""

import logging
from typing import Dict, List, Optional

from rapidfuzz import fuzz, process

from src.shared.contracts.knowledge import ResolvedEntity
from src.shared.db.connection import get_supabase_client
from src.shared.nlp.team_aliases import TEAM_ALIASES

logger = logging.getLogger(__name__)


_POSITION_MAP: Dict[str, str] = {
    # Quarterback
    "QUARTERBACK": "QB", "QB": "QB",
    # Running Back
    "RUNNING BACK": "RB", "RUNNINGBACK": "RB", "HALFBACK": "RB",
    "HALF BACK": "RB", "RB": "RB", "HB": "RB",
    # Wide Receiver
    "WIDE RECEIVER": "WR", "WIDERECEIVER": "WR", "RECEIVER": "WR", "WR": "WR",
    # Tight End
    "TIGHT END": "TE", "TIGHTEND": "TE", "TE": "TE",
    # Offensive Line
    "OFFENSIVE LINEMAN": "OL", "OFFENSIVE LINE": "OL", "OFFENSIVELINEMAN": "OL",
    "OFFENSIVE TACKLE": "OT", "OFFENSIVETACKLE": "OT",
    "LEFT TACKLE": "OT", "RIGHT TACKLE": "OT",
    "GUARD": "G", "OFFENSIVE GUARD": "G",
    "LEFT GUARD": "G", "RIGHT GUARD": "G",
    "CENTER": "C",
    "OT": "OT", "OG": "G", "OL": "OL", "G": "G", "C": "C",
    # Defensive Line
    "DEFENSIVE LINEMAN": "DL", "DEFENSIVE LINE": "DL", "DEFENSIVELINEMAN": "DL",
    "DEFENSIVE END": "DE", "DEFENSIVEEND": "DE",
    "DEFENSIVE TACKLE": "DT", "DEFENSIVETACKLE": "DT",
    "NOSE TACKLE": "NT", "NOSETACKLE": "NT",
    "EDGE": "EDGE", "EDGE RUSHER": "EDGE",
    "DL": "DL", "DE": "DE", "DT": "DT", "NT": "NT",
    # Linebacker
    "LINEBACKER": "LB", "INSIDE LINEBACKER": "LB",
    "OUTSIDE LINEBACKER": "LB", "MIDDLE LINEBACKER": "LB",
    "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
    # Defensive Back
    "CORNERBACK": "CB", "CORNER BACK": "CB", "CORNER": "CB",
    "SAFETY": "S", "FREE SAFETY": "S", "STRONG SAFETY": "S",
    "DEFENSIVE BACK": "DB",
    "CB": "CB", "S": "S", "FS": "S", "SS": "S", "DB": "DB",
    # Special Teams
    "KICKER": "K", "PLACEKICKER": "K", "PUNTER": "P",
    "LONG SNAPPER": "LS", "LONGSNAPPER": "LS",
    "KICK RETURNER": "KR", "PUNT RETURNER": "PR",
    "K": "K", "P": "P", "LS": "LS", "KR": "KR", "PR": "PR",
}


class EntityResolver:
    """Resolves extracted entity mentions to database IDs.

    Uses fuzzy matching and per-instance caching to efficiently match players,
    teams, and games. Instantiate one resolver per request when used inside a
    stateless Cloud Function (caches are not module-global).
    """

    def __init__(self, confidence_threshold: float = 0.6, client=None):
        """Initialize the resolver.

        ``client`` — optional pre-built Supabase client. Pass a request-scoped
        client in stateless Cloud Function contexts where credentials come
        from the request payload rather than env vars. When omitted, falls
        back to ``get_supabase_client()`` (env-based), preserving the legacy
        behavior used by the fact-level pipeline.
        """
        self.confidence_threshold = confidence_threshold
        self.client = client if client is not None else get_supabase_client()

        self._players_cache: Optional[Dict[str, Dict]] = None
        self._teams_cache: Optional[Dict[str, Dict]] = None
        self._games_cache: Optional[Dict[str, Dict]] = None
        self._team_aliases = TEAM_ALIASES

        logger.info(f"Initialized EntityResolver with threshold={confidence_threshold}")

    def _normalize_position(self, position: str) -> str:
        if not position:
            return ""
        pos = position.upper().strip()
        return _POSITION_MAP.get(pos, pos)

    def _normalize_text(self, text: str) -> str:
        text = text.lower()
        text = text.replace("'s", "").replace("'", "")
        text = " ".join(text.split())
        return text.strip()

    def resolve_player(
        self,
        mention_text: str,
        context: Optional[str] = None,
        position: Optional[str] = None,
        team_abbr: Optional[str] = None,
        team_name: Optional[str] = None,
    ) -> Optional[ResolvedEntity]:
        if not self._players_cache:
            self._load_players_cache()

        logger.debug(
            f"Resolving player: '{mention_text}' with disambiguation: "
            f"position={position}, team_abbr={team_abbr}, team_name={team_name}"
        )

        clean_mention = self._normalize_text(mention_text)
        candidates = []

        for player_id, player in self._players_cache.items():
            if self._exact_match(clean_mention, player):
                candidates.append((player_id, player, 1.0))

        if not candidates:
            fuzzy_match = self._fuzzy_match_player(clean_mention)
            if fuzzy_match and fuzzy_match.confidence >= self.confidence_threshold:
                player = self._players_cache.get(fuzzy_match.entity_id)
                if player:
                    candidates.append((fuzzy_match.entity_id, player, fuzzy_match.confidence))

        logger.debug(f"Found {len(candidates)} initial candidates for '{mention_text}'")

        if candidates and (position or team_abbr or team_name):
            filtered = []
            for player_id, player, confidence in candidates:
                should_keep = True
                reasons: List[str] = []

                if position:
                    player_position_raw = player.get("position", "").strip()
                    if player_position_raw:
                        player_position = self._normalize_position(player_position_raw)
                        provided_position = self._normalize_position(position)
                        if player_position != provided_position:
                            should_keep = False
                            reasons.append(
                                f"position mismatch: player={player_position} "
                                f"(from {player_position_raw}) vs provided={provided_position} "
                                f"(from {position})"
                            )

                if should_keep and (team_abbr or team_name):
                    player_team = (
                        player.get("team_abbr") or player.get("latest_team", "")
                    ).upper().strip()
                    if player_team:
                        if team_abbr:
                            provided_team = team_abbr.upper().strip()
                            if player_team != provided_team:
                                should_keep = False
                                reasons.append(
                                    f"team mismatch: player={player_team} vs provided={provided_team}"
                                )
                        elif team_name:
                            provided_team_lower = team_name.lower().strip()
                            if not self._teams_cache:
                                self._load_teams_cache()
                            matched_team_abbr = None
                            for abbr, team_data in self._teams_cache.items():
                                team_full_name = team_data.get("team_name", "").lower().strip()
                                if (
                                    provided_team_lower in team_full_name
                                    or team_full_name in provided_team_lower
                                ):
                                    matched_team_abbr = abbr.upper()
                                    break
                            if matched_team_abbr and player_team != matched_team_abbr:
                                should_keep = False
                                reasons.append(
                                    f"team mismatch: player={player_team} vs provided={matched_team_abbr}"
                                )

                if should_keep:
                    filtered.append((player_id, player, confidence))
                else:
                    logger.debug(
                        f"Filtered out player {player.get('display_name', player_id)} "
                        f"({', '.join(reasons)})"
                    )

            if filtered:
                candidates = filtered
            else:
                logger.warning(
                    f"No players matched after disambiguation filtering for '{mention_text}' "
                    f"with position={position}, team_abbr={team_abbr}, team_name={team_name}"
                )
                return None

        if candidates:
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
        context: Optional[str] = None,
    ) -> Optional[ResolvedEntity]:
        if not self._teams_cache:
            self._load_teams_cache()

        clean_mention = self._normalize_text(mention_text)

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

        for team_abbr, team in self._teams_cache.items():
            if self._exact_match_team(clean_mention, team, team_abbr):
                return ResolvedEntity(
                    entity_type="team",
                    entity_id=team_abbr,
                    mention_text=mention_text,
                    matched_name=team.get("team_name", team_abbr),
                    confidence=1.0,
                )

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
        week: Optional[int] = None,
    ) -> Optional[ResolvedEntity]:
        if not self._games_cache:
            self._load_games_cache(season)

        teams = self._extract_teams_from_game_mention(mention_text)
        if not teams or len(teams) < 2:
            logger.debug(f"Could not extract two teams from game mention: {mention_text}")
            return None

        for game_id, game in self._games_cache.items():
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")
            if (
                teams[0] in (home_team, away_team)
                and teams[1] in (home_team, away_team)
            ):
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
                    confidence=0.9,
                )

        logger.debug(f"No game match for: {mention_text}")
        return None

    def _load_players_cache(self):
        logger.info("Loading players cache from database...")
        try:
            players = {}
            page_size = 1000
            offset = 0
            while True:
                response = (
                    self.client.table("players")
                    .select(
                        "player_id, display_name, first_name, last_name, "
                        "short_name, football_name, latest_team, position"
                    )
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
        logger.info(f"Loading games cache from database (season: {season or 'all'})...")
        try:
            games = {}
            page_size = 1000
            offset = 0
            while True:
                query = self.client.table("games").select(
                    "game_id, season, week, home_team, away_team, game_type, gameday"
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

    def _exact_match(self, mention: str, player: Dict) -> bool:
        fields = [
            player.get("display_name", ""),
            player.get("first_name", ""),
            player.get("last_name", ""),
            player.get("short_name", ""),
            player.get("football_name", ""),
        ]
        normalized = [self._normalize_text(f) for f in fields if f]
        return mention in normalized

    def _exact_match_team(self, mention: str, team: Dict, team_abbr: str) -> bool:
        fields = [
            team.get("team_name", ""),
            team.get("team_nick", ""),
            team_abbr,
            team_abbr.lower(),
        ]
        normalized = [self._normalize_text(f) for f in fields if f]
        return mention in normalized

    def _fuzzy_match_player(self, mention: str) -> Optional[ResolvedEntity]:
        choices = []
        for player_id, player in self._players_cache.items():
            names = [
                player.get("display_name", ""),
                player.get("last_name", ""),
                f"{player.get('first_name', '')} {player.get('last_name', '')}",
                player.get("short_name", ""),
            ]
            for name in names:
                if name:
                    choices.append((player_id, self._normalize_text(name), name))

        result = process.extractOne(
            mention,
            choices,
            scorer=fuzz.token_sort_ratio,
            processor=lambda x: x[1],
            score_cutoff=int(self.confidence_threshold * 100),
        )
        if result:
            matched_choice, score, _ = result
            player_id, _, _ = matched_choice
            player = self._players_cache[player_id]
            confidence = score / 100.0
            logger.debug(
                f"Fuzzy matched '{mention}' to '{player['display_name']}' "
                f"(confidence: {confidence:.2f})"
            )
            return ResolvedEntity(
                entity_type="player",
                entity_id=player_id,
                mention_text=mention,
                matched_name=player["display_name"],
                confidence=confidence,
            )
        return None

    def _fuzzy_match_team(self, mention: str) -> Optional[ResolvedEntity]:
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
                score_cutoff=int(self.confidence_threshold * 100),
            )
        except Exception as e:
            logger.debug(f"Fuzzy match failed for '{mention}': {e}")
            return None
        if result:
            matched_choice, score, _ = result
            team_abbr, _, _ = matched_choice
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
        teams: List[str] = []
        mention = mention.split(",")[0].strip()
        for word in mention.split():
            if word.lower() in ("vs", "at", "versus", "v", "game", "matchup", "week"):
                continue
            if word.isdigit():
                continue
            if len(word) < 2:
                continue
            try:
                resolved = self.resolve_team(word)
                if resolved:
                    teams.append(resolved.entity_id)
            except Exception as e:
                logger.debug(f"Failed to resolve '{word}' as team: {e}")
                continue
        return teams


__all__ = ["EntityResolver", "ResolvedEntity"]
