"""
Game Analysis Pipeline

Main orchestration for the complete game analysis workflow.
Coordinates all 9 steps from validation through envelope creation.
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import uuid
from datetime import datetime

from ..contracts.game_package import GamePackageInput, GameInfo
from ..utils.validation import validate_package_with_details, ValidationError
from ..extraction.player_extractor import PlayerExtractor
from ..extraction.relevance_scorer import RelevanceScorer, RelevantPlayer
from ..bundling.request_builder import DataRequestBuilder
from ..fetching.data_fetcher import DataFetcher
from ..fetching.play_fetcher import PlayFetcher
from ..fetching.player_metadata_enricher import PlayerMetadataEnricher
from ..processing.data_normalizer import DataNormalizer
from ..processing.data_merger import DataMerger, MergedData
from ..processing.game_summarizer import GameSummarizer, GameSummaries
from ..processing.envelope_builder import AnalysisEnvelopeBuilder
from ..contracts.analysis_envelope import AnalysisEnvelope


logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for pipeline execution."""
    fetch_data: bool = False  # Whether to fetch from upstream sources
    strict_validation: bool = False  # Treat warnings as errors
    enable_envelope: bool = True  # Create analysis envelope
    correlation_id: Optional[str] = None  # Optional custom correlation ID
    
    # Provider configuration
    provider_timeout: int = 30  # Timeout for data fetching (seconds)
    max_retries: int = 3  # Max retry attempts for failed requests


@dataclass
class PipelineResult:
    """Complete result from pipeline execution."""
    status: str  # "success", "partial", "failed"
    correlation_id: str
    
    # Package data
    game_id: str
    season: int
    week: int
    
    # Validation results
    validation_passed: bool
    validation_warnings: List[str]
    
    # Processing results
    players_extracted: int
    players_selected: int
    data_fetched: bool
    
    # Output data
    merged_data: Optional[MergedData] = None
    game_summaries: Optional[GameSummaries] = None
    analysis_envelope: Optional[AnalysisEnvelope] = None
    
    # Error tracking
    errors: List[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        """Initialize mutable fields."""
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "status": self.status,
            "correlation_id": self.correlation_id,
            "game_info": {
                "game_id": self.game_id,
                "season": self.season,
                "week": self.week,
            },
            "validation": {
                "passed": self.validation_passed,
                "warnings": self.validation_warnings,
            },
            "processing": {
                "players_extracted": self.players_extracted,
                "players_selected": self.players_selected,
                "data_fetched": self.data_fetched,
            },
        }
        
        # Add summaries if available
        if self.game_summaries:
            result["game_summaries"] = self.game_summaries.to_dict()
        
        # Add envelope if available
        if self.analysis_envelope:
            result["analysis_envelope"] = self.analysis_envelope.to_dict()
        
        # Add merged data if available
        if self.merged_data:
            result["enriched_package"] = self.merged_data.to_dict()
        
        # Add errors and warnings if present
        if self.errors:
            result["errors"] = self.errors
        if self.warnings:
            result["warnings"] = self.warnings
        
        return result


