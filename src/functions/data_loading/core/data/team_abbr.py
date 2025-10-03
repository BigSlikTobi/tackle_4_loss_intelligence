"""
Utilities for normalizing NFL team abbreviations to canonical forms.

This module exposes a single function, ``normalize_team_abbr``, that accepts any
variation of an NFL team abbreviation and returns a canonical two‑ or three‑letter
code.  Normalisation is important when working with data from multiple sources
because different APIs and websites use historical or alternative team codes.

For example ``LAR`` and ``STL`` both map to ``LA`` to represent the Los Angeles
Rams, while ``SD`` maps to ``LAC`` for the Los Angeles Chargers.  Returning
``None`` for unknown values avoids inserting invalid foreign keys into the
database.

This file is largely unmodified from the original project; the primary addition
is this explanatory header to help future maintainers understand why
abbreviation normalisation exists and how to use it.
"""

from typing import Any, Optional
import pandas as pd


# Canonical abbreviations used in our database
CANONICAL = {
    'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN',
    'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC', 'LAC', 'LA', 'LV', 'MIA', 'MIN',
    'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SEA', 'SF', 'TB', 'TEN', 'WAS'
}


# Mapping of historical/alternate codes to canonical ones
TEAM_ABBR_MAP = {
    # Los Angeles / St. Louis Rams
    'STL': 'LA', 'LAR': 'LA',
    # Raiders
    'OAK': 'LV', 'LVR': 'LV',
    # Chargers
    'SD': 'LAC', 'SDG': 'LAC',
    # Jaguars
    'JAC': 'JAX',
    # Washington
    'WSH': 'WAS',
    # Packers
    'GNB': 'GB',
    # Chiefs
    'KAN': 'KC',
    # 49ers
    'SFO': 'SF',
    # Buccaneers
    'TAM': 'TB',
    # Saints / Patriots older codes
    'NOR': 'NO', 'NWE': 'NE',
    # Cardinals historic (Phoenix)
    'PHX': 'ARI', 'PHO': 'ARI', 'ARZ': 'ARI',
    # Cleveland alternate
    'CLV': 'CLE',
}


def normalize_team_abbr(team_abbr: Any) -> Optional[str]:
    """Return a canonical team abbreviation or ``None`` if the code is unrecognised.

    Parameters
    ----------
    team_abbr : Any
        The raw team abbreviation from an external data source.  This value may be
        a string, number, or ``None``/NaN.  Non‑string values are coerced to
        strings and upper‑cased prior to normalisation.

    Returns
    -------
    Optional[str]
        A canonical two‑ or three‑letter team code if the input represents a
        known team, otherwise ``None``.  Returning ``None`` signals to the
        calling code that the abbreviation is invalid and should not be used as
        a foreign key.
    """
    if pd.isna(team_abbr) or not team_abbr:
        return None

    code = str(team_abbr).upper().strip()

    # First apply mapping if present
    if code in TEAM_ABBR_MAP:
        code = TEAM_ABBR_MAP[code]

    # If already canonical, accept
    if code in CANONICAL:
        return code

    # If not canonical but 2–3 characters, keep only if it's known; else return None
    return None