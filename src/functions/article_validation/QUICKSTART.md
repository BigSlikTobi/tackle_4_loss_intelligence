# Article Validation Cloud Function - Quick Start

## Local Development

### 1. Install Dependencies
```bash
cd src/functions/article_validation
pip install -r requirements.txt
```

### 2. Start Local Server
```bash
cd functions
./run_local.sh
```

### 3. Test with Sample Request
```bash
# In another terminal
curl -X POST http://localhost:8080 \
  -H 'Content-Type: application/json' \
  -d @test_requests/minimal_validation.json
```

## Deployment to Google Cloud

### 1. Prerequisites
- Install Google Cloud SDK: https://cloud.google.com/sdk/docs/install
- Authenticate: `gcloud auth login`
- Set project: `gcloud config set project YOUR_PROJECT_ID`

### 2. Deploy
```bash
cd src/functions/article_validation/functions
./deploy.sh
```

### 3. Test Deployed Function
```bash
# Get the function URL from deploy output
curl -X POST https://REGION-PROJECT.cloudfunctions.net/article-validation \
  -H 'Content-Type: application/json' \
  -d '{
    "article": {"headline": "Test", "content": "Test article"},
    "article_type": "team_article",
    "llm": {"api_key": "YOUR_GEMINI_API_KEY"}
  }'
```

## Request Payload Structure

### Minimal Request
```json
{
  "article": {
    "headline": "Your headline",
    "content": "Your article content"
  },
  "article_type": "team_article",
  "llm": {
    "api_key": "your-gemini-api-key"
  }
}
```

### Full Request
```json
{
  "article": {...},
  "article_type": "team_article",
  "team_context": {
    "team_id": "KC",
    "team_name": "Kansas City Chiefs"
  },
  "source_summaries": ["summary1", "summary2"],
  "llm": {
    "api_key": "your-gemini-api-key",
    "model": "gemini-2.5-flash-lite",
    "enable_web_search": true,
    "timeout_seconds": 60
  },
  "validation_config": {
    "enable_factual": true,
    "enable_contextual": true,
    "enable_quality": true,
    "factual_threshold": 0.7,
    "contextual_threshold": 0.7,
    "quality_threshold": 0.7,
    "confidence_threshold": 0.8,
    "timeout_seconds": 90
  },
  "supabase": {
    "url": "your-supabase-url",
    "key": "your-supabase-key",
    "table": "article_validations"
  }
}
```

## Response Structure

```json
{
  "status": "success",
  "decision": "release",
  "is_releasable": true,
  "article_type": "team_article",
  "processing_time_ms": 4523,
  "factual": {
    "enabled": true,
    "score": 0.95,
    "confidence": 0.88,
    "passed": true,
    "issues": []
  },
  "contextual": {...},
  "quality": {...},
  "rejection_reasons": [],
  "review_reasons": []
}
```

## Decision Values

- `"release"`: Article passes all validation checks and can be published
- `"reject"`: Article has critical issues and should be regenerated
- `"review_required"`: Article has warnings that may need human review

## Files

- `functions/main.py` - Cloud Function entry point
- `functions/local_server.py` - Local development server
- `functions/deploy.sh` - Deployment script
- `functions/run_local.sh` - Local testing script
- `test_requests/*.json` - Sample payloads for testing

## Troubleshooting

### Import Errors
Make sure you're running from the project root and have installed dependencies:
```bash
cd /path/to/Tackle_4_loss_intelligence
pip install -r src/functions/article_validation/requirements.txt
```

### API Key Issues
Ensure your Gemini API key is valid and has web search enabled:
- Get API key: https://aistudio.google.com/app/apikey
- Include in request payload under `llm.api_key`

### Timeout Issues
Increase timeout in validation_config:
```json
"validation_config": {
  "timeout_seconds": 120
}
```

### Deployment Issues
- Check gcloud authentication: `gcloud auth list`
- Check project: `gcloud config get-value project`
- Check permissions: Ensure you have Cloud Functions Admin role

## Support

See full documentation in `README.md` (to be created in task 13).
