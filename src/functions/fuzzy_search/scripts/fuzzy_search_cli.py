"""Command line interface for fuzzy searching players, teams, or games."""

from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Optional

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.fuzzy_search.core.config import (
    FuzzySearchRequest,
    GameSearchFilters,
    PlayerSearchFilters,
)
from src.functions.fuzzy_search.core.search_service import FuzzySearchService

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="entity", required=True)

    common_args = {
        "query": {
            "help": "Search query (e.g., player name, team name, or matchup)",
        },
        "--limit": {
            "type": int,
            "default": 10,
            "help": "Maximum number of results to return",
        },
    }

    players_parser = subparsers.add_parser("players", help="Search players")
    players_parser.add_argument("query", **common_args["query"])
    players_parser.add_argument("--limit", **common_args["--limit"])
    players_parser.add_argument("--team", help="Filter players by team abbreviation")
    players_parser.add_argument("--college", help="Filter players by college name")
    players_parser.add_argument("--position", help="Filter players by position")

    teams_parser = subparsers.add_parser("teams", help="Search teams")
    teams_parser.add_argument("query", **common_args["query"])
    teams_parser.add_argument("--limit", **common_args["--limit"])

    games_parser = subparsers.add_parser("games", help="Search games")
    games_parser.add_argument("query", **common_args["query"])
    games_parser.add_argument("--limit", **common_args["--limit"])
    games_parser.add_argument("--weekday", help="Filter games by weekday name")

    return parser.parse_args()


def build_request(args: argparse.Namespace) -> FuzzySearchRequest:
    player_filters: Optional[PlayerSearchFilters] = None
    game_filters: Optional[GameSearchFilters] = None

    if args.entity == "players":
        player_filters = PlayerSearchFilters(
            team=args.team,
            college=args.college,
            position=args.position,
        )
    elif args.entity == "games":
        game_filters = GameSearchFilters(weekday=args.weekday)

    return FuzzySearchRequest(
        entity_type=args.entity,
        query=args.query,
        limit=args.limit,
        player_filters=player_filters or PlayerSearchFilters(),
        game_filters=game_filters or GameSearchFilters(),
    )


def main() -> None:
    load_env()
    setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))

    args = parse_args()
    service = FuzzySearchService()
    request = build_request(args)

    results = service.search(request)
    payload = [result.to_dict() for result in results]

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
