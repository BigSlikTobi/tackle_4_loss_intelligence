#!/usr/bin/env python3
"""
Game Analysis CLI Tool

Analyzes game packages and produces enriched analysis packages with LLM-ready envelopes.
Validates input, extracts relevant players, and creates comprehensive game analysis.

Usage:
    python analyze_game_cli.py --request path/to/game_package.json [options]

Examples:
    # Basic analysis with pretty output
    python analyze_game_cli.py --request ../test_requests/sample_game.json --pretty
    
    # Validation only (dry-run)
    python analyze_game_cli.py --request ../test_requests/sample_game.json --dry-run
    
    # With verbose logging
    python analyze_game_cli.py --request ../test_requests/sample_game.json --verbose
    
    # Save output to file
    python analyze_game_cli.py --request ../test_requests/sample_game.json --output result.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Dict, Any, Optional
from pathlib import Path

# Add project root to path (go up 4 levels: scripts -> game_analysis_package -> functions -> src -> project_root)
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

# Try to load shared utilities
try:
    from src.shared.utils.env import load_env
    from src.shared.utils.logging import setup_logging
    load_env()
    setup_logging()
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

from src.functions.game_analysis_package.core.contracts.game_package import (
    validate_game_package,
    ValidationError
)
from src.functions.game_analysis_package.core.utils.validation import (
    PackageValidator,
    validate_package_with_details
)
from src.functions.game_analysis_package.core.extraction.player_extractor import (
    PlayerExtractor
)
from src.functions.game_analysis_package.core.extraction.relevance_scorer import (
    RelevanceScorer
)
from src.functions.game_analysis_package.core.bundling.request_builder import (
    DataRequestBuilder
)
from src.functions.game_analysis_package.core.fetching import (
    DataFetcher
)
from src.functions.game_analysis_package.core.processing import (
    DataNormalizer,
    DataMerger,
    GameSummarizer,
    AnalysisEnvelopeBuilder
)
from src.functions.game_analysis_package.core.pipeline import (
    GameAnalysisPipeline,
    PipelineConfig
)

logger = logging.getLogger(__name__)


def load_game_package(file_path: str) -> Dict[str, Any]:
    """
    Load game package from JSON file.
    
    Args:
        file_path: Path to JSON file
        
    Returns:
        Parsed JSON data
        
    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Game package file not found: {file_path}")
    
    logger.info(f"Loading game package from {file_path}")
    
    with open(path, 'r') as f:
        data = json.load(f)
    
    return data


