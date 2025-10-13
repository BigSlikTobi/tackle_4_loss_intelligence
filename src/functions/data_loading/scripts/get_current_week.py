#!/usr/bin/env python3
"""Calculate the current NFL week based on the current date.

IMPORTANT: Update the season dates below at the start of each new NFL season.
The dates below are for the 2025 season.

For future seasons:
1. Update SEASON_XXXX_START to the Thursday of Week 1 regular season
2. Update PRESEASON_START to ~4 weeks before regular season
3. Update the SEASON variable in .github/workflows/injuries-daily.yml
"""

from datetime import datetime, timezone
import sys


# NFL 2025 Season Key Dates
# Regular season starts first Thursday in September (typically Sept 4-11)
SEASON_2025_START = datetime(2025, 9, 4, tzinfo=timezone.utc)  # Thursday, Sept 4, 2025
REGULAR_SEASON_WEEKS = 18

# Preseason typically runs 3 weeks before regular season
PRESEASON_START = datetime(2025, 8, 7, tzinfo=timezone.utc)  # ~4 weeks before regular season
PRESEASON_WEEKS = 3


def get_current_week_and_season_type() -> tuple[int, str]:
    """
    Calculate the current NFL week and season type.
    
    Returns:
        Tuple of (week_number, season_type) where season_type is 'pre', 'reg', or 'post'
    """
    now = datetime.now(timezone.utc)
    
    # Before preseason
    if now < PRESEASON_START:
        # Default to week 1 preseason (will fail gracefully if data not available)
        return 1, "pre"
    
    # During preseason
    if now < SEASON_2025_START:
        days_since_preseason = (now - PRESEASON_START).days
        week = min((days_since_preseason // 7) + 1, PRESEASON_WEEKS)
        return week, "pre"
    
    # During regular season
    days_since_start = (now - SEASON_2025_START).days
    week = (days_since_start // 7) + 1
    
    if week <= REGULAR_SEASON_WEEKS:
        return week, "reg"
    
    # Postseason (playoffs)
    # Playoffs start after Week 18, typically have 4 weeks (Wild Card, Divisional, Conference, Super Bowl)
    playoff_week = week - REGULAR_SEASON_WEEKS
    return min(playoff_week, 4), "post"


if __name__ == "__main__":
    week, season_type = get_current_week_and_season_type()
    
    # Output format for GitHub Actions or command line
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        import json
        print(json.dumps({"week": week, "season_type": season_type}))
    else:
        print(f"{week} {season_type}")
