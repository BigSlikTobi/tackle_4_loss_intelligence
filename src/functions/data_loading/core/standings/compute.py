"""Aggregate game results into per-team standings records.

Pure functions where possible; the only impure entry point is :func:`fetch_inputs`
which talks to Supabase. Callers that want to test or compute from in-memory
data should use :func:`build_team_records` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..utils.logging import get_logger
from .tiebreakers import rank_conference, rank_division

logger = get_logger(__name__)

_PAGE_SIZE = 1000


@dataclass
class TeamRecord:
    """Per-team aggregates used as input to the tiebreaker cascade."""

    team_abbr: str
    team_name: Optional[str]
    conference: str
    division: str

    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: int = 0
    points_against: int = 0

    div_wins: int = 0
    div_losses: int = 0
    div_ties: int = 0
    conf_wins: int = 0
    conf_losses: int = 0
    conf_ties: int = 0
    home_wins: int = 0
    home_losses: int = 0
    home_ties: int = 0
    away_wins: int = 0
    away_losses: int = 0
    away_ties: int = 0

    # Per-game outcomes in chronological order; used for last5 + streak.
    # Each entry is ('W'|'L'|'T', week:int).
    game_log: List[Tuple[str, int]] = field(default_factory=list)

    # opponent_abbr -> (w, l, t) from this team's perspective
    head_to_head: Dict[str, List[int]] = field(default_factory=dict)

    # Per-opponent net points (this_team minus opponent), summed across all
    # games against that opponent. Used for tiebreaker steps that aggregate
    # net points over a subset of opponents.
    net_vs: Dict[str, int] = field(default_factory=dict)

    # Filled in second pass:
    sov: float = 0.0
    sos: float = 0.0

    @property
    def games_played(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_pct(self) -> float:
        gp = self.games_played
        if gp == 0:
            return 0.0
        return (self.wins + 0.5 * self.ties) / gp

    @property
    def point_diff(self) -> int:
        return self.points_for - self.points_against

    @property
    def opponents(self) -> List[str]:
        return list(self.head_to_head.keys())

    @property
    def defeated_opponents(self) -> List[str]:
        return [opp for opp, (w, _l, _t) in self.head_to_head.items() if w > 0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_inputs(
    *,
    season: int,
    through_week: Optional[int] = None,
    client: Any = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fetch games and teams from Supabase. Returns ``(games, teams)``.

    Only completed regular-season games are returned. Pages through Supabase's
    1000-row default limit.
    """
    if client is None:
        from src.shared.db.connection import get_supabase_client  # local import to keep module pure

        client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client is not available")

    games: List[Dict[str, Any]] = []
    offset = 0
    while True:
        query = (
            client.table("games")
            .select(
                "game_id,season,week,game_type,home_team,away_team,home_score,away_score"
            )
            .eq("season", int(season))
            .eq("game_type", "REG")
            .order("week")
            .order("gameday")
            .range(offset, offset + _PAGE_SIZE - 1)
        )
        if through_week is not None:
            query = query.lte("week", int(through_week))
        response = query.execute()
        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Supabase error fetching games: {error}")
        page = getattr(response, "data", None) or []
        games.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    teams_resp = (
        client.table("teams")
        .select("team_abbr,team_name,team_conference,team_division")
        .execute()
    )
    error = getattr(teams_resp, "error", None)
    if error:
        raise RuntimeError(f"Supabase error fetching teams: {error}")
    teams = getattr(teams_resp, "data", None) or []

    logger.debug(
        "Fetched %d REG games and %d teams for season=%s through_week=%s",
        len(games),
        len(teams),
        season,
        through_week,
    )
    return games, teams


def build_team_records(
    *,
    games: Iterable[Dict[str, Any]],
    teams: Iterable[Dict[str, Any]],
) -> Dict[str, TeamRecord]:
    """Aggregate a season's REG games into per-team :class:`TeamRecord` objects.

    Skips games without both scores. Caller is responsible for restricting
    ``games`` to REG and to the desired ``through_week`` window.
    """
    records: Dict[str, TeamRecord] = {}
    for t in teams:
        abbr = (t.get("team_abbr") or "").upper().strip()
        if not abbr:
            continue
        records[abbr] = TeamRecord(
            team_abbr=abbr,
            team_name=t.get("team_name"),
            conference=(t.get("team_conference") or "").strip(),
            division=(t.get("team_division") or "").strip(),
        )

    # Pass 1: per-game accumulation. Games are pre-ordered by week.
    for g in sorted(games, key=lambda r: (r.get("week") or 0)):
        home = (g.get("home_team") or "").upper().strip()
        away = (g.get("away_team") or "").upper().strip()
        if not home or not away:
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        try:
            hs = int(float(hs))
            as_ = int(float(as_))
        except (TypeError, ValueError):
            continue
        week = int(g.get("week") or 0)

        if home not in records or away not in records:
            # Unknown team in games table; skip rather than crash.
            logger.warning("Game %s references unknown team(s): %s/%s", g.get("game_id"), home, away)
            continue

        _apply_game(records[home], opponent=away, mine=hs, theirs=as_, is_home=True, week=week)
        _apply_game(records[away], opponent=home, mine=as_, theirs=hs, is_home=False, week=week)

    # Pass 2: SOV / SOS using completed records.
    _compute_sov_sos(records)
    return records


