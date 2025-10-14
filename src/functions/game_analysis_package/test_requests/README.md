# Test Request Files

This directory contains sample game package JSON files for testing the game analysis module.

## Files

### `sample_game.json`
A complete game package with 10 plays from a 49ers vs Chiefs matchup. Includes various play types:
- Pass plays with completions
- Run plays
- Touchdown plays
- Sacks
- Multiple tacklers per play

Use this for full pipeline testing with realistic data.

### `minimal_game.json`
A minimal valid game package with just one play. Use this for:
- Quick validation testing
- Dry-run mode testing
- Development and debugging

## Usage with CLI

```bash
# Test with sample game
cd src/functions/game_analysis_package
python scripts/analyze_game_cli.py --request test_requests/sample_game.json --pretty

# Test with minimal game (dry-run)
python scripts/analyze_game_cli.py --request test_requests/minimal_game.json --dry-run

# Verbose output
python scripts/analyze_game_cli.py --request test_requests/sample_game.json --verbose
```

## Usage with HTTP API

### Local Testing

```bash
# Start local server
cd src/functions/game_analysis_package/functions
./run_local.sh

# In another terminal, test with curl
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d @../test_requests/sample_game.json | jq

# Test minimal game
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d @../test_requests/minimal_game.json | jq
```

### Production Testing

```bash
# Get function URL after deployment
cd src/functions/game_analysis_package/functions
FUNCTION_URL=$(gcloud functions describe game-analysis --region=us-central1 --format='value(httpsTrigger.url)')

# Test with sample game
curl -X POST $FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d @../test_requests/sample_game.json | jq
```

## Game Package Structure

All test files follow this structure:

```json
{
  "schema_version": "1.0.0",
  "producer": "client.system/version",
  "game_package": {
    "season": 2024,
    "week": 5,
    "game_id": "2024_05_SF_KC",
    "plays": [
      {
        "play_id": "unique_play_id",
        "game_id": "2024_05_SF_KC",
        "quarter": 1,
        "down": 1,
        "yards_to_go": 10,
        "posteam": "SF",
        "defteam": "KC",
        "play_type": "pass",
        "yards_gained": 8.0,
        "passer_player_id": "00-0036389",
        "receiver_player_id": "00-0037716",
        "tackler_player_ids": ["00-0033077"]
      }
    ],
    "correlation_id": "optional-trace-id"
  }
}
```

## Creating New Test Files

When creating new test files:

1. **Unique Game IDs**: Use format `YYYY_WW_AWAY_HOME`
2. **Unique Play IDs**: Use format `{game_id}_{sequence}`
3. **Matching IDs**: Ensure all plays have `game_id` matching the package
4. **Valid Seasons**: Use realistic seasons (1920-2026)
5. **Valid Weeks**: Use weeks 1-22 (including playoffs)
6. **Player IDs**: Use realistic NFL player IDs (00-XXXXXXX format)

## Validation Testing

Test various validation scenarios:

```bash
# Valid package
python scripts/analyze_game_cli.py --request test_requests/sample_game.json --dry-run

# Missing required field (should fail)
echo '{"game_package":{"season":2024}}' | python scripts/analyze_game_cli.py --request /dev/stdin --dry-run

# Invalid season (should fail)
echo '{"game_package":{"season":1800,"week":1,"game_id":"test","plays":[]}}' | python scripts/analyze_game_cli.py --request /dev/stdin --dry-run
```

## Expected Outputs

### Successful Analysis
```json
{
  "status": "analyzed",
  "correlation_id": "2024_05_SF_KC-cli",
  "game_info": {
    "game_id": "2024_05_SF_KC",
    "season": 2024,
    "week": 5
  },
  "analysis_summary": {
    "plays_analyzed": 10,
    "players_extracted": 15,
    "relevant_players": 15,
    "ngs_requests": 3
  }
}
```

### Validation Error
```json
{
  "error": "Validation failed",
  "message": "Game package validation failed for game unknown: Missing required field: 'game_id'",
  "game_id": "unknown"
}
```
