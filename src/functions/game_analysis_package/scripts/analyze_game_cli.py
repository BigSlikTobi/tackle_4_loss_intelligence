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
from pathlib import Path
from typing import Dict, Any

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
from src.functions.game_analysis_package.core.extraction.player_extractor import (
    PlayerExtractor
)
from src.functions.game_analysis_package.core.bundling.request_builder import (
    DataRequestBuilder,
    RelevantPlayer
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
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Analyze a game package and produce enriched output.
    
    Args:
        data: Game package data
        dry_run: If True, only validate without full processing
        
    Returns:
        Analysis results
    """
    # Step 1: Validate game package
    logger.info("Step 1: Validating game package...")
    try:
        package = validate_game_package(data)
        logger.info(
            f"✓ Valid game package for {package.game_id} "
            f"({package.season} Week {package.week}) "
            f"with {len(package.plays)} plays"
        )
    except ValidationError as e:
        logger.error(f"✗ Validation failed: {e}")
        raise
    
    if dry_run:
        logger.info("Dry-run mode: validation complete, skipping analysis")
        return {
            "status": "valid",
            "game_id": package.game_id,
            "season": package.season,
            "week": package.week,
            "play_count": len(package.plays)
        }
    
    # Step 2: Extract players
    logger.info("Step 2: Extracting players from plays...")
    extractor = PlayerExtractor()
    player_ids = extractor.extract_players(package.plays)
    logger.info(f"✓ Extracted {len(player_ids)} unique players")
    
    # Step 3: Build data request
    logger.info("Step 3: Building data request...")
    
    # For now, create mock relevant players from extracted IDs
    # In full implementation, this would come from relevance scoring
    relevant_players = [
        RelevantPlayer(player_id=pid, relevance_score=1.0)
        for pid in list(player_ids)[:20]  # Limit for demo
    ]
    
    builder = DataRequestBuilder()
    request = builder.build_request(
        game_info=package.get_game_info(),
        relevant_players=relevant_players
    )
    logger.info(
        f"✓ Built request with {len(request.ngs_requests)} NGS requests "
        f"for {len(request.player_ids)} players"
    )
    
    # For now, return the analysis structure
    # Full implementation would continue with data fetching, normalization, etc.
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
    
    return result


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
        '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    try:
        # Load game package
        data = load_game_package(args.request)
        
        # Analyze
        result = analyze_game_package(data, dry_run=args.dry_run)
        
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