def analyze_game_package(
    data: Dict[str, Any],
    dry_run: bool = False,
    strict: bool = False,
    fetch_data: bool = False
) -> Dict[str, Any]:
    """
    Analyze a game package and produce enriched output.
    
    Args:
        data: Game package data
        dry_run: If True, only validate without full processing
        strict: If True, treat warnings as errors
        fetch_data: If True, fetch data from upstream providers
        
    Returns:
        Analysis results
    """
    # Step 1: Basic validation (structure and contracts)
    logger.info("Step 1a: Validating package structure...")
    try:
        package = validate_game_package(data)
        logger.info(
            f"✓ Package structure valid for {package.game_id} "
            f"({package.season} Week {package.week}) "
            f"with {len(package.plays)} plays"
        )
    except ValidationError as e:
        logger.error(f"✗ Structural validation failed: {e}")
        raise
    
    # Step 1b: Detailed validation (data quality and consistency)
    logger.info("Step 1b: Performing detailed validation...")
    validation_result = validate_package_with_details(package, strict=strict)
    
    if not validation_result.is_valid:
        logger.error(f"✗ Detailed validation failed: {validation_result.get_summary()}")
        raise ValidationError(
            f"Package validation failed for {package.game_id}: "
            f"{len(validation_result.errors)} error(s) found"
        )
    
    logger.info(f"✓ {validation_result.get_summary()}")
    
    if dry_run:
        logger.info("Dry-run mode: validation complete, skipping analysis")
        return {
            "status": "valid",
            "game_id": package.game_id,
            "season": package.season,
            "week": package.week,
            "validation": validation_result.to_dict()
        }
    
    # Step 2: Extract players
    logger.info("Step 2: Extracting players from plays...")
    extractor = PlayerExtractor()
    player_ids = extractor.extract_players(package.plays)
    logger.info(f"✓ Extracted {len(player_ids)} unique players")
    
    # Step 3: Score and select relevant players
    logger.info("Step 3: Scoring and selecting relevant players...")
    scorer = RelevanceScorer()
    relevant_players = scorer.score_and_select(
        player_ids=player_ids,
        plays=package.plays,
        home_team=package.get_game_info().home_team,
        away_team=package.get_game_info().away_team
    )
    logger.info(f"✓ Selected {len(relevant_players)} relevant players")
    
    # Log top players by relevance score
    top_players = sorted(relevant_players, key=lambda p: p.relevance_score, reverse=True)[:5]
    logger.info("  Top 5 players by relevance:")
    for player in top_players:
        logger.info(f"    Player {player.player_id}: score={player.relevance_score:.2f}, "
                   f"plays={player.impact_signals.play_frequency}, "
                   f"touches={player.impact_signals.touches}, "
                   f"yards={player.impact_signals.yards}")
    
    # Step 4: Build data request
    logger.info("Step 4: Building data request...")
    
    builder = DataRequestBuilder()
    request = builder.build_request(
        game_info=package.get_game_info(),
        relevant_players=relevant_players
    )
    logger.info(
        f"✓ Built request with {len(request.ngs_requests)} NGS requests "
        f"for {len(request.player_ids)} players"
    )
    
    # Step 5: Fetch data (optional)
    fetch_result = None
    if fetch_data:
        logger.info("Step 5: Fetching data from upstream providers...")
        fetcher = DataFetcher(fail_fast=False)
        fetch_result = fetcher.fetch(request)
        logger.info(
            f"✓ Fetched data: {len(fetch_result.sources_succeeded)}/{len(fetch_result.sources_attempted)} sources succeeded"
        )
        if fetch_result.sources_failed:
            logger.warning(f"  Failed sources: {', '.join(fetch_result.sources_failed)}")
    else:
        logger.info("Step 5: Skipping data fetch (use --fetch to enable)")
    
    # Step 6: Normalize data (if fetched)
    normalized_data = None
    if fetch_result:
        logger.info("Step 6: Normalizing fetched data...")
        normalizer = DataNormalizer()
        normalized_data = normalizer.normalize(fetch_result)
        logger.info(
            f"✓ Normalized {sum(normalized_data.records_processed.values())} records, "
            f"fixed {len(normalized_data.issues_found)} issues"
        )
    else:
        logger.info("Step 6: Skipping data normalization (no data fetched)")
    
    # Step 7: Merge data into enriched package (if normalized)
    merged_data = None
    if normalized_data:
        logger.info("Step 7: Merging data into enriched package...")
        merger = DataMerger()
        merged_data = merger.merge(package, normalized_data)
        logger.info(
            f"✓ Merged data: {merged_data.players_enriched} players enriched, "
            f"{merged_data.teams_enriched} teams enriched"
        )
    else:
        logger.info("Step 7: Skipping data merge (no normalized data)")
    
    # Step 8: Compute game summaries
    game_summaries = None
    if merged_data:
        logger.info("Step 8: Computing team and player summaries...")
        summarizer = GameSummarizer()
        game_summaries = summarizer.summarize(merged_data, relevant_players)
        logger.info(
            f"✓ Computed summaries: {game_summaries.teams_summarized} teams, "
            f"{game_summaries.players_summarized} players"
        )
    else:
        # Create summaries from plays even without merged data
        logger.info("Step 8: Computing summaries from play data only...")
        summarizer = GameSummarizer()
        # Create minimal merged data structure for summarization
        from src.functions.game_analysis_package.core.processing.data_merger import MergedData
        minimal_merged = MergedData(
            season=package.season,
            week=package.week,
            game_id=package.game_id,
            plays=[
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
                    "forced_fumble_player_id": play.forced_fumble_player_id,
                    "fumble_recovery_player_id": play.fumble_recovery_player_id,
                }
                for play in package.plays
            ],
            player_data={pid: {"player_id": pid} for pid in player_ids}
        )
        game_summaries = summarizer.summarize(minimal_merged, relevant_players)
        logger.info(
            f"✓ Computed summaries: {game_summaries.teams_summarized} teams, "
            f"{game_summaries.players_summarized} players"
        )
        # Use minimal_merged for envelope if no full merged data
        if not merged_data:
            merged_data = minimal_merged
    
    # Step 9: Create analysis envelope
    analysis_envelope = None
    if game_summaries and merged_data:
        logger.info("Step 9: Creating analysis envelope...")
        envelope_builder = AnalysisEnvelopeBuilder()
        correlation_id = package.correlation_id or f"{package.game_id}-cli"
        analysis_envelope = envelope_builder.build_envelope(
            merged_data=merged_data,
            summaries=game_summaries,
            correlation_id=correlation_id
        )
        logger.info("✓ Analysis envelope created")
    else:
        logger.info("Step 9: Skipping envelope creation (no summaries)")
    
    # Build result structure
    result = {
        "status": "analyzed",
        "correlation_id": package.correlation_id or f"{package.game_id}-cli",
        "game_info": {
            "game_id": package.game_id,
            "season": package.season,
            "week": package.week,
        },
        "analysis_summary": {
            "plays_analyzed": len(package.plays),
            "players_extracted": len(player_ids),
            "relevant_players": len(relevant_players),
            "ngs_requests": len(request.ngs_requests),
        },
        "data_request": request.to_dict(),
    }
    
    # Add fetch results if available
    if fetch_result:
        result["fetch_result"] = {
            "sources_succeeded": fetch_result.sources_succeeded,
            "sources_failed": fetch_result.sources_failed,
            "errors": fetch_result.errors,
            "data_counts": {
                "play_by_play": len(fetch_result.play_by_play) if fetch_result.play_by_play else 0,
                "snap_counts": len(fetch_result.snap_counts) if fetch_result.snap_counts else 0,
                "team_context": len(fetch_result.team_context) if fetch_result.team_context else 0,
                "ngs_data": {
                    stat_type: len(data)
                    for stat_type, data in fetch_result.ngs_data.items()
                },
            },
        }
    
    # Add normalization results if available
    if normalized_data:
        result["normalization_result"] = {
            "records_processed": normalized_data.records_processed,
            "issues_found": len(normalized_data.issues_found),
            "issues": normalized_data.issues_found[:10],  # First 10 issues only
        }
    
    # Add merge results if available
    if merged_data:
        result["merge_result"] = {
            "players_enriched": merged_data.players_enriched,
            "teams_enriched": merged_data.teams_enriched,
            "conflicts_resolved": len(merged_data.conflicts_resolved),
        }
        
        # Include the enriched package in the result
        result["enriched_package"] = merged_data.to_dict()
    
    # Add summary results if available
    if game_summaries:
        result["game_summaries"] = game_summaries.to_dict()
    
    # Add analysis envelope if available
    if analysis_envelope:
        result["analysis_envelope"] = analysis_envelope.to_dict()

    
    return result


