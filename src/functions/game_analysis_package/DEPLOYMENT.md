# Game Analysis Package - Deployment Guide

## Production Deployment

### Cloud Function Details
- **Function Name**: `game-analysis`
- **URL**: https://game-analysis-hjm4dt4a5q-uc.a.run.app
- **Region**: us-central1
- **Runtime**: Python 3.11
- **Memory**: 512MB
- **Timeout**: 60s
- **Status**: ✅ ACTIVE

### Deployment Date
- **Initial Deployment**: October 14, 2025
- **Last Updated**: October 14, 2025 (Revision 00004)

## Testing the Deployed Function

### Using curl

```bash
# Basic test with minimal game package
curl -X POST https://game-analysis-hjm4dt4a5q-uc.a.run.app \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": "1.0.0",
    "producer": "test-client",
    "fetch_data": false,
    "enable_envelope": true,
    "game_package": {
      "season": 2025,
      "week": 6,
      "game_id": "2025_06_DEN_NYJ",
      "plays": [
        {
          "play_id": "1",
          "game_id": "2025_06_DEN_NYJ",
          "posteam": "DEN",
          "defteam": "NYJ",
          "play_type": "pass",
          "yards_gained": 10,
          "passer_player_id": "00-0039732",
          "receiver_player_id": "00-0038783"
        }
      ]
    }
  }'
```

### Using test file

```bash
curl -X POST https://game-analysis-hjm4dt4a5q-uc.a.run.app \
  -H 'Content-Type: application/json' \
  -d @src/functions/game_analysis_package/test_requests/http_api_test_minimal.json \
  | python3 -m json.tool
```

### Expected Response

```json
{
  "schema_version": "1.0.0",
  "correlation_id": "2025_06_DEN_NYJ-20251014215551-c3864397",
  "status": "success",
  "game_info": {
    "game_id": "2025_06_DEN_NYJ",
    "season": 2025,
    "week": 6
  },
  "validation": {
    "passed": true,
    "warnings": [...]
  },
  "processing": {
    "players_extracted": 4,
    "players_selected": 4,
    "data_fetched": false
  },
  "game_summaries": {
    "game_info": {...},
    "team_summaries": {...},
    "player_summaries": {...}
  },
  "analysis_envelope": {
    "game": {...},
    "teams": [...],
    "players": [...],
    "key_moments": [...],
    "data_links": {...}
  },
  "enriched_package": {
    "plays": [...],
    "player_data": [...]
  }
}
```

## Deployment Process

### Prerequisites
1. Authenticated with gcloud: `gcloud auth login`
2. Project set: `gcloud config set project tackle4loss-888b5`
3. Environment variables set in shell:
   - `SUPABASE_URL`
   - `SUPABASE_KEY`

### Deploy Command

```bash
cd src/functions/game_analysis_package/functions
./deploy.sh
```

### What the Deployment Script Does

1. **Navigates to project root** (4 levels up from functions directory)
2. **Creates temporary main.py** at root with absolute imports
3. **Creates temporary requirements.txt** with all dependencies
4. **Deploys entire src/ tree** to Cloud Functions
5. **Sets environment variables** (SUPABASE_URL, SUPABASE_KEY)
6. **Cleans up temporary files** after deployment

### Deployment Architecture

The deployment includes:
- `src/shared/` - Shared utilities (logging, db, env)
- `src/functions/game_analysis_package/core/` - All business logic
- `src/functions/data_loading/core/providers/` - Data fetching (if needed)

This allows the Cloud Function to use absolute imports:
```python
from src.shared.utils.env import load_env
from src.functions.game_analysis_package.core.pipeline import GameAnalysisPipeline
```

## Local Testing

### Run Local Server

```bash
cd src/functions/game_analysis_package/functions
./run_local.sh
```

Server will start on http://localhost:8080

### Test Local Server

```bash
curl -X POST http://localhost:8080 \
  -H 'Content-Type: application/json' \
  -d @../test_requests/http_api_test_minimal.json
```

## Monitoring and Logs

### View Cloud Function Logs

```bash
gcloud functions logs read game-analysis --region=us-central1 --gen2 --limit=50
```

### Check Function Status

```bash
gcloud functions describe game-analysis --region=us-central1 --gen2
```

### View in Console

