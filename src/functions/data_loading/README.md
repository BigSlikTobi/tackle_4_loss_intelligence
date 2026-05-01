# Data Loading Function

This module handles NFL data ingestion, transformation, and on-demand package
assembly.

## 🎯 Purpose

Load NFL data from various sources (nflreadpy, Pro Football Reference, etc.)
into Supabase and provide on-demand package assembly via HTTP API.

## 🚀 Quick Start

### Local Development

```bash
cd src/functions/data_loading
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your Supabase credentials

# Run data loaders
python scripts/players_cli.py --dry-run
python scripts/games_cli.py --season 2024 --clear
python scripts/player_weekly_stats_cli.py --season 2024 --week 1
```

### Deploy to Cloud Functions

```bash
cd functions
./check_requirements.sh
./deploy.sh
```

### Test Locally

```bash
cd functions
./run_local.sh

# In another terminal
./test_function.sh
```

### Testing & Deployment Notes

- `functions/run_local.sh` bootstraps a venv, installs dependencies, exports
  `PYTHONPATH` to the repo root, and starts Functions Framework on
  `http://localhost:8080`. Use `functions/test_function.sh` or
  `curl -d @requests/*.json` to keep exercising the handler while iterating.
- For manual sessions run from the repo root, set
  `export PYTHONPATH="$(pwd):$PYTHONPATH"`, `source .env`, and launch
  `functions-framework --target=package_handler --source=src/functions/data_loading/functions --port=8080 --debug`.
- Cloud deployments expect a module-specific `.env.yaml` (Supabase URL/key, log
  level). The hardened `deploy.sh` copies the source tree into a temporary
  directory and deploys from there so real repo files are never overwritten.
- If Cloud Functions throws import errors after deploy, confirm you ran from the
  project root, that `.gcloudignore` is not excluding `src/`, and that
  `.env.yaml` matches your local configuration.
  `gcloud functions logs read package-handler --region=<region> --limit=50`
  surfaces stack traces quickly.

## 📦 Structure

```
data_loading/
├── core/                    # Core functionality
│   ├── contracts/          # Data contracts and models
│   ├── data/               # Data loaders and transformers
│   │   ├── loaders/       # Source-specific loaders
│   │   └── transformers/  # Data transformation logic
│   ├── db/                 # Database initialization
│   ├── packaging/          # Package assembly service
│   ├── pipelines/          # Data pipeline orchestration
│   ├── providers/          # On-demand data providers
│   └── utils/              # CLI and utilities
├── scripts/                # CLI tools for data loading
├── functions/              # Cloud Function deployment
│   ├── main.py            # Entry point
│   ├── deploy.sh          # Deployment script
│   └── requirements.txt   # Function dependencies
├── tests/                  # Unit tests
├── requirements.txt        # Development dependencies
├── .env.example           # Example environment config
└── README.md              # This file
```

## 🔧 Configuration

Required environment variables:

- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_KEY`: Supabase service role key
- `LOG_LEVEL`: Logging level (default: INFO)

## 📊 Data Loaders

### Players Loader

```bash
python scripts/players_cli.py [--clear] [--dry-run] [--verbose]
```

### Games Loader

```bash
python scripts/games_cli.py --season 2024 [--clear] [--dry-run]
```

### Player Weekly Stats

```bash
python scripts/player_weekly_stats_cli.py --season 2024 --week 1 [--dry-run]
```

### Teams Loader

```bash
python scripts/teams_cli.py [--clear] [--dry-run]
```

### Rosters Loader

```bash
python scripts/rosters_cli.py --season 2024 [--clear] [--dry-run]
```

### Depth Charts Loader

```bash
python scripts/depth_charts_cli.py --season 2024 --week 1 [--clear] [--dry-run]
```

### Injuries Loader

```bash
python scripts/injuries_cli.py --season 2025 --week 6 [--season-type reg] [--dry-run]
```

The injury workflow scrapes nfl.com reports, performs fuzzy player resolution,
and writes history-preserving rows keyed by
`(season, week, season_type, team_abbr, player_id)`. Highlights:

- **Database schema:** run `schema_injuries.sql` to create the `injuries` table
  with versioned primary key plus timestamps (`last_update`, `created_at`,
  `updated_at`). Historical queries (e.g., recovery timelines) are now simple
  grouping queries.
- **CLI flags:** `--season`, `--week`, optional `--season-type {pre,reg,post}`,
  `--dry-run`, `--log-level`. Use `scripts/get_current_week.py [--json]` to
  auto-detect the current week/season type when automating.
- **Automation:** `.github/workflows/injuries-daily.yml` runs nightly at 6 PM
  ET, leveraging automatic week detection and retry logic. Set `LOG_LEVEL=DEBUG`
  for verbose Supabase logging when troubleshooting.
- **Loaders**: Fetch data from NFLReadPy and store in DB.
- **Sync**: Utility to sync data from a Live/Prod Supabase instance to
  Local/Dev.
- **Package**: Assemble weekly data packages for the frontend (games, rosters,
  stats).
- **Maintenance**: Utilities for current week detection and cleanup.
- **Player resolution:** uses scraped IDs when present, otherwise falls back to
  name + team + Levenshtein distance against the `players` table. Unresolved
  players log warnings so you can add them via the players loader.
- **Common SQL snippets:**
  - Current-week snapshot:
    `SELECT team_abbr, player_name, injury, game_status FROM injuries WHERE season=2025 AND week=6 AND season_type='REG';`
  - Recovered players: compare week N vs week N+1 with a `LEFT JOIN` to find
    absences.
  - Recurring injuries:
    `SELECT player_name, COUNT(*) FROM injuries WHERE season=2025 AND season_type='REG' GROUP BY player_name HAVING COUNT(*)>3;`
- **Troubleshooting:** missing table errors mean the schema script wasn’t run;
  wrong week detection means updating the start-date constants in
  `scripts/get_current_week.py`; `ModuleNotFoundError: src` indicates
  `PYTHONPATH` was not pointed at the repo root.

### Standings Loader

```bash
python scripts/standings_cli.py [--season 2024] [--through-week 18] [--dry-run]
python scripts/standings_cli.py --show --conference AFC      # read-back AFC seeds 1-7
python scripts/standings_cli.py --show --division "AFC East" # read-back one division
```

Computes NFL standings on top of the persisted `games` + `teams` tables and
upserts one row per team into the `standings` table, keyed on
`(season, through_week, team_abbr)`. Historical snapshots are preserved.

- **Database schema:** run `docs/standings_schema.sql` once via the Supabase
  SQL editor. The script creates the table, the supporting indexes, and a
  public-read RLS policy so the Flutter client can read with the anon key.
- **Rankings produced per row:** `division_rank` (1–4 within the division),
  `conference_rank` (1–N within the conference, full ordering — playoff and
  non-playoff teams), `conference_seed` (1–7 — playoff seeds only, otherwise
  null), and `league_rank` (1–N across all 32 teams, ordered by win% →
  point diff → points scored → alphabetical).
- **Tiebreakers:** full NFL division and wild-card cascades — head-to-head,
  division record, common-games (≥4), conference record, strength of victory,
  strength of schedule, conference + overall points ranks, and net point
  totals. Each team's `tiebreaker_trail` JSONB column records which step
  finalized its placement (`["WPCT","H2H"]`, `["WPCT","DIV"]`, etc.). The
  `tied` boolean flags any team that fell through to the deterministic
  alphabetical fallback (extremely rare).
- **Known limitations:** net-touchdowns tiebreaker is skipped (not in the
  `games` schema); `clinched` flags are reserved but always `null` in v1.
- **CLI flags:** `--season`, `--through-week N`, `--dry-run`, `--json`,
  plus `--show` / `--conference` / `--division` for read-back.
- **Automation:** `.github/workflows/standings-recompute.yml` runs after the
  games loader workflow succeeds (workflow_run trigger) and as a Tue/Wed
  morning safety-net cron. Manual runs via `workflow_dispatch` accept
  optional `season` and `through_week` inputs.
- **Flutter consumption:** read directly from Supabase with the anon key:

  ```dart
  final rows = await supabase
      .from('standings')
      .select()
      .eq('season', 2024)
      .eq('through_week', 18)
      .eq('conference', 'AFC')
      .order('conference_seed', nullsFirst: false);
  ```

  No HTTP function call needed; standings are precomputed.

## Syncing Data from Live ➡️ Local

You can sync data from a "Live" (Source) Supabase instance to your "Local"
(Target) instance using `sync_data_cli.py`.

### Prerequisites

Ensure your local `.env` file has the following variables:

- `SUPABASE_URL` / `SUPABASE_KEY`: Connection to the **Source (Live)** instance.
- `SUPABASE_URL_DEV` / `SUPABASE_KEY_DEV`: Connection to the **Target (Local)**
  instance.

### Usage

```bash
# Sync specific tables (defaults to 100 records)
python scripts/sync_data_cli.py --tables teams games --limit 50

# Sync with schema notation (e.g. content.articles)
python scripts/sync_data_cli.py --tables content.articles --limit 50

# Sync ALL data (fetches everything in pages of 1000)
python scripts/sync_data_cli.py --tables teams --all

# Wipe target table before syncing (Use with caution!)
python scripts/sync_data_cli.py --tables teams --all --wipe

# Dry Run (see what would happen)
python scripts/sync_data_cli.py --tables teams --all --wipe --dry-run
```

## 🌐 API

### POST /package-handler

Assemble on-demand data packages.

**Request:**

```json
{
  "schema_version": "1.0.0",
  "producer": "client-id",
  "subject": {
    "entity_type": "player",
    "entity_id": "00-0012345"
  },
  "scope": {
    "temporal": {
      "season": 2024,
      "week": 1
    }
  },
  "provenance": {
    "sources": ["player_weekly_stats"]
  },
  "bundles": [
    {
      "provider": "player_weekly_stats",
      "stream": "weekly_stats"
    }
  ]
}
```

**Response:**

```json
{
  "schema_version": "1.0.0",
  "producer": "client-id",
  "subject": {...},
  "scope": {...},
  "provenance": {...},
  "payload": {
    "player_stats": [...],
    "metadata": {...}
  }
}
```

## 🏗️ Architecture

See `docs/firebase_function.md` for detailed architecture and deployment flow.

## 🧪 Testing

```bash
# Run unit tests (when implemented)
pytest tests/

# Manual testing with dry-run
python scripts/players_cli.py --dry-run --verbose
```

## 📚 Documentation

- [Package Contract](../../../docs/package_contract.md)
- [Firebase Function Architecture](../../../docs/firebase_function.md)
- [Dataset Stream Matrix](../../../docs/dataset_stream_matrix.svg)