def compute_standings_rows(
    *,
    season: int,
    through_week: Optional[int] = None,
    games: Optional[Iterable[Dict[str, Any]]] = None,
    teams: Optional[Iterable[Dict[str, Any]]] = None,
    client: Any = None,
) -> List[Dict[str, Any]]:
    """Top-level orchestrator: fetch → aggregate → rank → emit table rows.

    For testing, pass in-memory ``games`` and ``teams`` to skip Supabase.
    """
    # Always fetch the full schedule (no through_week clip). We need it
    # unclipped to identify the active 32-team roster — including pre-Week-1
    # snapshots where no game has been played yet.
    if games is None or teams is None:
        games, teams = fetch_inputs(season=season, through_week=None, client=client)
    games = list(games)

    # Drop historical franchise aliases (e.g. STL/LA/LAR all refer to the Rams
    # across eras). The teams table preserves every abbreviation a franchise
    # has ever used; for a given season only one is active. The season's
    # *schedule* is the source of truth — every active team appears in at
    # least one scheduled (REG) game even before kickoff. If the schedule
    # hasn't been loaded yet (rare: pre-May for the upcoming year), fall
    # back to keeping every row so the caller still gets a 32-team frame.
    rostered = {(g.get("home_team") or "").upper().strip() for g in games} | {
        (g.get("away_team") or "").upper().strip() for g in games
    }
    rostered.discard("")
    if rostered:
        teams = [t for t in teams if (t.get("team_abbr") or "").upper().strip() in rostered]

    # Now clip the games list by through_week for the records pass — the
    # roster filter above stays unaffected.
    if through_week is not None:
        record_games = [g for g in games if (g.get("week") or 0) <= int(through_week)]
    else:
        record_games = games

    records = build_team_records(games=record_games, teams=teams)

    # Resolve effective through_week: explicit arg, else max week with played games, else 0.
    if through_week is None:
        weeks = [int(g.get("week") or 0) for g in games if g.get("home_score") is not None and g.get("away_score") is not None]
        effective_through_week = max(weeks) if weeks else 0
    else:
        effective_through_week = int(through_week)

    # Group by division and rank.
    by_division: Dict[str, List[TeamRecord]] = {}
    for rec in records.values():
        if not rec.division:
            continue
        by_division.setdefault(rec.division, []).append(rec)

    division_order: Dict[str, List[Tuple[TeamRecord, List[str]]]] = {}
    for division, members in by_division.items():
        division_order[division] = rank_division(members, all_records=records)

    # Conference seeding: build per-conference list of (team, division_rank, trail).
    by_conference: Dict[str, List[Tuple[TeamRecord, int, List[str]]]] = {}
    for division, ordered in division_order.items():
        for idx, (rec, trail) in enumerate(ordered, start=1):
            by_conference.setdefault(rec.conference, []).append((rec, idx, trail))

    # Full conference ranking 1..N (typically 16). The seed 1..7 are
    # the playoff seeds; ranks 8..N are non-playoff order.
    conference_ranks: Dict[str, Dict[str, Tuple[int, List[str]]]] = {}
    for conference, members in by_conference.items():
        seeded = rank_conference(members, all_records=records)
        conference_ranks[conference] = {
            rec.team_abbr: (rank, trail) for rank, (rec, trail) in enumerate(seeded, start=1)
        }

    # League-wide ranking 1..N (typically 32). NFL does not define a strict
    # cross-conference tiebreaker order, so use the pragmatic ordering used
    # by broadcasters: win% → point diff → points scored → alphabetical.
    league_ranking = sorted(
        records.values(),
        key=lambda r: (-r.win_pct, -r.point_diff, -r.points_for, r.team_abbr),
    )
    league_ranks: Dict[str, int] = {
        rec.team_abbr: idx for idx, rec in enumerate(league_ranking, start=1)
    }

    rows: List[Dict[str, Any]] = []
    for division, ordered in division_order.items():
        for div_rank, (rec, div_trail) in enumerate(ordered, start=1):
            rank_info = conference_ranks.get(rec.conference, {}).get(rec.team_abbr)
            conf_rank = rank_info[0] if rank_info else None
            conf_trail = rank_info[1] if rank_info else []
            seed = conf_rank if (conf_rank is not None and conf_rank <= 7) else None
            trail = list(dict.fromkeys(div_trail + conf_trail))  # dedupe, preserve order
            tied = "COIN" in trail
            rows.append(
                {
                    "season": int(season),
                    "through_week": effective_through_week,
                    "team_abbr": rec.team_abbr,
                    "team_name": rec.team_name,
                    "conference": rec.conference,
                    "division": rec.division,
                    "wins": rec.wins,
                    "losses": rec.losses,
                    "ties": rec.ties,
                    "win_pct": round(rec.win_pct, 6),
                    "points_for": rec.points_for,
                    "points_against": rec.points_against,
                    "point_diff": rec.point_diff,
                    "division_record": _format_record(rec.div_wins, rec.div_losses, rec.div_ties),
                    "conference_record": _format_record(rec.conf_wins, rec.conf_losses, rec.conf_ties),
                    "home_record": _format_record(rec.home_wins, rec.home_losses, rec.home_ties),
                    "away_record": _format_record(rec.away_wins, rec.away_losses, rec.away_ties),
                    "last5": _format_last5(rec.game_log),
                    "streak": _format_streak(rec.game_log),
                    "division_rank": div_rank,
                    "conference_rank": conf_rank,
                    "conference_seed": seed,
                    "league_rank": league_ranks.get(rec.team_abbr),
                    "clinched": None,
                    "tiebreaker_trail": trail,
                    "tied": tied,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_game(
    rec: TeamRecord,
    *,
    opponent: str,
    mine: int,
    theirs: int,
    is_home: bool,
    week: int,
) -> None:
    rec.points_for += mine
    rec.points_against += theirs
    h2h = rec.head_to_head.setdefault(opponent, [0, 0, 0])
    rec.net_vs[opponent] = rec.net_vs.get(opponent, 0) + (mine - theirs)

    same_div = False
    same_conf = False
    # We don't have opponent metadata in this scope; division/conference splits
    # are filled by the caller with knowledge of all records. We resolve them
    # lazily here via a sentinel that the orchestrator fixes up — but cleaner
    # to do it in-place: caller has the records dict, so we expose a helper.
    # For simplicity, defer division/conference flags to a second pass below.
    if mine > theirs:
        rec.wins += 1
        h2h[0] += 1
        rec.game_log.append(("W", week))
        if is_home:
            rec.home_wins += 1
        else:
            rec.away_wins += 1
    elif mine < theirs:
        rec.losses += 1
        h2h[1] += 1
        rec.game_log.append(("L", week))
        if is_home:
            rec.home_losses += 1
        else:
            rec.away_losses += 1
    else:
        rec.ties += 1
        h2h[2] += 1
        rec.game_log.append(("T", week))
        if is_home:
            rec.home_ties += 1
        else:
            rec.away_ties += 1


def _compute_sov_sos(records: Dict[str, TeamRecord]) -> None:
    """Compute SOV/SOS and division/conference splits in a second pass."""
    # Division/conference splits depend on opponent metadata, so resolve here.
    for rec in records.values():
        for opp_abbr, (w, l, t) in rec.head_to_head.items():
            opp = records.get(opp_abbr)
            if opp is None:
                continue
            if opp.division == rec.division and rec.division:
                rec.div_wins += w
                rec.div_losses += l
                rec.div_ties += t
            if opp.conference == rec.conference and rec.conference:
                rec.conf_wins += w
                rec.conf_losses += l
                rec.conf_ties += t

    # SOV / SOS
    for rec in records.values():
        opp_records = [records[o] for o in rec.opponents if o in records]
        if not opp_records:
            rec.sos = 0.0
        else:
            rec.sos = sum(o.win_pct for o in opp_records) / len(opp_records)
        defeated = [records[o] for o in rec.defeated_opponents if o in records]
        if not defeated:
            rec.sov = 0.0
        else:
            rec.sov = sum(o.win_pct for o in defeated) / len(defeated)


def _format_record(w: int, l: int, t: int) -> str:
    if t:
        return f"{w}-{l}-{t}"
    return f"{w}-{l}"


def _format_last5(game_log: Sequence[Tuple[str, int]]) -> str:
    last = list(game_log)[-5:]
    if not last:
        return ""
    w = sum(1 for o, _ in last if o == "W")
    l = sum(1 for o, _ in last if o == "L")
    t = sum(1 for o, _ in last if o == "T")
    return _format_record(w, l, t)


def _format_streak(game_log: Sequence[Tuple[str, int]]) -> str:
    if not game_log:
        return ""
    last_outcome = game_log[-1][0]
    n = 0
    for o, _ in reversed(game_log):
        if o == last_outcome:
            n += 1
        else:
            break
    return f"{last_outcome}{n}"
