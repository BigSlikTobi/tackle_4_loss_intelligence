"""
Data fetching utilities for NFL data.

This module centralises all calls to the third‑party ``nflreadpy`` package to
retrieve raw football data.  Each function in this file wraps a call to a
specific ``nflreadpy`` helper and hides the details of how that data is
retrieved.  By collecting all fetch logic in a single place we make it easy
to locate and modify data acquisition without touching the rest of the
pipeline.

Functions return ``pandas.DataFrame`` instances which are then passed
through transformer classes (defined in :mod:`src.core.data.transform`) to
produce cleaned and validated records.  When adding new datasets to the
pipeline, you should implement a new fetch function here first.  Naming
conventions follow the pattern ``fetch_<dataset>_data`` so that they are
easy to discover.

The functions defined below are intentionally thin wrappers – they perform
minimal parameter manipulation and delegate all heavy lifting to
``nflreadpy``.  If the upstream API changes or requires additional
configuration (for example, API keys or caching), this module is the
single point of entry to implement such changes.

Examples
--------
Fetch the 2024 season schedule:

>>> from ...core.data.fetch import fetch_game_schedule_data
>>> schedule_df = fetch_game_schedule_data(season=2024)
>>> schedule_df.head()

Similarly, to fetch all historical roster data for a team:

>>> from ...core.data.fetch import fetch_seasonal_roster_data
>>> roster_df = fetch_seasonal_roster_data(team_abbr="NYJ")
>>> print(len(roster_df))

Note
----
These functions rely on the ``nflreadpy`` library being installed.  See
``requirements.txt`` for a complete list of external dependencies.  If you
encounter import errors when calling these functions please ensure that
the package is installed in your environment.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import pandas as pd  # type: ignore

try:
    import requests
except ImportError as exc:
    raise ImportError(
        "The `requests` package is required for injury scraping. "
        "Install it via pip: pip install requests"
    ) from exc

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:
    raise ImportError(
        "The `beautifulsoup4` package is required for injury scraping. "
        "Install it via pip: pip install beautifulsoup4"
    ) from exc

try:
    import nflreadpy as nfl
except ImportError as exc:
    raise ImportError(
        "The `nflreadpy` package is required for data fetching. "
        "Install it via pip: pip install nflreadpy"
    ) from exc


logger = logging.getLogger(__name__)


_SINGLE_SEASON_PARAM_NAMES = ("season", "year")
_MULTI_SEASON_PARAM_NAMES = ("seasons", "years")
_WEEK_SINGLE_PARAM_NAMES = ("week",)
_WEEK_MULTI_PARAM_NAMES = ("weeks", "week_number", "week_num")
_SIGNATURE_ERROR_TOKENS = (
    "unexpected keyword argument",
    "got an unexpected keyword",
    "positional argument",
    "takes 1 positional argument",
    "takes 0 positional arguments",
    "missing 1 required positional argument",
    "missing 2 required positional arguments",
    "required positional argument",
    "multiple values for argument",
)


def _get_parameters(func: Callable[..., pd.DataFrame]) -> dict[str, inspect.Parameter]:
    try:
        return inspect.signature(func).parameters  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return {}


def _has_var_keyword(params: dict[str, inspect.Parameter]) -> bool:
    return any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())


def _looks_like_signature_error(exc: TypeError) -> bool:
    message = str(exc)
    return any(token in message for token in _SIGNATURE_ERROR_TOKENS)


def _to_pandas(df: Any) -> pd.DataFrame:
    """Normalise third-party data structures into ``pandas.DataFrame``."""
    if isinstance(df, pd.DataFrame):
        return df

    to_pandas = getattr(df, "to_pandas", None)
    if callable(to_pandas):
        try:
            converted = to_pandas(use_pyarrow_extension_array=False)
        except TypeError:
            converted = to_pandas()
        except ModuleNotFoundError:
            to_dicts = getattr(df, "to_dicts", None)
            if callable(to_dicts):
                return pd.DataFrame(to_dicts())
            converted = []
        if isinstance(converted, pd.DataFrame):
            return converted
        return pd.DataFrame(converted)

    to_dicts = getattr(df, "to_dicts", None)
    if callable(to_dicts):
        return pd.DataFrame(to_dicts())

    return pd.DataFrame(df)


def _filter_dataframe(df: pd.DataFrame, value: int, columns: Iterable[str]) -> pd.DataFrame:
    for column in columns:
        if column in df.columns:
            return df[df[column] == value]
    return df


def _call_import(
    func: Callable[..., pd.DataFrame],
    *,
    season: Optional[int] = None,
    week: Optional[int] = None,
    base_kwargs: Optional[dict[str, object]] = None,
    allow_no_args: bool = False,
    season_filter_columns: tuple[str, ...] = ("season", "season_year", "year"),
    week_filter_columns: tuple[str, ...] = ("week", "week_number"),
) -> pd.DataFrame:
    params = _get_parameters(func)
    kwargs: dict[str, object] = dict(base_kwargs or {})
    season_applied = False
    week_applied = False

    if season is not None:
        for key in _SINGLE_SEASON_PARAM_NAMES:
            if key in params:
                kwargs[key] = season
                season_applied = True
                break
        if not season_applied:
            for key in _MULTI_SEASON_PARAM_NAMES:
                if key in params:
                    kwargs[key] = [season]
                    season_applied = True
                    break
        if not season_applied and params and _has_var_keyword(params):
            kwargs.setdefault("season", season)
            season_applied = True

    if week is not None:
        for key in _WEEK_SINGLE_PARAM_NAMES:
            if key in params:
                kwargs[key] = week
                week_applied = True
                break
        if not week_applied:
            for key in _WEEK_MULTI_PARAM_NAMES:
                if key in params:
                    kwargs[key] = [week]
                    week_applied = True
                    break
        if not week_applied and params and _has_var_keyword(params):
            kwargs.setdefault("week", week)
            week_applied = True

    if season is None and not allow_no_args and not kwargs:
        raise ValueError(f"{func.__name__} requires a season parameter.")

    try:
        raw_df = func(**kwargs)
    except TypeError as exc:
        if _looks_like_signature_error(exc) and (season_applied or week_applied):
            # Retry without the dynamic parameters and defer to downstream filtering.
            kwargs = dict(base_kwargs or {})
            season_applied = False
            week_applied = False
            raw_df = func(**kwargs)
        else:
            raise

    df = _to_pandas(raw_df)
    if season is not None and not season_applied:
        df = _filter_dataframe(df, season, season_filter_columns)
    if week is not None and not week_applied:
        df = _filter_dataframe(df, week, week_filter_columns)
    return df


def fetch_team_data(season: Optional[int] = None) -> pd.DataFrame:
    """Return a DataFrame containing metadata about all NFL teams.

    The underlying call to ``nfl.load_teams()`` returns basic information such as
    team names, abbreviations, conferences and divisions.  This wrapper
    simply logs the operation and returns the resulting DataFrame.
    """
    label = f" for season {season}" if season else ""
    logger.info("Fetching team metadata from nflreadpy%s...", label)
    df = _call_import(
        nfl.load_teams,
        season=season,
        allow_no_args=True,
        season_filter_columns=("season", "year"),
    )
    if season is not None and "season" not in df.columns:
        logger.warning("Upstream `load_teams` did not expose a `season` column; unable to filter to season %s", season)
    logger.debug("Fetched %d team records", len(df))
    return df


def fetch_player_data(
    season: Optional[int] = None,
    *,
    active_only: bool = False,
    min_last_season: Optional[int] = None,
) -> pd.DataFrame:
    """Return a DataFrame of player metadata.

    Parameters
    ----------
    season: optional
        If provided, restricts results to players active in the given season.
    active_only: bool, optional
        When ``True``, keep only players whose ``status`` field is ``Active``.
    min_last_season: optional
        Keep only players whose ``last_season`` column is greater than or
        equal to this value.

    Returns
    -------
    pandas.DataFrame
        A table with one row per player and columns such as ``player_id``,
        ``full_name`` and ``position``.
    """
    filters: list[str] = []
    if season:
        filters.append(f"season {season}")
    if active_only:
        filters.append("status=Active")
        if min_last_season is None:
            min_last_season = datetime.now().year - 1
            filters.append(f"last_season>={min_last_season} (auto)")
    if min_last_season is not None and not (active_only and filters[-1].endswith("(auto)")):
        filters.append(f"last_season>={min_last_season}")
    label = f" with filters ({', '.join(filters)})" if filters else ""

    logger.info("Fetching player data%s...", label)
    df = _call_import(
        nfl.load_players,
        season=season,
        allow_no_args=True,
        season_filter_columns=("season", "season_year", "year"),
    )
    initial_len = len(df)
    if min_last_season is not None:
        if "last_season" in df.columns:
            last_season = pd.to_numeric(df["last_season"], errors="coerce")
            df = df[last_season.fillna(0) >= min_last_season]
        else:
            logger.warning(
                "Requested min_last_season filter %s but `last_season` column was not present",
                min_last_season,
            )
    if active_only:
        if "status" in df.columns:
            status_series = df["status"].astype(str).str.strip()
            status_lower = status_series.str.lower()
            active_mask = status_lower.str.startswith("active") | status_lower.eq("act")
            df = df[active_mask]
        else:
            logger.warning("Requested active_only filter but `status` column was not present")
    if len(df) != initial_len:
        logger.debug(
            "Filtered player records from %d to %d using active/min_last_season constraints",
            initial_len,
            len(df),
        )
    logger.debug("Fetched %d player records", len(df))
    return df


def fetch_game_schedule_data(season: Optional[int] = None, week: Optional[int] = None) -> pd.DataFrame:
    """Return the game schedule for a given season and optional week.

    Parameters
    ----------
    season: optional
        The NFL season year, e.g. ``2024``.  If omitted, schedules for all
        available seasons are returned.
    week: optional
        Restrict results to a single week within the season.  Ignored when
        ``season`` is not specified.
    """
    msg = "Fetching game schedule"
    if season:
        msg += f" for season {season}"
    if week:
        msg += f", week {week}"
    logger.info(msg + "...")
    df = _call_import(
        nfl.load_schedules,
        season=season,
        week=week,
        allow_no_args=True,
        season_filter_columns=("season", "season_year", "year"),
        week_filter_columns=("week", "week_number", "game_week"),
    )
    logger.debug("Fetched %d game schedule records", len(df))
    return df


def fetch_weekly_stats_data(season: int, week: Optional[int] = None) -> pd.DataFrame:
    """Return weekly aggregated player statistics.

    Parameters
    ----------
    season: int
        The NFL season to query.
    week: optional
        If provided, restrict results to a single week within the season.
    """
    logger.info(
        "Fetching weekly statistics for season %s%s...",
        season,
        f", week {week}" if week else "",
    )
    df = _call_import(
        nfl.load_player_stats,
        season=season,
        week=week,
        base_kwargs={"summary_level": "week"},
        week_filter_columns=("week", "week_number"),
    )
    logger.debug("Fetched %d weekly stat records", len(df))
    return df


def fetch_pbp_data(season: int, week: Optional[int] = None) -> pd.DataFrame:
    """Return play‑by‑play data for a given season and optional week.

    Because play‑by‑play datasets are very large, you may wish to restrict
    results to a particular week to improve performance.  Downsampling and
    column pruning can also be performed later by the transformer.
    """
    logger.info(
        "Fetching play‑by‑play data for season %s%s...",
        season,
        f", week {week}" if week else "",
    )
    df = _call_import(
        nfl.load_pbp,
        season=season,
        week=week,
        week_filter_columns=("week", "week_number"),
    )
    logger.debug("Fetched %d pbp records", len(df))
    return df


def fetch_ngs_data(season: int, stat_type: str) -> pd.DataFrame:
    """Return NextGenStats data for a given season and stat type.

    Parameters
    ----------
    season: int
        The season for which to retrieve NGS data.
    stat_type: str
        One of the supported NGS datasets, for example ``"receiving"`` or
        ``"rushing"``.  See the ``nflreadpy`` documentation for a complete
        list.
    """
    logger.info("Fetching NGS %s stats for season %s...", stat_type, season)
    df = _call_import(
        nfl.load_nextgen_stats,
        season=season,
        base_kwargs={"stat_type": stat_type},
        season_filter_columns=("season", "season_year", "year"),
    )
    logger.debug("Fetched %d NGS records", len(df))
    return df


def fetch_seasonal_roster_data(season: int) -> pd.DataFrame:
    """Return seasonal roster information for all teams.

    Parameters
    ----------
    season: int
        The season year, e.g. 2024.
    """
    logger.info("Fetching seasonal roster data for season %s...", season)
    df = _call_import(
        nfl.load_rosters,
        season=season,
        season_filter_columns=("season", "season_year", "year"),
    )
    logger.debug("Fetched %d roster records", len(df))
    return df


def fetch_weekly_roster_data(
    season: Optional[int] = None,
    week: Optional[int] = None,
) -> pd.DataFrame:
    """Return weekly roster data for the specified season and week.

    When ``season`` or ``week`` are omitted, the underlying ``nflreadpy`` call
    is executed without those parameters to enumerate all available snapshots.
    Callers can then filter the resulting DataFrame to the desired period.
    """
    if season is not None and week is not None:
        logger.info("Fetching weekly roster data for season %s, week %s...", season, week)
    elif season is not None:
        logger.info("Fetching weekly roster data for season %s (all weeks)...", season)
    else:
        logger.info("Fetching weekly roster data across all available seasons...")
    df = _call_import(
        nfl.load_rosters_weekly,
        season=season,
        week=week,
        allow_no_args=season is None,
        season_filter_columns=("season", "season_year", "year"),
        week_filter_columns=("week", "week_number"),
    )
    logger.debug("Fetched %d weekly roster records", len(df))
    return df


def fetch_ftn_data(season: int, week: Optional[int] = None) -> pd.DataFrame:
    """Return advanced Football Study Hall (FTN) data.

    FTN data includes advanced statistics like Expected Points Added (EPA) and
    success rate.  This wrapper allows an optional week filter.
    """
    logger.info(
        "Fetching FTN data for season %s%s...",
        season,
        f", week {week}" if week else "",
    )
    df = _call_import(
        nfl.load_ftn_charting,
        season=season,
        week=week,
        week_filter_columns=("week", "week_number"),
    )
    logger.debug("Fetched %d FTN records", len(df))
    return df

def fetch_pfr_data(season: int, week: Optional[int] = None) -> pd.DataFrame:
    """Return Pro Football Reference (PFR) data for a given season and optional week."""
    logger.info(
        "Fetching PFR data for season %s%s...",
        season,
        f", week {week}" if week else "",
    )
    stat_types = ("pass", "rush", "rec")
    frames = []
    for stat_type in stat_types:
        url = (
            "https://github.com/nflverse/nflverse-data/releases/download/"
            f"pfr_advstats/advstats_week_{stat_type}_{season}.parquet"
        )
        try:
            part = pd.read_parquet(url)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to download PFR {stat_type} data for season {season}"
            ) from exc
        part["stat_type"] = stat_type
        frames.append(part)

    df = pd.concat(frames, ignore_index=True)
    if week is not None and "week" in df.columns:
        df = df[df["week"] == week]
    logger.debug("Fetched %d PFR records", len(df))
    return df


_INJURY_API_URL = "https://www.nfl.com/api/injuries/v1/teams"
_INJURY_PAGE_TEMPLATE = "https://www.nfl.com/injuries/league/{season}/{segment}"
_DEFAULT_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
_PLAYER_LIST_KEYS: Tuple[str, ...] = (
    "players",
    "injuries",
    "injuryList",
    "playerList",
    "injuredPlayers",
    "injuredplayers",
)
_TEAM_ABBR_KEYS: Tuple[str, ...] = (
    "teamAbbr",
    "team",
    "abbr",
    "teamCode",
    "clubcode",
)
_TEAM_NAME_KEYS: Tuple[str, ...] = (
    "teamName",
    "name",
    "fullName",
    "teamFullName",
    "clubName",
)
_PLAYER_NAME_KEYS: Tuple[str, ...] = (
    "playerFullName",
    "displayName",
    "playerName",
    "name",
    "fullName",
)
_PLAYER_ID_KEYS: Tuple[str, ...] = (
    "playerId",
    "gsisId",
    "nflId",
    "nflComId",
    "id",
)
_INJURY_KEYS: Tuple[str, ...] = (
    "injury",
    "injuryDesc",
    "injuryDescription",
    "injuryDetail",
)
_PRACTICE_STATUS_KEYS: Tuple[str, ...] = (
    "practiceStatus",
    "practice",
    "practiceParticipation",
    "participation",
)
_GAME_STATUS_KEYS: Tuple[str, ...] = (
    "gameStatus",
    "status",
    "game",
)
_LAST_UPDATE_KEYS: Tuple[str, ...] = (
    "lastUpdated",
    "lastUpdate",
    "lastUpdatedDate",
    "updated",
    "update",
    "updateTimestamp",
)


def fetch_injury_data(
    season: int,
    week: int,
    *,
    season_type: str = "reg",
) -> pd.DataFrame:
    """Scrape NFL injury reports for the given season and week."""

    if season is None:
        raise ValueError("`season` is required when fetching injuries")
    if week is None:
        raise ValueError("`week` is required when fetching injuries")

    season_type_normalised = season_type.lower()
    if season_type_normalised not in {"reg", "pre", "post"}:
        raise ValueError(
            "season_type must be one of 'reg', 'pre', or 'post'"
        )

    context: Dict[str, Any] = {
        "season": season,
        "week": week,
        "season_type": season_type_normalised.upper(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    records: List[Dict[str, Any]] = []
    api_error: Optional[str] = None

    try:
        records = _fetch_injuries_via_api(season, week, season_type_normalised, context)
        if records:
            logger.debug(
                "Fetched %d injury records via NFL API", len(records)
            )
    except Exception as exc:  # pragma: no cover - network safeguards
        api_error = str(exc)
        logger.debug("NFL injury API fetch failed: %s", exc, exc_info=True)

    if not records:
        segment = _build_week_segment(season_type_normalised, week)
        page_url = _INJURY_PAGE_TEMPLATE.format(season=season, segment=segment)
        logger.info(
            "Scraping NFL injury page for season %s %s week %s",  # type: ignore[str-format]
            season,
            season_type_normalised.upper(),
            week,
        )
        try:
            records = _fetch_injuries_via_html(page_url, context)
        except Exception as exc:  # pragma: no cover - network safeguards
            logger.error("Failed to scrape NFL injuries from %s", page_url)
            if api_error:
                logger.error("API attempt also failed: %s", api_error)
            raise

    if not records:
        logger.warning(
            "No injury data discovered for season %s %s week %s",
            season,
            season_type_normalised.upper(),
            week,
        )
        columns = [
            "team_abbr",
            "team_name",
            "player_name",
            "injury",
            "practice_status",
            "game_status",
            "player_id",
            "source_player_id",
            "last_update",
            "season",
            "week",
            "season_type",
        ]
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(records)
    df["season"] = season
    df["week"] = week
    df["season_type"] = season_type_normalised.upper()
    return df


def _build_week_segment(season_type: str, week: int) -> str:
    return f"{season_type}{week}"


def _fetch_injuries_via_api(
    season: int,
    week: int,
    season_type: str,
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    params = {
        "season": str(season),
        "seasonType": season_type.upper(),
        "week": str(week),
    }
    response = requests.get(
        _INJURY_API_URL,
        params=params,
        headers=_DEFAULT_HTTP_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("NFL injury API returned invalid JSON") from exc
    return _extract_injury_records_from_payload(payload, context)


def _fetch_injuries_via_html(url: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    response = requests.get(url, headers=_DEFAULT_HTTP_HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    records = _extract_injuries_from_next_data(soup, context)
    if records:
        return records
    return _extract_injuries_from_tables(soup, context)


def _extract_injuries_from_next_data(
    soup: BeautifulSoup,
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return []
    try:
        payload = json.loads(script.string)
    except json.JSONDecodeError:
        logger.debug("Unable to parse __NEXT_DATA__ payload for injuries", exc_info=True)
        return []
    return _extract_injury_records_from_payload(payload, context)


def _extract_injury_records_from_payload(
    payload: Any,
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for team_abbr, team_name, players, node_context in _iter_team_nodes(payload):
        combined_context = dict(context)
        if node_context.get("last_update"):
            combined_context["last_update"] = node_context["last_update"]
        clean_abbr = _clean_team_code(team_abbr)
        for player in players:
            record = _normalise_injury_player(player, clean_abbr, team_name, combined_context)
            if record:
                records.append(record)
    return records


def _iter_team_nodes(payload: Any) -> Iterator[Tuple[Optional[str], Optional[str], List[Any], Dict[str, Any]]]:
    stack: List[Any] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            lowered = {str(key).lower(): value for key, value in current.items()}
            for list_key in _PLAYER_LIST_KEYS:
                values = lowered.get(list_key.lower())
                if isinstance(values, list) and values:
                    team_abbr = _extract_string_from_mapping(current, _TEAM_ABBR_KEYS)
                    team_name = _extract_string_from_mapping(current, _TEAM_NAME_KEYS)
                    last_update = _extract_string_from_mapping(current, _LAST_UPDATE_KEYS)
                    yield team_abbr, team_name, values, {"last_update": last_update}
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _normalise_injury_player(
    player: Any,
    team_abbr: Optional[str],
    team_name: Optional[str],
    context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not isinstance(player, dict):
        return None

    player_name = _extract_string_from_mapping(player, _PLAYER_NAME_KEYS)
    if not player_name:
        return None

    player_id = _extract_string_from_mapping(player, _PLAYER_ID_KEYS)
    injury_text = _extract_string_from_mapping(player, _INJURY_KEYS)
    practice_status = _extract_status_value(player, _PRACTICE_STATUS_KEYS)
    game_status = _extract_status_value(player, _GAME_STATUS_KEYS)
    last_update = (
        _extract_string_from_mapping(player, _LAST_UPDATE_KEYS)
        or context.get("last_update")
        or context.get("fetched_at")
    )

    return {
        "team_abbr": team_abbr,
        "team_name": team_name,
        "player_name": player_name,
        "injury": injury_text,
        "practice_status": practice_status,
        "game_status": game_status,
        "player_id": player_id,
        "source_player_id": player_id,
        "last_update": last_update,
    }


def _extract_injuries_from_tables(
    soup: BeautifulSoup,
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for table in soup.find_all("table"):
        header_row = table.find("thead")
        if not header_row:
            continue
        headers = [
            _normalise_whitespace(th.get_text(" ", strip=True)).lower()
            for th in header_row.find_all("th")
        ]
        if not headers or "player" not in headers:
            continue

        header_index = {header: idx for idx, header in enumerate(headers)}
        player_idx = _resolve_header_index(header_index, ("player", "player name"))
        if player_idx is None:
            continue
        injury_idx = _resolve_header_index(
            header_index,
            ("injury", "injury description", "injury detail"),
        )
        practice_idx = _resolve_header_index(
            header_index,
            ("practice status", "practice", "practice participation"),
        )
        game_idx = _resolve_header_index(
            header_index,
            ("game status", "status", "game"),
        )

        team_abbr = _clean_team_code(
            table.get("data-team-abbr") or table.get("data-abbr")
        )
        team_name = table.get("data-team-name") or table.get("aria-label")
        if not team_name:
            heading = table.find_previous(["h2", "h3", "h4"])
            if heading:
                team_name = _normalise_whitespace(
                    heading.get_text(" ", strip=True)
                )

        body = table.find("tbody")
        if not body:
            continue

        for row in body.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) <= player_idx:
                continue
            player_name = _normalise_whitespace(
                cells[player_idx].get_text(" ", strip=True)
            )
            if not player_name:
                continue
            record = {
                "team_abbr": team_abbr,
                "team_name": team_name,
                "player_name": player_name,
                "injury": _extract_cell_value(cells, injury_idx),
                "practice_status": _extract_cell_value(cells, practice_idx),
                "game_status": _extract_cell_value(cells, game_idx),
                "player_id": None,
                "source_player_id": None,
                "last_update": context.get("fetched_at"),
            }
            records.append(record)

    return records


def _resolve_header_index(
    header_index: Dict[str, int],
    candidates: Sequence[str],
) -> Optional[int]:
    for candidate in candidates:
        normalised = candidate.lower()
        if normalised in header_index:
            return header_index[normalised]
    return None


def _extract_cell_value(cells: Sequence[Any], index: Optional[int]) -> Optional[str]:
    if index is None or index >= len(cells):
        return None
    text = cells[index].get_text(" ", strip=True)
    return _normalise_whitespace(text) if text else None


def _extract_status_value(mapping: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
    raw = _extract_raw_value(mapping, keys)
    if raw is None:
        return None
    if isinstance(raw, dict):
        nested = _extract_string_from_mapping(raw, ("status", "text", "value"))
        if nested:
            return nested
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                nested = _extract_string_from_mapping(
                    item, ("status", "text", "value")
                )
                if nested:
                    return nested
            elif item:
                return _normalise_whitespace(str(item))
        return None
    return _normalise_whitespace(str(raw))


def _extract_raw_value(mapping: Dict[str, Any], keys: Sequence[str]) -> Any:
    if not isinstance(mapping, dict):
        return None
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return value
    return None


def _extract_string_from_mapping(
    mapping: Any,
    keys: Sequence[str],
) -> Optional[str]:
    if not isinstance(mapping, dict):
        return None
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value:
                return _normalise_whitespace(value)
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, dict):
            nested = _extract_string_from_mapping(
                value, ("text", "value", "displayName", "name", "status")
            )
            if nested:
                return nested
    return None


def _normalise_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_team_code(team_code: Optional[str]) -> Optional[str]:
    if team_code is None:
        return None
    code = str(team_code).strip().upper()
    return code or None
