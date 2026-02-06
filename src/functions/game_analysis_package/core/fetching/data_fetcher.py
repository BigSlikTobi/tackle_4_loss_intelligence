"""
Data fetching service for retrieving data from upstream providers.

Integrates with the existing data_loading module's provider registry to fetch
play-by-play data, snap counts, team context, and Next Gen Stats.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
import logging
import time

from ..bundling.request_builder import CombinedDataRequest, NGSRequest
from ..utils.player_id_mapper import PlayerIdMapper

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Error occurred during data fetching."""
    def __init__(self, source: str, message: str, original_error: Optional[Exception] = None):
        self.source = source
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{source}] {message}")


@dataclass
class FetchResult:
    """
    Result of fetching data from all requested sources.
    
    Contains raw data from each source along with metadata about the fetch operation.
    """
    # Fetched data
    play_by_play: Optional[List[Dict[str, Any]]] = None
    snap_counts: Optional[List[Dict[str, Any]]] = None
    team_context: Optional[Dict[str, Any]] = None
    ngs_data: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # keyed by stat_type
    
    # Metadata
    fetch_timestamp: Optional[float] = None
    sources_attempted: List[str] = field(default_factory=list)
    sources_succeeded: List[str] = field(default_factory=list)
    sources_failed: List[str] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    # Provenance tracking
    provenance: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "play_by_play": self.play_by_play,
            "snap_counts": self.snap_counts,
            "team_context": self.team_context,
            "ngs_data": self.ngs_data,
            "metadata": {
                "fetch_timestamp": self.fetch_timestamp,
                "sources_attempted": self.sources_attempted,
                "sources_succeeded": self.sources_succeeded,
                "sources_failed": self.sources_failed,
                "errors": self.errors,
            },
            "provenance": self.provenance,
        }


