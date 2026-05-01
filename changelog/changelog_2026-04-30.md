# Changelog — 2026-04-30

## Summary
Fixed a critical standings ranking bug in `_run_cascade` where the early-exit path for all-distinct win percentages iterated over unsorted input instead of the already-sorted partitions, producing wrong division ranks and conference seeds. Also committed the full standings module (compute, tiebreakers, loader, CLI, workflow, schema, and tests) that was built in prior sessions but never staged.

## Changes

### Bug Fix
- **`_run_cascade` early-return iterates sorted `groups` not raw `members`** — when every team in a group had a distinct win percentage, the function returned ranks in original (unsorted) input order instead of win-pct descending order. Concrete bad outcomes: NE (14-3) ranked 3rd in AFC East behind DAL (7-9-1) ranked 1st in NFC East, and ARI (3-14) placed as NFC seed 7. Fix: `return [(g[0], ["WPCT"]) for g in groups]`.

### New Module: Standings (prior sessions, now committed)
- **`src/functions/data_loading/core/standings/compute.py`** — `TeamRecord` dataclass + full standings computation: W/L/T/ties, win%, home/away splits, streak, last-5, division record, conference record, point differentials.
- **`src/functions/data_loading/core/standings/tiebreakers.py`** — Full NFL tiebreaker cascade (H2H, division record, common games >=4, conference record, SoV, SoS, conference/overall points ranks, net points, alphabetical fallback). Division and wild-card seeding logic. `tiebreaker_trail` and `tied` fields.
- **`src/functions/data_loading/core/data/loaders/standings/standings.py`** — `StandingsDataLoader`: reads games + teams from Supabase, calls compute + tiebreakers, upserts `(season, through_week, team_abbr)` keyed rows into the `standings` table.
- **`src/functions/data_loading/scripts/standings_cli.py`** — CLI with `--season`, `--through-week`, `--dry-run`, `--json`, `--show`, `--conference`, `--division` flags.
- **`.github/workflows/standings-recompute.yml`** — Runs after the games-loader workflow succeeds (workflow_run trigger) and as a Tue/Wed morning safety-net cron. Accepts optional `season` and `through_week` inputs via `workflow_dispatch`.
- **`docs/standings_schema.sql`** — Table DDL, indexes, and public-read RLS policy for the `standings` table.

### Documentation & Minor Fixes
- **`src/functions/data_loading/README.md`** — Added full Standings Loader section: CLI usage, schema bootstrap, ranking fields, tiebreaker trail, known limitations, Flutter consumption snippet.
- **`src/functions/data_loading/core/data/transformers/team.py`** — `conference` field resolution now also checks `team_conf` column (used by `nflreadpy.load_teams()`).

### Tests
- **`tests/data_loading/test_standings_tiebreakers.py`** — 4 tests covering H2H two-team tie, three-way division tie, conference seeding with 4 division winners + 1 wild-card, and coin-flip only on truly identical records.
- **`tests/data_loading/test_standings_compute.py`** — 13 tests covering clean records, tie counting, incomplete game skipping, home/away splits, streak/last-5, through-week filtering, division ranking, conference seeding, historical alias handling, offseason snapshots, and row schema shape.
- **`tests/data_loading/test_standings_loader.py`** — Loader integration tests (collection fails in root venv due to missing `pandas`; runs fine inside the `data_loading` module venv).

## Files Modified
- `src/functions/data_loading/core/standings/tiebreakers.py` — bug fix: `_run_cascade` early-return now uses sorted `groups`
- `src/functions/data_loading/core/standings/compute.py` — new: standings computation logic
- `src/functions/data_loading/core/standings/__init__.py` — new: module init
- `src/functions/data_loading/core/data/loaders/standings/standings.py` — new: Supabase loader
- `src/functions/data_loading/core/data/loaders/standings/__init__.py` — new: loader init
- `src/functions/data_loading/scripts/standings_cli.py` — new: CLI entrypoint
- `src/functions/data_loading/README.md` — updated: Standings Loader section added
- `src/functions/data_loading/core/data/transformers/team.py` — updated: `team_conf` column alias
- `.github/workflows/standings-recompute.yml` — new: automation workflow
- `docs/standings_schema.sql` — new: table DDL + RLS policy
- `tests/data_loading/test_standings_tiebreakers.py` — new: 4 tiebreaker tests
- `tests/data_loading/test_standings_compute.py` — new: 13 compute tests
- `tests/data_loading/test_standings_loader.py` — new: loader integration tests

## Code Quality Notes
- **Tests (tiebreakers + compute):** 17/17 PASSED (`test_standings_tiebreakers.py` + `test_standings_compute.py`).
- **Tests (loader):** Collection error — `ModuleNotFoundError: No module named 'pandas'` in the root venv. This is a pre-existing environment issue; the loader tests run correctly inside the `data_loading` module venv. Not a code defect.
- **Linting:** No obvious issues — no TODOs, FIXMEs, debug print statements, or commented-out code blocks found in the changed files.

## Open Items / Carry-over
- `test_standings_loader.py` requires `pandas` in the root venv (or a pytest marker to skip when unavailable). Consider adding `pytest.importorskip("pandas")` at the top of that file to prevent collection failures in CI.
- `clinched` flags in standings rows are always `null` in v1. The field is reserved for a future session when week-by-week playoff elimination logic is added.
- Net-touchdowns tiebreaker is skipped (not present in the `games` schema). Document the omission or add the column if needed.