class GameAnalysisPipeline:
    """
    Main orchestration pipeline for game analysis.
    
    Coordinates all 10+ steps:
    0. Play fetching (optional - if plays array is empty)
    1. Package validation (structure and data quality)
    2. Player extraction (from play-by-play)
    3. Relevance scoring and selection
    4. Data request building
    5. Data fetching (optional - NGS/snap counts)
    6. Data normalization
    7. Data merging and enrichment
    8. Summary computation (teams and players)
    8.5. Player metadata enrichment (names, positions, teams from database)
    9. Analysis envelope creation
    
    Example:
        pipeline = GameAnalysisPipeline()
        config = PipelineConfig(fetch_data=True, correlation_id="custom-id")
        result = pipeline.process(package, config)
        
        if result.status == "success":
            print(f"Analysis complete: {result.correlation_id}")
            envelope = result.analysis_envelope
    """
    
    def __init__(self):
        """Initialize pipeline with component instances."""
        # Core processing components
        self.play_fetcher = PlayFetcher()  # NEW: Dynamic play fetching
        self.player_metadata_enricher = PlayerMetadataEnricher()  # NEW: Player metadata enrichment
        self.player_extractor = PlayerExtractor()
        self.relevance_scorer = RelevanceScorer()
        self.request_builder = DataRequestBuilder()
        self.data_fetcher = DataFetcher()
        self.data_normalizer = DataNormalizer()
        self.data_merger = DataMerger()
        self.game_summarizer = GameSummarizer()
        self.envelope_builder = AnalysisEnvelopeBuilder()
    
    def process(
        self,
        package: GamePackageInput,
        config: Optional[PipelineConfig] = None
    ) -> PipelineResult:
        """
        Execute complete analysis pipeline.
        
        Args:
            package: Game package to analyze
            config: Pipeline configuration options
            
        Returns:
            PipelineResult with all outputs and status
            
        Raises:
            ValidationError: If package validation fails
        """
        # Use default config if not provided
        if config is None:
            config = PipelineConfig()
        
        # Generate correlation ID for tracking
        correlation_id = self._generate_correlation_id(package, config.correlation_id)
        
        logger.info(f"Starting pipeline for {package.game_id} [{correlation_id}]")
        
        # Initialize result
        result = PipelineResult(
            status="processing",
            correlation_id=correlation_id,
            game_id=package.game_id,
            season=package.season,
            week=package.week,
            validation_passed=False,
            validation_warnings=[],
            players_extracted=0,
            players_selected=0,
            data_fetched=False,
        )
        
        try:
            # Step 0: Fetch plays if needed (NEW STEP!)
            if package.needs_play_fetching():
                logger.info(
                    f"[{correlation_id}] Step 0: Fetching plays from database "
                    f"(empty plays array detected)..."
                )
                try:
                    fetch_result = self.play_fetcher.fetch_plays(
                        season=package.season,
                        week=package.week,
                        game_id=package.game_id
                    )
                    
                    # Replace empty plays array with fetched plays
                    package.plays = fetch_result.plays
                    
                    logger.info(
                        f"[{correlation_id}] ✓ Fetched {fetch_result.total_count} plays "
                        f"in {fetch_result.retrieval_time:.2f}s from {fetch_result.source}"
                    )
                    result.warnings.append(
                        f"Automatically fetched {fetch_result.total_count} plays from database"
                    )
                    
                except Exception as e:
                    error_msg = (
                        f"Failed to fetch plays for {package.game_id}: {e}. "
                        "Please provide plays manually in the request."
                    )
                    logger.error(f"[{correlation_id}] {error_msg}")
                    result.status = "failed"
                    result.errors.append(error_msg)
                    return result
            else:
                logger.info(
                    f"[{correlation_id}] Using {len(package.plays)} provided plays "
                    "(skipping automatic fetch)"
                )
            
            # Step 1: Validate package
            logger.info(f"[{correlation_id}] Step 1: Validating package...")
            validation_result = self._validate_package(package, config.strict_validation)
            result.validation_passed = validation_result.is_valid
            result.validation_warnings = [w.message for w in validation_result.warnings]
            
            if not validation_result.is_valid:
                result.status = "failed"
                result.errors.append(f"Validation failed: {validation_result.get_summary()}")
                logger.error(f"[{correlation_id}] Validation failed")
                return result
            
            logger.info(f"[{correlation_id}] ✓ Validation passed")
            
            # Step 2: Extract players
            logger.info(f"[{correlation_id}] Step 2: Extracting players...")
            all_players = self.player_extractor.extract_players(package.plays)
            result.players_extracted = len(all_players)
            logger.info(f"[{correlation_id}] ✓ Extracted {len(all_players)} players")
            
            # Step 3: Score and select relevant players
            logger.info(f"[{correlation_id}] Step 3: Scoring player relevance...")
            relevant_players = self.relevance_scorer.score_and_select(
                all_players,
                package.plays
            )
            result.players_selected = len(relevant_players)
            logger.info(f"[{correlation_id}] ✓ Selected {len(relevant_players)} relevant players")
            
            # Step 4: Build data request
            logger.info(f"[{correlation_id}] Step 4: Building data request...")
            game_info = GameInfo(
                season=package.season,
                week=package.week,
                game_id=package.game_id
            )
            data_request = self.request_builder.build_request(
                game_info=game_info,
                relevant_players=relevant_players
            )
            logger.info(
                f"[{correlation_id}] ✓ Built request with "
                f"{len(data_request.ngs_requests)} NGS requests"
            )
            
            # Step 5: Fetch data (optional)
            fetched_data = None
            if config.fetch_data:
                logger.info(f"[{correlation_id}] Step 5: Fetching data...")
                try:
                    fetched_data = self.data_fetcher.fetch(data_request)
                    result.data_fetched = True
                    logger.info(f"[{correlation_id}] ✓ Data fetched successfully")
                except Exception as e:
                    logger.warning(f"[{correlation_id}] Data fetch failed: {e}")
                    result.warnings.append(f"Data fetch failed: {str(e)}")
                    # Continue without fetched data
            else:
                logger.info(f"[{correlation_id}] Step 5: Skipping data fetch")
            
            # Step 6: Normalize data (if fetched)
            normalized_data = None
            if fetched_data:
                logger.info(f"[{correlation_id}] Step 6: Normalizing data...")
                normalized_data = self.data_normalizer.normalize(
                    fetched_data,
                    correlation_id=correlation_id
                )
                logger.info(
                    f"[{correlation_id}] ✓ Normalized {normalized_data.records_processed} records"
                )
            else:
                logger.info(f"[{correlation_id}] Step 6: Skipping normalization (no data)")
            
            # Step 7: Merge and enrich data
            merged_data = None
            if normalized_data:
                logger.info(f"[{correlation_id}] Step 7: Merging data...")
                merged_data = self.data_merger.merge(
                    package=package,
                    normalized_data=normalized_data,
                    relevant_players=relevant_players
                )
                result.merged_data = merged_data
                logger.info(
                    f"[{correlation_id}] ✓ Merged data: "
                    f"{merged_data.players_enriched} players enriched"
                )
            else:
                # Create minimal merged data from package plays
                logger.info(f"[{correlation_id}] Step 7: Creating minimal merged data...")
                merged_data = self._create_minimal_merged_data(
                    package,
                    relevant_players
                )
                result.merged_data = merged_data
                logger.info(f"[{correlation_id}] ✓ Created minimal merged data")
            
            # Step 8: Compute summaries
            logger.info(f"[{correlation_id}] Step 8: Computing summaries...")
            game_summaries = self.game_summarizer.summarize(
                merged_data,
                relevant_players
            )
            result.game_summaries = game_summaries
            logger.info(
                f"[{correlation_id}] ✓ Summaries: "
                f"{game_summaries.teams_summarized} teams, "
                f"{game_summaries.players_summarized} players"
            )
            
            # Step 8.5: Enrich player summaries with metadata from nflreadpy
            try:
                logger.info(f"[{correlation_id}] Step 8.5: Enriching player metadata...")
                
                # Collect all player IDs that need metadata
                player_ids = set(game_summaries.player_summaries.keys())
                
                if player_ids:
                    # Fetch metadata from nflreadpy using the game's season
                    player_metadata = self.player_metadata_enricher.fetch_player_metadata(
                        player_ids=player_ids,
                        season=package.season
                    )
                    
                    # Enrich summaries with metadata
                    self.player_metadata_enricher.enrich_player_summaries(
                        player_summaries=game_summaries.player_summaries,
                        metadata=player_metadata
                    )
                    
                    logger.info(
                        f"[{correlation_id}] ✓ Player metadata enriched: "
                        f"{len(player_metadata)}/{len(player_ids)} players found in rosters"
                    )
                else:
                    logger.info(f"[{correlation_id}] Step 8.5: No players to enrich")
                    
            except Exception as e:
                # Don't fail pipeline if metadata enrichment fails - it's optional
                logger.warning(
                    f"[{correlation_id}] Player metadata enrichment failed: {e}. "
                    "Continuing without metadata."
                )
                result.warnings.append(
                    f"Player metadata enrichment failed: {e}"
                )
            
            # Step 9: Create analysis envelope
            if config.enable_envelope:
                logger.info(f"[{correlation_id}] Step 9: Creating analysis envelope...")
                analysis_envelope = self.envelope_builder.build_envelope(
                    merged_data=merged_data,
                    summaries=game_summaries,
                    correlation_id=correlation_id
                )
                result.analysis_envelope = analysis_envelope
                logger.info(f"[{correlation_id}] ✓ Analysis envelope created")
            else:
                logger.info(f"[{correlation_id}] Step 9: Skipping envelope creation")
            
            # Mark as successful
            result.status = "success" if not result.warnings else "partial"
            logger.info(
                f"[{correlation_id}] Pipeline complete: {result.status} "
                f"({len(result.warnings)} warnings)"
            )
            
        except ValidationError as e:
            result.status = "failed"
            result.errors.append(f"Validation error: {str(e)}")
            logger.error(f"[{correlation_id}] Pipeline failed: {e}")
        
        except Exception as e:
            result.status = "failed"
            result.errors.append(f"Unexpected error: {str(e)}")
            logger.error(f"[{correlation_id}] Pipeline failed with unexpected error: {e}")
        
        return result
    
    def _generate_correlation_id(
        self,
        package: GamePackageInput,
        custom_id: Optional[str] = None
    ) -> str:
        """
        Generate correlation ID for request tracking.
        
        Args:
            package: Game package being processed
            custom_id: Optional custom correlation ID
            
        Returns:
            Correlation ID string
        """
        if custom_id:
            return custom_id
        
        if package.correlation_id:
            return package.correlation_id
        
        # Generate from game ID + timestamp + short UUID
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        
        return f"{package.game_id}-{timestamp}-{short_uuid}"
    
    def _validate_package(
        self,
        package: GamePackageInput,
        strict: bool = False
    ) -> Any:
        """
        Validate package with detailed checks.
        
        Args:
            package: Package to validate
            strict: Treat warnings as errors
            
        Returns:
            Validation result
            
        Raises:
            ValidationError: If validation fails
        """
        validation_result = validate_package_with_details(package, strict=strict)
        
        if not validation_result.is_valid:
            raise ValidationError(
                f"Package validation failed for {package.game_id}: "
                f"{validation_result.get_summary()}"
            )
        
        return validation_result
    
    def _create_minimal_merged_data(
        self,
        package: GamePackageInput,
        relevant_players: List[RelevantPlayer]
    ) -> MergedData:
        """
        Create minimal merged data structure from package plays.
        
        Used when data fetching is skipped or fails.
        
        Args:
            package: Game package
            relevant_players: Selected relevant players
            
        Returns:
            Minimal MergedData instance
        """
        # Extract player IDs for player_data dict
        player_ids = {p.player_id for p in relevant_players}
        
        # Convert plays to dict format
        plays_data = [
            {
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
                "safety": play.safety,
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
            }
            for play in package.plays
        ]
        
        return MergedData(
            season=package.season,
            week=package.week,
            game_id=package.game_id,
            plays=plays_data,
            player_data={pid: {"player_id": pid} for pid in player_ids}
        )