- **Functions Dashboard**: https://console.cloud.google.com/functions/details/us-central1/game-analysis?project=tackle4loss-888b5
- **Logs**: https://console.cloud.google.com/logs/query?project=tackle4loss-888b5

## Error Handling

The API returns appropriate HTTP status codes:

- **200**: Success - Analysis completed
- **204**: No Content - OPTIONS preflight request
- **400**: Bad Request - Invalid JSON or missing fields
- **405**: Method Not Allowed - Non-POST request
- **422**: Unprocessable Entity - Validation failed
- **500**: Internal Server Error - Pipeline execution failed

## Request Schema

```json
{
  "schema_version": "1.0.0",          // Required: API version
  "producer": "string",                // Required: Client identifier
  "fetch_data": false,                 // Optional: Fetch additional data from providers
  "enable_envelope": true,             // Optional: Include analysis envelope in response
  "correlation_id": "string",          // Optional: Custom correlation ID for tracking
  "game_package": {                    // Required: Game data
    "season": 2025,                    // Required: Season year
    "week": 6,                         // Required: Week number
    "game_id": "2025_06_DEN_NYJ",     // Required: Unique game identifier
    "plays": [...]                     // Required: Array of play data
  }
}
```

## Response Schema

```json
{
  "schema_version": "1.0.0",          // API version
  "correlation_id": "string",          // Tracking ID (auto-generated or custom)
  "status": "success",                 // Status: "success", "partial", or "failed"
  "game_info": {...},                  // Game metadata
  "validation": {...},                 // Validation results and warnings
  "processing": {...},                 // Processing metrics
  "game_summaries": {...},             // Team and player summaries
  "analysis_envelope": {...},          // LLM-friendly analysis context
  "enriched_package": {...}            // Complete game data with enrichments
}
```

## Performance Metrics

From test deployments:
- **Cold start**: ~2-3 seconds
- **Warm request**: ~0.5-1 seconds
- **Average response size**: ~8-10KB (minimal game)
- **Memory usage**: ~150-200MB typical

## Troubleshooting

### Function won't start
- Check logs: `gcloud functions logs read game-analysis --gen2 --region=us-central1`
- Verify environment variables are set
- Check that deployment included entire src/ tree

### Import errors
- Ensure deploy.sh creates temporary main.py at project root
- Verify absolute imports use `from src.functions.game_analysis_package...`
- Check that src/shared/ is included in deployment

### Timeout errors
- Increase timeout in deploy.sh (default 60s)
- Check for large data fetching operations
- Monitor Cloud Function metrics in console

### Module not found errors
- Deploy from project root (deploy.sh handles this)
- Include entire src/ tree in deployment
- Use absolute imports in temporary main.py

## Update Deployment

To update the deployed function:

```bash
cd src/functions/game_analysis_package/functions
./deploy.sh
```

The script will:
1. Create a new revision (e.g., 00005)
2. Deploy the new code
3. Switch traffic to the new revision
4. Keep previous revision for rollback if needed

## Rollback

If deployment fails or issues arise:

```bash
# List revisions
gcloud run revisions list --service=game-analysis --region=us-central1

# Route traffic to previous revision
gcloud run services update-traffic game-analysis \
  --region=us-central1 \
  --to-revisions=game-analysis-00003-rep=100
```

## Environment Variables

Set before deployment:

```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-supabase-key"
```

These are automatically included in the deployment by deploy.sh.

## Security

- Function allows unauthenticated access (suitable for internal n8n workflows)
- For production, consider adding authentication:
  ```bash
  gcloud functions deploy game-analysis --no-allow-unauthenticated
  ```
- Use service account credentials for n8n → Cloud Function calls
- Rotate SUPABASE_KEY regularly
- Monitor function logs for suspicious activity

## Cost Estimation

Pricing based on Cloud Functions (2nd gen) pricing:
- Invocations: $0.40 per million requests
- CPU: $0.00001667 per vCPU-second
- Memory: $0.000002083 per GB-second
- Networking: $0.12 per GB egress

Estimated cost for 1000 requests/day:
- ~$0.40/month for invocations
- ~$1-2/month for compute
- Total: ~$2-3/month

## Next Steps

1. ✅ Local testing complete
2. ✅ Cloud Function deployed
3. ✅ HTTP API tested
4. ⏳ Integration with n8n workflows
5. ⏳ Production monitoring setup
6. ⏳ Comprehensive test suite (Task 12)
