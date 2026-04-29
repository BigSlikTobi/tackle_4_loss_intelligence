# Changelog — 2026-04-29

## Summary
Migrated the `data_loading` module to a new Supabase project, with a full CLI/UX overhaul across all six NFL data pipeline CLIs and their backing loaders. A new shared season-detection utility eliminates hardcoded year constants throughout scripts and GitHub Actions workflows.

## Changes

### New Shared Utility
- Added `src/functions/data_loading/core/utils/season.py` with:
  - `get_current_season()` — uses March as the NFL league year threshold (April 2026 correctly returns 2026)
  - `get_current_week_and_season_type()` — auto-detects current week and season type
  - `is_in_season()` — returns False during the offseason; used by CLIs to short-circuit with a friendly message

### CLI Scripts (6 files overhauled)
- `depth_charts_cli.py`, `games_cli.py`, `injuries_cli.py`, `players_cli.py`, `rosters_cli.py`, `teams_cli.py`
  - Added `--show` read-only viewer modes to all applicable CLIs
  - Auto-detect season/week defaults via new `season.py` helper (removes hardcoded `--season YYYY`)
  - Removed phantom `--clear` flags that had no implementation
  - Added post-load summary rollups for observability
  - Deleted `get_current_week.py` (absorbed into `season.py`)

### Loaders (4 files optimized)
- `depth_charts.py` — batched N+1 versioning queries into single per-(season, week) round trips
- `injuries.py` — replaced full-table players scan with last-name targeted query; switched data source from nfl.com (returning 404s) to ESPN, guarded by `_is_current_live_scope()` to prevent stamping historical weeks with today's live data
- `games.py` — dropped custom delete-then-insert writer in favour of base `SupabaseWriter` with `conflict_columns=["game_id"]` for atomic upserts
- `rosters.py` — fixed `dept_chart_position` → `depth_chart_position` typo; added per-team latest-week selection

### Shared Data Fetch Layer
- `src/functions/data_loading/core/data/fetch.py` — updated to support new Supabase project credentials and revised query patterns
- `src/functions/data_loading/core/data/transformers/player.py` — minor transformer adjustments for new loader contracts

### GitHub Actions Workflows (trimmed)
- Removed hardcoded `--season YYYY` / `--min-last-season YYYY` from 5 active workflows: `depth-charts-daily.yml`, `games-schedule.yml`, `injuries-daily.yml`, `players-daily.yml`, `rosters-daily.yml`
- Hard-deleted 13 deprecated workflows that wrote into the old Supabase project (article-knowledge-cleanup, content-facts-entities-realtime, content-pipeline-create, content-pipeline-poll, content-summarization, entities-realtime, facts-realtime, knowledge-extraction, news-extraction, news-extraction-cleanup, story-embeddings, story-grouping, url-content-extraction-cleanup). Source modules are retained; they are now invoked via Cloud Functions rather than Actions.

### Database (SQL run directly in Supabase by user)
- Created/updated tables: `injuries`, `depth_charts`, `rosters`
- Added views: `depth_charts_current`, `rosters_current`, `players_current`, `teams_summary`
- Added unique constraint: `games_game_id_key`

## Files Modified
- `src/functions/data_loading/core/utils/season.py` — new file
- `src/functions/data_loading/core/data/fetch.py` — Supabase migration + query updates
- `src/functions/data_loading/core/data/loaders/game/games.py` — atomic upsert refactor
- `src/functions/data_loading/core/data/loaders/injury/injuries.py` — ESPN source + scope guard
- `src/functions/data_loading/core/data/loaders/player/depth_charts.py` — batched versioning
- `src/functions/data_loading/core/data/loaders/player/rosters.py` — typo fix + week selection
- `src/functions/data_loading/core/data/transformers/player.py` — transformer adjustments
- `src/functions/data_loading/scripts/depth_charts_cli.py` — --show, auto-season, rollup
- `src/functions/data_loading/scripts/games_cli.py` — --show, auto-season, rollup
- `src/functions/data_loading/scripts/injuries_cli.py` — --show, auto-season, rollup
- `src/functions/data_loading/scripts/players_cli.py` — --show, auto-season, rollup
- `src/functions/data_loading/scripts/rosters_cli.py` — --show, auto-season, rollup
- `src/functions/data_loading/scripts/teams_cli.py` — auto-season, rollup
- `src/functions/data_loading/scripts/get_current_week.py` — deleted (merged into season.py)
- `.github/workflows/depth-charts-daily.yml` — removed hardcoded year args
- `.github/workflows/games-schedule.yml` — removed hardcoded year args
- `.github/workflows/injuries-daily.yml` — removed hardcoded year args
- `.github/workflows/players-daily.yml` — removed hardcoded year args
- `.github/workflows/rosters-daily.yml` — removed hardcoded year args
- 13 deprecated `.github/workflows/*.yml` — deleted

## Code Quality Notes
- Tests: SKIPPED — `pytest` and module deps (`pandas`) not installed in the global Python environment; this is the pre-existing baseline for this repo (venv required per module)
- Linting: not run (no project-wide lint command configured)
- No debug print statements, TODO/FIXME comments, or commented-out code blocks observed in the changed files

## Open Items / Carry-over
- Scheduled remote agent (trigger ID `trig_01J7GCtiKdUAw5ah1tghGMja`) fires 2026-08-03 09:00 UTC to open a PR bumping `season.py` constants for the 2026 NFL season — no manual action needed
- Local branch `migrate-data-loading-to-new-supabase` still exists locally and on origin post squash-merge; delete when convenient (`git branch -d migrate-data-loading-to-new-supabase && git push origin --delete migrate-data-loading-to-new-supabase`)
- The 13 deleted workflows had corresponding source modules that are still present in `src/functions/`; confirm with team whether any cloud function deploys for those modules are still active or can be decommissioned
