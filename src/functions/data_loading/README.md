# Data Loading Function

This module handles NFL data ingestion, transformation, and on-demand package assembly.

## 🎯 Purpose

Load NFL data from various sources (nflreadpy, Pro Football Reference, etc.) into Supabase and provide on-demand package assembly via HTTP API.

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