def analyze_game_package_pipeline(
    data: Dict[str, Any],
    dry_run: bool = False,
    strict: bool = False,
    fetch_data: bool = False,
    correlation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze a game package using the orchestrated pipeline.
    
    This is a streamlined version that uses GameAnalysisPipeline
    for coordinated execution of all steps.
    
    Args:
        data: Game package data
        dry_run: If True, only validate without full processing
        strict: If True, treat warnings as errors
        fetch_data: If True, fetch data from upstream providers
        correlation_id: Optional custom correlation ID
        
    Returns:
        Analysis results in pipeline format
    """
    # Validate and create package
    logger.info("Validating package structure...")
    try:
        package = validate_game_package(data)
        logger.info(
            f"✓ Package structure valid for {package.game_id} "
            f"({package.season} Week {package.week}) "
            f"with {len(package.plays)} plays"
        )
    except ValidationError as e:
        logger.error(f"✗ Structural validation failed: {e}")
        raise
    
    # Stop here if dry-run
    if dry_run:
        return {
            "status": "validated",
            "game_id": package.game_id,
            "season": package.season,
            "week": package.week,
            "message": "Validation only - use without --dry-run for full analysis"
        }
    
    # Configure pipeline
    config = PipelineConfig(
        fetch_data=fetch_data,
        strict_validation=strict,
        enable_envelope=True,
        correlation_id=correlation_id
    )
    
    # Execute pipeline
    pipeline = GameAnalysisPipeline()
    result = pipeline.process(package, config)
    
    # Convert to dictionary for output
    return result.to_dict()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze game packages and produce enriched analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a game package
  %(prog)s --request sample_game.json --pretty
  
  # Validation only
  %(prog)s --request sample_game.json --dry-run
  
  # With verbose logging
  %(prog)s --request sample_game.json --verbose
  
  # Save output to file
  %(prog)s --request sample_game.json --output result.json

For more information, see the module README.md
        """
    )
    
    # Required arguments
    parser.add_argument(
        '--request',
        type=str,
        required=True,
        help='Path to game package JSON file'
    )
    
    # Optional arguments
    parser.add_argument(
        '--output',
        type=str,
        help='Path to save output JSON (default: print to stdout)'
    )
    
    parser.add_argument(
        '--pretty',
        action='store_true',
        help='Pretty-print JSON output with indentation'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate input only, skip full analysis'
    )
    
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat validation warnings as errors'
    )
    
    parser.add_argument(
        '--fetch',
        action='store_true',
        help='Fetch data from upstream providers (requires .env configuration)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )
    
    parser.add_argument(
        '--pipeline',
        action='store_true',
        help='Use orchestrated pipeline mode (recommended for production)'
    )
    
    parser.add_argument(
        '--correlation-id',
        type=str,
        help='Custom correlation ID for request tracking'
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    try:
        # Load game package
        data = load_game_package(args.request)
        
        # Choose analysis mode
        if args.pipeline:
            # Use orchestrated pipeline
            logger.info("Using orchestrated pipeline mode")
            result = analyze_game_package_pipeline(
                data,
                dry_run=args.dry_run,
                strict=args.strict,
                fetch_data=args.fetch,
                correlation_id=getattr(args, 'correlation_id', None)
            )
        else:
            # Use detailed step-by-step mode
            logger.info("Using detailed step-by-step mode")
            result = analyze_game_package(
                data, 
                dry_run=args.dry_run, 
                strict=args.strict,
                fetch_data=args.fetch
            )
        
        # Format output
        if args.pretty:
            output = json.dumps(result, indent=2)
        else:
            output = json.dumps(result)
        
        # Write output
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                f.write(output)
            logger.info(f"✓ Results written to {args.output}")
        else:
            print(output)
        
        logger.info("✓ Analysis complete")
        sys.exit(0)
        
    except FileNotFoundError as e:
        logger.error(f"✗ File error: {e}")
        sys.exit(1)
    except ValidationError as e:
        logger.error(f"✗ Validation error: {e}")
        sys.exit(2)
    except json.JSONDecodeError as e:
        logger.error(f"✗ JSON parse error: {e}")
        sys.exit(3)
    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}", exc_info=True)
        sys.exit(4)


if __name__ == '__main__':
    main()
