"""
Data fetching service for retrieving data from upstream providers.

Integrates with the existing data_loading module's provider registry to fetch
play-by-play data, snap counts, team context, and Next Gen Stats.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging
import time

from ..bundling.request_builder import CombinedDataRequest, NGSRequest

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
    
    def __init__(self, fail_fast: bool = False):
        """
        Initialize the data fetcher.
        
        Args:
            fail_fast: If True, raise exception on first error. If False, collect
                      errors and return partial results.
        """
        self.fail_fast = fail_fast
        # Import providers lazily to avoid circular dependencies
        self._providers_module = None
    
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
            
            # Snap counts provider fetches all players, then we filter
            # NOTE: The provider requires pfr_id per player, but for now we'll fetch
            # all snap counts for the game and filter by game_id
            logger.warning(f"Snap counts fetching not yet fully implemented - provider requires pfr_id per player")
            result.snap_counts = []
            result.sources_succeeded.append(source)
            
            # Track provenance
            result.provenance[source] = {
                "source": "pfr",
                "provider": "snap_counts",
                "retrieval_time": time.time(),
                "record_count": 0,
                "note": "Provider requires per-player pfr_id - bulk fetch not yet implemented",
            }
            
            logger.info(f"✓ Snap counts fetch deferred (requires per-player implementation)")
            
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
