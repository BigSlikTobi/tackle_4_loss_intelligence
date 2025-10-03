# Cloud Function API

> **Part of**: [`src/functions/data_loading/`](../src/functions/data_loading/)

The data loading module includes a Python-based Cloud Function that wraps the package assembly service behind an HTTP API. Deploy this function to allow downstream systems to request on-demand analytics packages via HTTP.

## Overview

**Purpose**: Provide HTTP access to on-demand analytics packages (play-by-play, stats, Next Gen Stats, etc.)

**Architecture**:
```
Client Request (HTTP POST)
    ↓
Google Cloud Functions (Gen 2)
    ↓
package_handler (functions/main.py)
    ↓
assemble_package (core/packaging/service.py)
    ↓
Providers (pbp, pfr, ngs, snap_counts, etc.)
    ↓
JSON Response
```

⚠️ **Scope**: The HTTP API only returns **on-demand analytics bundles**. Warehouse datasets (`teams`, `players`, `rosters`, `depth_charts`, `games`) are loaded via CLI scripts and stored in Supabase—they are **not** exposed through this endpoint.

## Files

**Entry Point**: [`src/functions/data_loading/functions/main.py`](../src/functions/data_loading/functions/main.py)
- `package_handler()` – HTTP entry point that parses requests, invokes `assemble_package()`, and returns JSON envelope with CORS headers

**Dependencies**: [`src/functions/data_loading/requirements.txt`](../src/functions/data_loading/requirements.txt)
- `functions-framework`, `flask`, `nflreadpy`, `supabase`, etc.

**Deployment Script**: [`src/functions/data_loading/functions/deploy.sh`](../src/functions/data_loading/functions/deploy.sh)
- Creates temporary wrapper at project root and deploys to Google Cloud Functions

## Request Format

```json
{
  "schema_version": "1.0.0",
  "producer": "t4l.sports.packager/api@1.0.0",
  "subject": {"entity_type": "player", "ids": {"nflverse": "00-0038796"}},
  "scope": {"granularity": "week", "competition": "regular", "temporal": {"season": 2025, "week": 2}},
  "provenance": {"sources": [{"name": "pfr.weekly", "version": "2025.02"}]},
  "bundles": [
    {
  "name": "weekly_stats",
  "schema_ref": "player.week.v1",
      "record_grain": "entity",
  "provider": "player_weekly_stats",
  "filters": {"season": 2025, "week": 2, "player_id": "00-0038796"}
    }
  ]
}
```

**Responses**:
- `200` – Success with serialized package envelope
- `400` – Validation error (invalid JSON or missing required fields)
- `500` – Unexpected error
- `204` – Pre-flight OPTIONS request

**Sample Requests**: See [`requests/`](../requests/) directory:
- `ngs_player_week_package.json` – Next Gen Stats
- `pfr_player_season_package.json` – Pro Football Reference
- `snap_counts_player_game_package.json` – Snap counts
- `pbp_single_game_package.json` – Play-by-play

**Contract**: See [package_contract.md](package_contract.md) for complete request/response specification.

## Local Testing

**Quick Start**:
```bash
cd src/functions/data_loading
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure Supabase

# Run local server
cd functions
./run_local.sh
```

The local server runs on `http://localhost:8080`. Test with curl:

```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d @../../requests/pfr_player_season_package.json
```

See [TESTING_DEPLOYMENT.md](../src/functions/data_loading/TESTING_DEPLOYMENT.md) for details.

## Deployment

**Deploy to Google Cloud Functions**:
```bash
cd src/functions/data_loading/functions
./deploy.sh
```

The deployment script:
1. Creates a temporary `main.py` wrapper at project root
2. Deploys to Google Cloud Functions (Gen 2)
3. Cleans up temporary files
4. Exposes HTTPS endpoint: `https://<region>-<project>.cloudfunctions.net/data-loader`

**Configuration**:
- Edit `deploy.sh` to set:
  - `PROJECT_ID` – Your Google Cloud project
  - `REGION` – Deployment region (default: `us-central1`)
  - `FUNCTION_NAME` – Cloud Function name (default: `data-loader`)
  - `SUPABASE_URL` and `SUPABASE_KEY` – Environment variables for Cloud Function

See [TESTING_DEPLOYMENT.md](../src/functions/data_loading/TESTING_DEPLOYMENT.md) for complete deployment guide.

## Data Providers

The Cloud Function supports multiple data providers:

| Provider | Description | Example Request |
|----------|-------------|-----------------|
| `pbp` | Play-by-play data | `requests/pbp_single_game_package.json` |
| `pfr` | Pro Football Reference stats | `requests/pfr_player_season_package.json` |
| `ngs` | Next Gen Stats | `requests/ngs_player_week_package.json` |
| `player_weekly_stats` | Weekly player stats | `requests/player_weekly_stats_package.json` |
| `snap_counts` | Snap counts | `requests/snap_counts_player_game_package.json` |

Each provider supports different filters and granularities. See [package_contract.md](package_contract.md) for details.

## Error Handling & CORS

- **Methods**: Only `POST` and `OPTIONS` supported (405 for others)
- **Validation**: Invalid JSON or missing fields return 400
- **CORS**: All responses include `Access-Control-Allow-Origin: *` for browser access
- **Errors**: Structured error responses with details

## Warehouse Datasets

The Cloud Function API **does not** expose warehouse datasets (`teams`, `players`, `rosters`, `depth_charts`, `games`).

**To load warehouse data**:
```bash
cd src/functions/data_loading
python scripts/players_cli.py --season 2024
python scripts/games_cli.py --season 2024
python scripts/rosters_cli.py
python scripts/depth_charts_cli.py
```

These datasets are stored in Supabase and can be queried directly from your application.

---

**See Also**:
- [package_contract.md](package_contract.md) – Request/response specification
- [TESTING_DEPLOYMENT.md](../src/functions/data_loading/TESTING_DEPLOYMENT.md) – Testing & deployment guide
- [Data Loading README](../src/functions/data_loading/README.md) – Complete module documentation
