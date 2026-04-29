"""Helpers for inferring the current NFL season, week, and season type.

IMPORTANT: Update SEASON_START / PRESEASON_START at the start of each new
NFL season. Defaults are encoded for the 2025 season.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


# NFL 2025 Season Key Dates
# Regular season starts the first Thursday in September.
SEASON_START = datetime(2025, 9, 4, tzinfo=timezone.utc)
REGULAR_SEASON_WEEKS = 18

# Preseason runs ~3 weeks before the regular season opener.
PRESEASON_START = datetime(2025, 8, 7, tzinfo=timezone.utc)
PRESEASON_WEEKS = 3

# The postseason has 4 weeks (Wild Card, Divisional, Conference, Super Bowl).
POSTSEASON_WEEKS = 4


def _season_window_end() -> datetime:
    """End of the active NFL calendar window (Super Bowl Sunday + buffer).

    Computed as ``SEASON_START + (REGULAR_SEASON_WEEKS + POSTSEASON_WEEKS)``
    weeks. Used to distinguish "in season" from "offseason" — anything past
    this point is treated as offseason until the next ``PRESEASON_START``.
    """
    return SEASON_START + timedelta(weeks=REGULAR_SEASON_WEEKS + POSTSEASON_WEEKS)


def is_in_season() -> bool:
    """Return True iff the current date is inside the NFL calendar window.

    The window runs from ``PRESEASON_START`` (early August) through Super
    Bowl Sunday (early February of the following year). Outside this window
    there is no meaningful "current week" to tag scheduled data with, so
    callers should refuse to auto-detect a week.
    """
    now = datetime.now(timezone.utc)
    return PRESEASON_START <= now <= _season_window_end()


def get_current_season() -> int:
    """Return the NFL season year for the current date.

    Aligned with the NFL league year, which begins March 16 each year.
    From March onward, the "current season" is the upcoming one whose
    regular season starts that September. January and February still
    belong to the prior season (playoffs / Super Bowl).

    Note: the latest season actually present in nflverse data may lag
    this value by a few weeks — the next season's schedule is typically
    published in May. CLIs that display data may need to fall back to
    ``max(season)`` from the table when the calendar default has no rows
    yet.
    """

    now = datetime.now(timezone.utc)
    if now.month >= 3:
        return now.year
    return now.year - 1


def get_current_week_and_season_type() -> Tuple[Optional[int], Optional[str]]:
    """Calculate the current NFL week and season phase.

    Returns:
        ``(week_number, season_type)`` where ``season_type`` is ``'pre'``,
        ``'reg'``, or ``'post'``. Returns ``(None, None)`` when the current
        date falls outside the NFL calendar (offseason between Super Bowl
        Sunday and the next preseason). Callers must handle ``None`` —
        scheduled loaders should not synthesize a week in that case.
    """

    now = datetime.now(timezone.utc)

    if now < PRESEASON_START:
        return None, None

    if now < SEASON_START:
        days_since_preseason = (now - PRESEASON_START).days
        week = min((days_since_preseason // 7) + 1, PRESEASON_WEEKS)
        return week, "pre"

    days_since_start = (now - SEASON_START).days
    week = (days_since_start // 7) + 1

    if week <= REGULAR_SEASON_WEEKS:
        return week, "reg"

    playoff_week = week - REGULAR_SEASON_WEEKS
    if playoff_week > POSTSEASON_WEEKS:
        # Past Super Bowl Sunday — offseason until the next PRESEASON_START.
        return None, None
    return playoff_week, "post"