class DataFetcher:
    """
    Fetches data from upstream providers based on CombinedDataRequest.
    
    Uses the existing data_loading module's provider registry to retrieve:
    - Play-by-play data
    - Snap counts
    - Team context (PFR season stats)
    - Next Gen Stats (position-appropriate stats)
    
    Handles errors gracefully and tracks provenance for all fetched data.
    """
    
    def __init__(
        self,
        fail_fast: bool = False,
        player_id_mapper: Optional[PlayerIdMapper] = None,
    ):
        """
        Initialize the data fetcher.
        
        Args:
            fail_fast: If True, raise exception on first error. If False, collect
                      errors and return partial results.
        """
        self.fail_fast = fail_fast
        # Import providers lazily to avoid circular dependencies
        self._providers_module = None
        self._snap_counts_cache: Dict[int, List[Dict[str, Any]]] = {}
        self._player_id_mapper = player_id_mapper or PlayerIdMapper()
    
    def _get_provider(self, name: str, **options: Any) -> Any:
        """Lazy import and access to data_loading providers."""
        if self._providers_module is None:
            # Import at runtime to avoid circular dependency
            from src.functions.data_loading.core.providers import get_provider
            self._providers_module = get_provider
        return self._providers_module(name, **options)
    
    def fetch(self, request: CombinedDataRequest) -> FetchResult:
        """
        Fetch all requested data from upstream sources.
        
        Args:
            request: Combined data request specifying what to fetch
            
        Returns:
            FetchResult with fetched data and metadata
            
        Raises:
            FetchError: If fail_fast=True and any fetch fails
        """
        logger.info(f"Fetching data for game {request.game_id} (season {request.season}, week {request.week})")
        
        result = FetchResult(fetch_timestamp=time.time())
        
        # Fetch play-by-play data
        if request.include_play_by_play:
            self._fetch_play_by_play(request, result)
        
        # Fetch snap counts
        if request.include_snap_counts:
            self._fetch_snap_counts(request, result)
        
        # Fetch team context (PFR season stats)
        if request.include_team_context:
            self._fetch_team_context(request, result)
        
        # Fetch NGS data for each stat type
        for ngs_request in request.ngs_requests:
            self._fetch_ngs_data(ngs_request, result)
        
        # Log summary
        logger.info(f"Fetch complete: {len(result.sources_succeeded)}/{len(result.sources_attempted)} sources succeeded")
        if result.sources_failed:
            logger.warning(f"Failed sources: {', '.join(result.sources_failed)}")
        
        return result
    
    def _fetch_play_by_play(self, request: CombinedDataRequest, result: FetchResult) -> None:
        """Fetch play-by-play data for the game."""
        source = "pbp"
        result.sources_attempted.append(source)
        
        try:
            logger.debug(f"Fetching play-by-play data for {request.game_id}")
            provider = self._get_provider("pbp")
            
            # Fetch play-by-play data
            data = provider.get(
                season=request.season,
                week=request.week,
                game_id=request.game_id,
                output="dict"
            )
            
            result.play_by_play = data
            result.sources_succeeded.append(source)
            
            # Track provenance
            result.provenance[source] = {
                "source": "nfl_data_py",
                "provider": "pbp",
                "retrieval_time": time.time(),
                "record_count": len(data) if data else 0,
            }
            
            if data:
                logger.info(f"✓ Fetched {len(data)} play-by-play records")
            else:
                logger.warning(f"✓ No play-by-play records found for {request.game_id} (game may not exist in dataset)")
            
        except Exception as e:
            self._handle_fetch_error(source, str(e), e, result)
    
    def _fetch_snap_counts(self, request: CombinedDataRequest, result: FetchResult) -> None:
        """Fetch snap count data for the game."""
        source = "snap_counts"
        result.sources_attempted.append(source)
        
        try:
            logger.debug(f"Fetching snap counts for {request.game_id}")

            snap_records = self._load_snap_counts(request.season)
            filtered = self._filter_snap_counts_for_game(snap_records, request)

            result.snap_counts = filtered
            result.sources_succeeded.append(source)

            record_count = len(filtered)
            result.provenance[source] = {
                "source": "nflreadpy",
                "provider": "snap_counts",
                "retrieval_time": time.time(),
                "record_count": record_count,
                "season": request.season,
                "week": request.week,
            }

            if record_count:
                logger.info(f"✓ Fetched snap counts for {record_count} players")
            else:
                logger.warning(
                    "✓ Snap counts fetched but no records matched %s (season=%s, week=%s)",
                    request.game_id,
                    request.season,
                    request.week
                )
            
        except ImportError as e:
            self._handle_fetch_error(
                source,
                "nflreadpy is required for snap count fetching. Install with 'pip install nflreadpy'.",
                e,
                result
            )

        except Exception as e:
            self._handle_fetch_error(source, str(e), e, result)
    
    def _fetch_team_context(self, request: CombinedDataRequest, result: FetchResult) -> None:
        """Fetch team context data (season stats) for both teams."""
        source = "team_context"
        result.sources_attempted.append(source)
        
        try:
            logger.debug(f"Fetching team context for {request.home_team} vs {request.away_team}")
            
            # PFR provider requires pfr_id per player, not suitable for team context
            # For now, we'll defer this to a future implementation
            logger.warning(f"Team context fetching not yet implemented - requires different provider")
            result.team_context = {}
            result.sources_succeeded.append(source)
            
            # Track provenance
            result.provenance[source] = {
                "source": "pfr",
                "provider": "pfr",
                "retrieval_time": time.time(),
                "record_count": 0,
                "note": "Provider requires per-player pfr_id - team stats not yet implemented",
            }
            
            logger.info(f"✓ Team context fetch deferred (requires different provider)")
            
        except Exception as e:
            self._handle_fetch_error(source, str(e), e, result)
    
    def _fetch_ngs_data(self, ngs_request: NGSRequest, result: FetchResult) -> None:
        """Fetch Next Gen Stats data for specific players and stat type."""
        source = f"ngs_{ngs_request.stat_type}"
        result.sources_attempted.append(source)
        
        try:
            logger.debug(f"Fetching NGS {ngs_request.stat_type} data for {len(ngs_request.player_ids)} players")
            provider = self._get_provider("ngs", stat_type=ngs_request.stat_type)
            
            # NGS provider fetches all players for season/week, then filters by player_id
            # Fetch for each player individually
            all_data = []
            for player_id in ngs_request.player_ids:
                try:
                    player_data = provider.get(
                        season=ngs_request.season,
                        week=ngs_request.week,
                        player_id=player_id,
                        output="dict"
                    )
                    if player_data:
                        all_data.extend(player_data if isinstance(player_data, list) else [player_data])
                except Exception as player_error:
                    logger.debug(f"  No {ngs_request.stat_type} data for player {player_id}: {player_error}")
                    continue
            
            # Store by stat type
            result.ngs_data[ngs_request.stat_type] = all_data
            result.sources_succeeded.append(source)
            
            # Track provenance
            result.provenance[source] = {
                "source": "ngs",
                "provider": "ngs",
                "stat_type": ngs_request.stat_type,
                "retrieval_time": time.time(),
                "record_count": len(all_data),
                "requested_players": len(ngs_request.player_ids),
            }
            
            logger.info(f"✓ Fetched {len(all_data)} NGS {ngs_request.stat_type} records")
            
        except Exception as e:
            self._handle_fetch_error(source, str(e), e, result)
    
    def _handle_fetch_error(
        self, 
        source: str, 
        message: str, 
        error: Exception, 
        result: FetchResult
    ) -> None:
        """Handle a fetch error, either raising or recording it."""
        logger.error(f"✗ Failed to fetch {source}: {message}")
        
        result.sources_failed.append(source)
        result.errors.append({
            "source": source,
            "message": message,
            "error_type": type(error).__name__,
        })
        
        if self.fail_fast:
            raise FetchError(source, message, error)

    def _load_snap_counts(self, season: int) -> List[Dict[str, Any]]:
        """Load and cache snap counts for a season from nflreadpy."""
        if season in self._snap_counts_cache:
            return self._snap_counts_cache[season]

        from nflreadpy import load_snap_counts  # Lazy import

        raw_data = load_snap_counts(seasons=[season])
        records = self._convert_generic_to_records(raw_data)
        self._snap_counts_cache[season] = records
        logger.debug(
            "Cached %d snap count records for season %s",
            len(records),
            season
        )
        return records

    def _filter_snap_counts_for_game(
        self,
        snap_records: List[Dict[str, Any]],
        request: CombinedDataRequest
    ) -> List[Dict[str, Any]]:
        """Filter cached snap counts to match the requested game and players."""
        game_records: List[Dict[str, Any]] = []
        target_players: Set[str] = set()
        for pid in request.player_ids:
            if not pid:
                continue
            normalized = self._normalize_player_id(str(pid))
            if normalized:
                target_players.add(normalized)
            target_players.add(str(pid))

        for record in snap_records:
            if not self._is_same_game(record, request):
                continue

            player_id = self._resolve_snap_player_id(record, request.season)
            if not player_id:
                continue

            normalized_player_id = self._normalize_player_id(player_id) or player_id

            if target_players and normalized_player_id not in target_players:
                continue

            payload = self._build_snap_payload(record, normalized_player_id)
            game_records.append(payload)

        return game_records

    def _convert_generic_to_records(
        self,
        raw_data: Any
    ) -> List[Dict[str, Any]]:
        """Convert nflreadpy structures (Polars/Pandas/list) into dict records."""
        if raw_data is None:
            return []

        # Polars DataFrame support
        try:
            import polars as pl  # type: ignore
            if isinstance(raw_data, pl.DataFrame):  # pragma: no branch - depends on env
                return [
                    dict(zip(raw_data.columns, row))
                    for row in raw_data.iter_rows()
                ]
        except ImportError:  # pragma: no cover - polars optional
            pass

        # Prefer to_pandas when available (works for Polars/Pandas hybrid objects)
        if hasattr(raw_data, "to_pandas"):
            df = raw_data.to_pandas()
            return df.to_dict(orient="records")  # type: ignore[no-any-return]

        # Native pandas DataFrame
        try:
            import pandas as pd  # type: ignore
            if isinstance(raw_data, pd.DataFrame):
                return raw_data.to_dict(orient="records")
        except ImportError:  # pragma: no cover - pandas optional
            pass

        if isinstance(raw_data, list):
            return [dict(item) for item in raw_data if isinstance(item, dict)]

        if isinstance(raw_data, dict):
            return [dict(raw_data)]

        raise TypeError(
            f"Unsupported snap count data type: {type(raw_data)}"
        )

    def _is_same_game(
        self,
        record: Dict[str, Any],
        request: CombinedDataRequest
    ) -> bool:
        """Determine if a snap count record belongs to the requested game."""
        season = self._coerce_int(record.get("season"))
        if season is not None and season != request.season:
            return False

        week = self._coerce_int(record.get("week"))
        if week is not None and week != request.week:
            return False

        game_id = self._clean_str(record.get("game_id"))
        if game_id:
            return game_id == request.game_id

        pfr_game_id = self._clean_str(record.get("pfr_game_id"))
        if pfr_game_id:
            return pfr_game_id == request.game_id

        team = self._clean_str(record.get("team"))
        opponent = self._clean_str(record.get("opponent") or record.get("opp"))
        if team and opponent and request.home_team and request.away_team:
            return {team, opponent} == {request.home_team, request.away_team}

        return False

    def _resolve_snap_player_id(self, record: Dict[str, Any], season: int) -> Optional[str]:
        """Resolve the NFL GSIS player ID from a snap count record."""
        candidate_fields = (
            "gsis_id",
            "player_id",
            "gsis",
            "nfl_id",
        )
        for field in candidate_fields:
            value = record.get(field)
            if value:
                text = str(value).strip()
                normalized = self._player_id_mapper.normalize_to_gsis(text, season=season)
                if normalized:
                    return normalized

        pfr_candidate = record.get("pfr_player_id") or record.get("pfr_id")
        if pfr_candidate:
            pfr_id = self._clean_str(pfr_candidate)
            if pfr_id:
                mapped = self._player_id_mapper.resolve_gsis_from_pfr(pfr_id, season=season)
                if mapped:
                    return mapped
        return None

    def _build_snap_payload(
        self,
        record: Dict[str, Any],
        player_id: str
    ) -> Dict[str, Any]:
        """Build a normalized snap count payload for downstream consumers."""
        offensive_snaps = self._coerce_int(
            record.get("offense_snaps") or record.get("offensive_snaps")
        )
        defensive_snaps = self._coerce_int(record.get("defense_snaps"))
        special_snaps = self._coerce_int(
            record.get("st_snaps") or record.get("special_teams_snaps")
        )

        offensive_pct = self._coerce_float(
            record.get("offense_pct") or record.get("offensive_pct")
        )
        defensive_pct = self._coerce_float(record.get("defense_pct"))
        special_pct = self._coerce_float(
            record.get("st_pct") or record.get("special_teams_pct")
        )

        total_snaps = self._coerce_int(record.get("total_snaps") or record.get("snaps"))
        if total_snaps is None:
            component_values = [
                value for value in (offensive_snaps, defensive_snaps, special_snaps)
                if value is not None
            ]
            if component_values:
                total_snaps = int(sum(component_values))

        snap_pct = self._coerce_float(record.get("snap_pct"))
        if snap_pct is None:
            for candidate in (offensive_pct, defensive_pct, special_pct):
                if candidate is not None:
                    snap_pct = candidate
                    break

        payload = {
            "player_id": player_id,
            "player_name": record.get("player") or record.get("player_name"),
            "game_id": self._clean_str(record.get("game_id") or record.get("pfr_game_id")),
            "team": self._clean_str(record.get("team")),
            "opponent": self._clean_str(record.get("opponent") or record.get("opp")),
            "season": self._coerce_int(record.get("season")),
            "week": self._coerce_int(record.get("week")),
            "snaps": total_snaps,
            "snap_pct": snap_pct,
            "offensive_snaps": offensive_snaps,
            "offensive_pct": offensive_pct,
            "defensive_snaps": defensive_snaps,
            "defensive_pct": defensive_pct,
            "special_teams_snaps": special_snaps,
            "special_teams_pct": special_pct,
            "pfr_player_id": self._clean_str(record.get("pfr_player_id") or record.get("pfr_id")),
        }

        return payload

    # Mapping logic is centralized in PlayerIdMapper to keep behavior consistent
    # across fetch + normalization stages.

    @staticmethod
    def _normalize_player_id(value: str) -> Optional[str]:
        if not value:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned.startswith("00-") and len(cleaned) == 10:
            return cleaned
        if cleaned.startswith("00") and len(cleaned) == 9 and cleaned[2:].isdigit():
            return f"00-{cleaned[2:]}"
        digits = ''.join(ch for ch in cleaned if ch.isdigit())
        if len(digits) == 7:
            return f"00-{digits}"
        if len(digits) == 8:
            return f"00-{digits[-7:]}"
        return cleaned

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return None
        if converted != converted:  # NaN check
            return None
        return int(round(converted))

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, float):
            if value != value:  # NaN
                return None
            return value
        if isinstance(value, int):
            return float(value)
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return None
        if converted != converted:  # NaN
            return None
        return converted

    @staticmethod
    def _clean_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
