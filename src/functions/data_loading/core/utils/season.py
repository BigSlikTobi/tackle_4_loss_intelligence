"""Helpers for inferring the current NFL season, week, and season type.

IMPORTANT: Update SEASON_START / PRESEASON_START at the start of each new
NFL season. Defaults are encoded for the 2025 season.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple


# NFL 2025 Season Key Dates
# Regular season starts the first Thursday in September.
SEASON_START = datetime(2025, 9, 4, tzinfo=timezone.utc)
REGULAR_SEASON_WEEKS = 18

# Preseason runs ~3 weeks before the regular season opener.
PRESEASON_START = datetime(2025, 8, 7, tzinfo=timezone.utc)
PRESEASON_WEEKS = 3


def get_current_season() -> int:
    """Return the NFL season year for the current date.

    NFL seasons span two calendar years (Sept → Feb). We treat August onward
    as the new season to cover preseason; January / February belong to the
    prior year's season (playoffs / Super Bowl).
    """

    now = datetime.now(timezone.utc)
    if now.month >= 8:
        return now.year
    return now.year - 1


def get_current_week_and_season_type() -> Tuple[int, str]:
    """Calculate the current NFL week and season phase.

    Returns:
        (week_number, season_type) where season_type is 'pre', 'reg', or 'post'.
    """

    now = datetime.now(timezone.utc)

    if now < PRESEASON_START:
        return 1, "pre"

    if now < SEASON_START:
        days_since_preseason = (now - PRESEASON_START).days
        week = min((days_since_preseason // 7) + 1, PRESEASON_WEEKS)
        return week, "pre"

    days_since_start = (now - SEASON_START).days
    week = (days_since_start // 7) + 1

    if week <= REGULAR_SEASON_WEEKS:
        return week, "reg"

    playoff_week = week - REGULAR_SEASON_WEEKS
    return min(playoff_week, 4), "post"
