"""NFL division and conference tiebreaker cascades.

The cascade is implemented as a list of comparator steps. Each step partitions
its input group into ordered sub-groups (better → worse). When a step produces
sub-groups smaller than the input, the partitioning is recorded in each
team's ``tiebreaker_trail`` and the cascade recurses on each sub-group.

Returns lists of ``(TeamRecord, trail)`` ordered from best to worst.

Notes / known limitations
-------------------------
* ``Net touchdowns`` (NFL step 11 division / step 10 wild-card) is **skipped**
  because per-team TD data is not stored on the ``games`` row.
* Final fallback is a deterministic alphabetical sort labelled ``COIN``;
  any team placed via this step has ``tied=True`` in the resulting standings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List, Sequence, Tuple

if TYPE_CHECKING:
    from .compute import TeamRecord


Trail = List[str]
Group = List["TeamRecord"]
Comparator = Callable[[Group, Dict[str, "TeamRecord"]], List[Group]]


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def rank_division(
    members: Group,
    *,
    all_records: Dict[str, "TeamRecord"],
) -> List[Tuple["TeamRecord", Trail]]:
    """Order teams within a single division using NFL division tiebreakers."""
    return _run_cascade(members, _DIVISION_STEPS, all_records=all_records)


def rank_conference(
    division_winners_first: Sequence[Tuple["TeamRecord", int, Trail]],
    *,
    all_records: Dict[str, "TeamRecord"],
) -> List[Tuple["TeamRecord", Trail]]:
    """Order teams within a conference for seeds 1..N.

    ``division_winners_first`` is a list of ``(team, division_rank, trail)``
    tuples for every team in the conference. Seeds 1-4 go to the four
    division winners (division_rank == 1), tied among themselves with the
    conference cascade. Remaining seeds use the wild-card cascade with the
    "one-team-per-division" eligibility rule.
    """
    by_div_rank: Dict[int, List[Tuple["TeamRecord", Trail]]] = {}
    for rec, div_rank, trail in division_winners_first:
        by_div_rank.setdefault(div_rank, []).append((rec, list(trail)))

    seeded: List[Tuple["TeamRecord", Trail]] = []

    # Seeds 1-4: the four division winners.
    div_winners = [item[0] for item in by_div_rank.get(1, [])]
    if div_winners:
        winner_trails = {rec.team_abbr: trail for rec, trail in by_div_rank.get(1, [])}
        ordered_winners = _run_cascade(div_winners, _CONFERENCE_STEPS, all_records=all_records)
        for rec, trail in ordered_winners:
            seeded.append((rec, _merge_trails(winner_trails.get(rec.team_abbr, []), trail)))

    # Wild-card: at most one team per division eligible at any time. Iterate
    # by current division rank (2, 3, 4...) — each tier produces a pool of
    # eligible teams across divisions, ranked by the conference cascade.
    next_idx_per_div: Dict[str, int] = {}
    for rec, _trail in [item for tier in sorted(by_div_rank.keys()) for item in by_div_rank[tier] if tier > 1]:
        next_idx_per_div.setdefault(rec.division, 0)

    # Build per-division ordered lists of (rec, trail) for non-winners.
    per_div_queue: Dict[str, List[Tuple["TeamRecord", Trail]]] = {}
    for tier in sorted(by_div_rank.keys()):
        if tier == 1:
            continue
        for rec, trail in by_div_rank[tier]:
            per_div_queue.setdefault(rec.division, []).append((rec, trail))

    while True:
        eligible: List[Tuple["TeamRecord", Trail]] = []
        for div, queue in per_div_queue.items():
            idx = next_idx_per_div.get(div, 0)
            if idx < len(queue):
                eligible.append(queue[idx])
        if not eligible:
            break
        ordered = _run_cascade([rec for rec, _ in eligible], _CONFERENCE_STEPS, all_records=all_records)
        # Take the top of the ordered group, advance that division's pointer.
        top_rec, top_trail = ordered[0]
        seeded.append(
            (
                top_rec,
                _merge_trails(
                    next(t for r, t in eligible if r.team_abbr == top_rec.team_abbr),
                    top_trail,
                ),
            )
        )
        next_idx_per_div[top_rec.division] = next_idx_per_div.get(top_rec.division, 0) + 1

    return seeded


# ---------------------------------------------------------------------------
# Cascade engine
# ---------------------------------------------------------------------------


def _run_cascade(
    members: Group,
    steps: List[Tuple[str, Comparator]],
    *,
    all_records: Dict[str, "TeamRecord"],
) -> List[Tuple["TeamRecord", Trail]]:
    """Recursively partition ``members`` until each sub-group has size 1."""
    if len(members) <= 1:
        return [(m, []) for m in members]

    # Step 0 is always overall win-pct.
    groups = _split_by(members, key=lambda r: -r.win_pct)
    if len(groups) == len(members):
        return [(g[0], ["WPCT"]) for g in groups]

    out: List[Tuple["TeamRecord", Trail]] = []
    for group in groups:
        if len(group) == 1:
            out.append((group[0], ["WPCT"]))
            continue
        # Apply tiebreaker cascade.
        ordered_subs = _apply_steps(group, steps, all_records=all_records)
        for rec, trail in ordered_subs:
            out.append((rec, ["WPCT", *trail]))
    return out


def _apply_steps(
    members: Group,
    steps: List[Tuple[str, Comparator]],
    *,
    all_records: Dict[str, "TeamRecord"],
) -> List[Tuple["TeamRecord", Trail]]:
    if len(members) == 1:
        return [(members[0], [])]
    for label, comparator in steps:
        partitioned = comparator(members, all_records)
        if len(partitioned) == 1:
            continue  # this step didn't split anything
        out: List[Tuple["TeamRecord", Trail]] = []
        for sub in partitioned:
            if len(sub) == 1:
                out.append((sub[0], [label]))
            else:
                # Recurse: drop steps already applied? In strict NFL rules each
                # step is applied once, but a sub-group must restart from the
                # top of the *remaining* cascade. Drop steps up through and
                # including the current one to avoid revisiting it.
                remaining = steps[steps.index((label, comparator)) + 1 :]
                tail = _apply_steps(sub, remaining, all_records=all_records)
                for rec, sub_trail in tail:
                    out.append((rec, [label, *sub_trail]))
        return out
    # No step split the group → coin flip (deterministic alphabetical fallback).
    ordered = sorted(members, key=lambda r: r.team_abbr)
    return [(rec, ["COIN"]) for rec in ordered]


def _split_by(group: Group, *, key: Callable[["TeamRecord"], object]) -> List[Group]:
    """Partition ``group`` into runs that share the same ``key`` value, ordered by key."""
    if not group:
        return []
    decorated = sorted(group, key=lambda r: (key(r), r.team_abbr))
    out: List[Group] = []
    current: Group = [decorated[0]]
    current_key = key(decorated[0])
    for rec in decorated[1:]:
        k = key(rec)
        if k == current_key:
            current.append(rec)
        else:
            out.append(current)
            current = [rec]
            current_key = k
    out.append(current)
    return out


def _merge_trails(a: Trail, b: Trail) -> Trail:
    out: Trail = []
    for x in [*a, *b]:
        if x not in out:
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# Comparator steps
# ---------------------------------------------------------------------------


def _step_head_to_head(group: Group, _all: Dict[str, "TeamRecord"]) -> List[Group]:
    """Sweep rule: a team with a winning H2H record vs. *all* others advances.

    For 2-team groups: standard better-record. For 3+ teams: only applies if a
    single team has a winning record vs. every other member (sweep). If
    multiple do, partition accordingly.
    """
    if len(group) == 2:
        a, b = group
        a_wlt = a.head_to_head.get(b.team_abbr, [0, 0, 0])
        if a_wlt[0] > a_wlt[1]:
            return [[a], [b]]
        if a_wlt[1] > a_wlt[0]:
            return [[b], [a]]
        return [group]

    # 3+ teams: bucket by H2H win% within the group.
    pcts: Dict[str, float] = {}
    for rec in group:
        gp = w = t = 0
        for opp in group:
            if opp is rec:
                continue
            wlt = rec.head_to_head.get(opp.team_abbr, [0, 0, 0])
            w += wlt[0]
            t += wlt[2]
            gp += sum(wlt)
        pcts[rec.team_abbr] = (w + 0.5 * t) / gp if gp else 0.5

    return _split_by(group, key=lambda r: -pcts.get(r.team_abbr, 0.5))


def _step_division_record(group: Group, _all: Dict[str, "TeamRecord"]) -> List[Group]:
    return _split_by(group, key=lambda r: -_pct(r.div_wins, r.div_losses, r.div_ties))


def _step_common_games(group: Group, _all: Dict[str, "TeamRecord"]) -> List[Group]:
    """Common-games record. Requires each team to have ≥4 common opponents."""
    common_opponents = set.intersection(*[set(r.opponents) for r in group]) if group else set()
    if len(common_opponents) < 4:
        return [group]
    pcts: Dict[str, float] = {}
    for rec in group:
        w = l = t = 0
        for opp in common_opponents:
            wlt = rec.head_to_head.get(opp, [0, 0, 0])
            w += wlt[0]
            l += wlt[1]
            t += wlt[2]
        pcts[rec.team_abbr] = _pct(w, l, t)
    return _split_by(group, key=lambda r: -pcts[r.team_abbr])


def _step_conference_record(group: Group, _all: Dict[str, "TeamRecord"]) -> List[Group]:
    return _split_by(group, key=lambda r: -_pct(r.conf_wins, r.conf_losses, r.conf_ties))


def _step_strength_of_victory(group: Group, _all: Dict[str, "TeamRecord"]) -> List[Group]:
    return _split_by(group, key=lambda r: -r.sov)


def _step_strength_of_schedule(group: Group, _all: Dict[str, "TeamRecord"]) -> List[Group]:
    return _split_by(group, key=lambda r: -r.sos)


def _step_conf_points_rank(group: Group, all_records: Dict[str, "TeamRecord"]) -> List[Group]:
    """Combined ranking among conference teams in points scored & allowed.

    NFL rule: best conference rank in points scored *plus* best conference
    rank in points allowed (lower combined rank wins).
    """
    if not group:
        return [group]
    conf = group[0].conference
    conf_teams = [r for r in all_records.values() if r.conference == conf]
    return _combined_points_rank(group, conf_teams)


def _step_overall_points_rank(group: Group, all_records: Dict[str, "TeamRecord"]) -> List[Group]:
    return _combined_points_rank(group, list(all_records.values()))


def _combined_points_rank(group: Group, universe: List["TeamRecord"]) -> List[Group]:
    pf_rank = _rank_desc(universe, key=lambda r: r.points_for)
    pa_rank = _rank_asc(universe, key=lambda r: r.points_against)
    combined: Dict[str, int] = {}
    for rec in group:
        combined[rec.team_abbr] = pf_rank.get(rec.team_abbr, len(universe)) + pa_rank.get(rec.team_abbr, len(universe))
    return _split_by(group, key=lambda r: combined[r.team_abbr])


def _step_net_common(group: Group, _all: Dict[str, "TeamRecord"]) -> List[Group]:
    common_opponents = set.intersection(*[set(r.opponents) for r in group]) if group else set()
    if not common_opponents:
        return [group]
    nets: Dict[str, int] = {}
    for rec in group:
        nets[rec.team_abbr] = sum(rec.net_vs.get(opp, 0) for opp in common_opponents)
    return _split_by(group, key=lambda r: -nets[r.team_abbr])


def _step_net_overall(group: Group, _all: Dict[str, "TeamRecord"]) -> List[Group]:
    return _split_by(group, key=lambda r: -r.point_diff)


# ---------------------------------------------------------------------------
# Step lists
# ---------------------------------------------------------------------------


_DIVISION_STEPS: List[Tuple[str, Comparator]] = [
    ("H2H", _step_head_to_head),
    ("DIV", _step_division_record),
    ("COMMON", _step_common_games),
    ("CONF", _step_conference_record),
    ("SOV", _step_strength_of_victory),
    ("SOS", _step_strength_of_schedule),
    ("CONF_PTS", _step_conf_points_rank),
    ("ALL_PTS", _step_overall_points_rank),
    ("NET_COMMON", _step_net_common),
    ("NET_ALL", _step_net_overall),
]


_CONFERENCE_STEPS: List[Tuple[str, Comparator]] = [
    # Wild-card cascade per NFL: H2H sweep (only if applicable) → conference
    # record → common-games (≥4) → SOV → SOS → conference points rank →
    # overall points rank → net conference points → net overall points.
    ("H2H", _step_head_to_head),
    ("CONF", _step_conference_record),
    ("COMMON", _step_common_games),
    ("SOV", _step_strength_of_victory),
    ("SOS", _step_strength_of_schedule),
    ("CONF_PTS", _step_conf_points_rank),
    ("ALL_PTS", _step_overall_points_rank),
    ("NET_COMMON", _step_net_common),
    ("NET_ALL", _step_net_overall),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pct(w: int, l: int, t: int) -> float:
    gp = w + l + t
    if gp == 0:
        return 0.0
    return (w + 0.5 * t) / gp


def _rank_desc(universe: List["TeamRecord"], *, key: Callable[["TeamRecord"], int]) -> Dict[str, int]:
    """Return rank (1 = highest key) per team_abbr; ties share the lower rank."""
    sorted_teams = sorted(universe, key=lambda r: (-key(r), r.team_abbr))
    out: Dict[str, int] = {}
    last_val = None
    last_rank = 0
    for idx, rec in enumerate(sorted_teams, start=1):
        v = key(rec)
        if v != last_val:
            last_rank = idx
            last_val = v
        out[rec.team_abbr] = last_rank
    return out


def _rank_asc(universe: List["TeamRecord"], *, key: Callable[["TeamRecord"], int]) -> Dict[str, int]:
    """Return rank (1 = lowest key) per team_abbr; ties share the lower rank."""
    sorted_teams = sorted(universe, key=lambda r: (key(r), r.team_abbr))
    out: Dict[str, int] = {}
    last_val = None
    last_rank = 0
    for idx, rec in enumerate(sorted_teams, start=1):
        v = key(rec)
        if v != last_val:
            last_rank = idx
            last_val = v
        out[rec.team_abbr] = last_rank
    return out
