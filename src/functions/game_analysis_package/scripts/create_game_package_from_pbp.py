#!/usr/bin/env python3
"""
Create a game package JSON from PBP data using the data_loading provider.

This script fetches play-by-play data from the data_loading module's PBP provider
(which uses nflreadpy under the hood) and converts it to game package format.

Usage:
    python create_game_package_from_pbp.py --game-id 2025_06_DEN_NYJ --output test_requests/2025_06_DEN_NYJ_real.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

# Add project root to path
project_root = Path(__file__).parents[4]
sys.path.insert(0, str(project_root))

from src.functions.data_loading.core.providers import get_provider

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def safe_value(value: Any) -> Any:
    """Convert pandas NaN and other special values to JSON-safe values."""
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        try:
            # Convert to int if it's a whole number
            return int(value) if value == int(value) else float(value)
        except (ValueError, OverflowError):
            return None
    return value


def create_game_package(game_id: str, output_path: str) -> None:
    """
    Fetch PBP data for a game and create a game package JSON file.
    
    Args:
        game_id: Game identifier (e.g., "2025_06_DEN_NYJ")
        output_path: Path to write the JSON file
    """
    logger.info(f"Fetching play-by-play data for {game_id}...")
    
    # Parse game_id to extract season and week
    parts = game_id.split('_')
    if len(parts) < 4:
        raise ValueError(f"Invalid game_id format: {game_id}. Expected format: YYYY_WW_AWAY_HOME")
    
    season = int(parts[0])
    week = int(parts[1])
    away_team = parts[2]
    home_team = parts[3]
    
    logger.info(f"Season: {season}, Week: {week}, Away: {away_team}, Home: {home_team}")
    
    # Get PBP provider from data_loading module
    pbp_provider = get_provider("pbp")
    
    # Fetch play-by-play data
    try:
        pbp_data = pbp_provider.get(
            season=season,
            week=week,
            game_id=game_id,
            output="dict"
        )
    except Exception as e:
        logger.error(f"Failed to fetch PBP data: {e}")
        raise
    
    if not pbp_data:
        logger.error(f"No play-by-play data found for {game_id}")
        sys.exit(1)
    
    logger.info(f"Fetched {len(pbp_data)} plays")
    
    # Filter plays with required team info (posteam and defteam)
    valid_plays = []
    skipped_plays = 0
    
    for play in pbp_data:
        if play.get('posteam') and play.get('defteam'):
            valid_plays.append(play)
        else:
            skipped_plays += 1
    
    if skipped_plays > 0:
        logger.info(f"Filtered out {skipped_plays} plays without team info (kept {len(valid_plays)} plays)")
    
    # Convert to game package format
    game_package = {
        "schema_version": "1.0.0",
        "producer": "create_game_package_from_pbp.py@1.0.0",
        "game_package": {
            "season": season,
            "week": week,
            "game_id": game_id,
            "home_team": home_team,
            "away_team": away_team,
            "plays": []
        }
    }
    
    # Convert each play to game package format
    for play in valid_plays:
        game_package["game_package"]["plays"].append({
            "play_id": safe_value(play.get("play_id")),
            "game_id": safe_value(play.get("game_id")),
            "quarter": safe_value(play.get("quarter")),
            "time": safe_value(play.get("time")),
            "down": safe_value(play.get("down")),
            "yards_to_go": safe_value(play.get("ydstogo")),
            "yardline": safe_value(play.get("yardline_100")),
            "posteam": safe_value(play.get("posteam")),
            "defteam": safe_value(play.get("defteam")),
            "play_type": safe_value(play.get("play_type")),
            "yards_gained": safe_value(play.get("yards_gained", 0)),
            "touchdown": safe_value(play.get("touchdown", 0)),
            "safety": safe_value(play.get("safety", 0)),
            "passer_player_id": safe_value(play.get("passer_player_id")),
            "receiver_player_id": safe_value(play.get("receiver_player_id")),
            "rusher_player_id": safe_value(play.get("rusher_player_id")),
            "tackler_player_ids": safe_value(play.get("tackle_1_player_id")),
            "assist_tackler_player_ids": safe_value(play.get("tackle_2_player_id")),
            "sack_player_ids": safe_value(play.get("sack_player_id")),
            "kicker_player_id": safe_value(play.get("kicker_player_id")),
            "punter_player_id": safe_value(play.get("punter_player_id")),
            "returner_player_id": safe_value(play.get("return_player_id")),
            "interception_player_id": safe_value(play.get("interception_player_id")),
            "fumble_recovery_player_id": safe_value(play.get("fumble_recovery_1_player_id")),
            "forced_fumble_player_id": safe_value(play.get("forced_fumble_player_1_player_id")),
        })
    
    # Write to file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(game_package, f, indent=2)
    
    logger.info(f"✓ Game package written to {output_path}")
    logger.info(f"  - {len(game_package['game_package']['plays'])} plays")
    logger.info(f"  - Season {season}, Week {week}")
    logger.info(f"  - {away_team} @ {home_team}")


def main():
    parser = argparse.ArgumentParser(
        description="Create game package from PBP data using data_loading provider"
    )
    parser.add_argument(
        "--game-id",
        required=True,
        help="Game identifier (e.g., '2025_06_DEN_NYJ')"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file path"
    )
    
    args = parser.parse_args()
    
    try:
        create_game_package(args.game_id, args.output)
    except Exception as e:
        logger.error(f"Failed to create game package: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
