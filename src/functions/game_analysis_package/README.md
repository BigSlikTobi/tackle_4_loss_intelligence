# Game Analysis Package Module

## Overview

The Game Analysis Package module transforms raw play-by-play game data into enriched, LLM-ready analysis packages. It automatically identifies relevant players, fetches comprehensive stats from multiple sources, and produces both detailed datasets and compact analysis envelopes optimized for AI consumption.

## Features

- **Automatic Player Extraction**: Identifies relevant players from play-by-play data using impact scoring
- **Multi-Source Data Integration**: Fetches play-by-play, snap counts, team context, and Next Gen Stats
- **Data Normalization**: Cleans and standardizes data with consistent identifiers
- **Comprehensive Summaries**: Computes team and player performance metrics
- **LLM-Ready Envelopes**: Creates compact, AI-optimized analysis packages
- **Independent Deployment**: Follows function-based isolation architecture

## Architecture

This module follows the established function-based isolation pattern:

```
game_analysis_package/
├── core/                  # Business logic
│   ├── contracts/         # Data contracts and types
│   ├── extraction/        # Player extraction and relevance
│   ├── bundling/          # Data request management
│   ├── processing/        # Data processing and normalization
│   ├── pipelines/         # Main orchestration
│   └── utils/             # Module utilities
├── scripts/               # CLI tools
├── functions/             # Cloud Function deployment
├── test_requests/         # Sample test data
├── requirements.txt       # Module dependencies
├── .env.example          # Configuration template
└── README.md             # This file
```

## Setup

### Prerequisites

- Python 3.9+
- Access to Supabase database
- Central `.env` file configured at project root

### Installation

```bash
# Navigate to module directory
cd src/functions/game_analysis_package

# Create isolated virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Ensure central .env is configured
# (Copy .env.example to project root .env if needed)
```

### Configuration

All configuration is managed through the **central `.env` file** at the project root. Required variables:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
LOG_LEVEL=INFO
```

## Usage

### CLI Usage

Analyze a game package from a JSON file:

```bash
# From module directory
python scripts/analyze_game_cli.py --request test_requests/sample_game.json --pretty

# With verbose logging
python scripts/analyze_game_cli.py --request test_requests/sample_game.json --verbose

# Dry-run mode (validation only)
python scripts/analyze_game_cli.py --request test_requests/sample_game.json --dry-run
```

### HTTP API Usage

#### Local Testing

```bash
# Start local server
cd functions
./run_local.sh

# Test with curl
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d @../test_requests/sample_game.json
```

#### Production Deployment

```bash
# Deploy to Cloud Functions
cd functions
./deploy.sh

# Test production endpoint
curl -X POST https://us-central1-project.cloudfunctions.net/game-analysis \
  -H "Content-Type: application/json" \
  -d @../test_requests/sample_game.json
```

## Input Format

The module accepts game packages in the following format:

```json
{
  "schema_version": "1.0.0",
  "producer": "client.system/analysis@1.0.0",
  "game_package": {
    "season": 2024,
    "week": 5,
    "game_id": "2024_05_SF_KC",
    "plays": [
      {
        "play_id": "...",
        "game_id": "2024_05_SF_KC",
        "rusher_player_id": "...",
        "receiver_player_id": "...",
        ...
      }
    ],
    "correlation_id": "optional-trace-id"
  }
}
```

## Output Format

Returns both an enriched package and an analysis envelope:

```json
{
  "schema_version": "1.0.0",
  "correlation_id": "game-2024_05_SF_KC-abc123",
  "enriched_package": {
    "game_info": {...},
    "plays": [...],
    "team_data": {...},
    "player_data": {...},
    "data_sources": {...}
  },
  "analysis_envelope": {
    "game_header": {...},
    "team_summaries": {...},
    "player_map": {...},
    "key_sequences": [...],
    "data_pointers": {...}
  }
}
```

## Pipeline Steps

The module processes game packages through a 9-step pipeline:

1. **Validation**: Validate package structure and completeness
2. **Player Extraction**: Extract unique player IDs from plays
3. **Relevance Scoring**: Score and select balanced player set
4. **Request Bundling**: Build combined data requests
5. **Data Fetching**: Fetch from upstream sources
6. **Normalization**: Clean and standardize data
7. **Summarization**: Compute team and player metrics
8. **Envelope Creation**: Build LLM-friendly envelope
9. **Response Formatting**: Format final output

## Development

### Running Tests

```bash
# Run module tests
pytest tests/game_analysis_package/

# With coverage
pytest tests/game_analysis_package/ --cov=src.functions.game_analysis_package
```

### Debugging

Enable debug logging:

```bash
export LOG_LEVEL=DEBUG
python scripts/analyze_game_cli.py --request test_requests/sample_game.json
```

## Integration

This module integrates with the existing data loading module:

- Uses existing providers via `src.functions.data_loading.core.providers`
- Follows established package contract patterns
- Maintains complete independence (no direct imports from other function modules)

## Dependencies

- **Shared Utilities**: Uses `src.shared.utils` for logging and environment configuration
- **Database**: Uses `src.shared.db` for Supabase connections
- **Data Loading**: Integrates with existing providers (no direct imports)

## Deployment

Deploy independently as a Cloud Function:

```bash
cd functions
./deploy.sh
```

The function will be deployed as `game-analysis` and exposed at:
```
https://<region>-<project>.cloudfunctions.net/game-analysis
```

## Architecture Compliance

This module follows function-based isolation principles:

- ✅ Complete independence from other function modules
- ✅ Isolated dependencies in module-specific `requirements.txt`
- ✅ Independent deployment capability
- ✅ Only uses shared utilities from `src/shared/`
- ✅ Can be deleted without affecting other modules

## Troubleshooting

### Common Issues

**Import Errors**: Ensure you're running from the project root or have PYTHONPATH set correctly:
```bash
export PYTHONPATH=/path/to/Tackle_4_loss_intelligence:$PYTHONPATH
```

**Database Connection Issues**: Verify central `.env` file has correct Supabase credentials

**Provider Not Found**: Ensure data loading module is available (no direct import, uses registry pattern)

## Support

For issues or questions:
- Check existing module READMEs for similar patterns
- Review `docs/architecture/function_isolation.md` for architecture guidelines
- See `docs/game-analysis-package/` for detailed design and requirements
