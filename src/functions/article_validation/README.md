# Article Validation Module

## Overview

The Article Validation Module is an independent, self-contained function module that provides automated fact-checking and quality validation for generated articles. It uses Google Gemini API with web search capabilities to verify factual accuracy, contextual correctness, and adherence to quality standards.

Following the repository's function-based isolation architecture, this module is completely independent with its own dependencies, scripts, and Cloud Function deployment capabilities.

## Features

- **Factual Verification**: Verifies claims against current web sources using LLM web search
- **Contextual Validation**: Ensures correct team, player, and event associations
- **Quality Assessment**: Evaluates articles against customizable quality standards
- **Automated Decisions**: Returns clear release/reject/review decisions
- **Request-Scoped Credentials**: API keys provided per-request (no environment variables required)
- **Flexible Article Structures**: Supports various article types and formats
- **Graceful Degradation**: Optional Supabase storage, handles timeouts and API failures
- **Cloud Function Ready**: Deploy to Google Cloud Functions Gen 2

## Architecture

```
src/functions/article_validation/
├── core/                          # Business logic
│   ├── contracts/                 # Request/response models
│   │   ├── validation_request.py
│   │   ├── validation_report.py
│   │   └── validation_standards.py
│   ├── llm/                       # LLM client integration
│   │   ├── gemini_client.py
│   │   └── rate_limiter.py
│   ├── processors/                # Validation processors
│   │   ├── fact_checker.py
│   │   ├── context_validator.py
│   │   ├── quality_validator.py
│   │   └── decision_engine.py
│   ├── config.py                  # Configuration models
│   ├── factory.py                 # Request factory
│   └── service.py                 # Main orchestration
├── functions/                     # Cloud Function deployment
│   ├── main.py                    # Cloud Function handler
│   ├── local_server.py           # Local development server
│   ├── deploy.sh                 # Deployment script
│   └── run_local.sh              # Local testing script
├── scripts/                       # CLI tools
│   └── validate_cli.py           # Command-line validation tool
├── test_requests/                 # Sample payloads
│   ├── sample_validation.json
│   ├── minimal_validation.json
│   └── custom_standards.json
├── requirements.txt              # Module dependencies
├── .env.example                  # Configuration template
└── README.md                     # This file
```

## Quick Start

### Local Development

1. **Install dependencies**:
```bash
cd src/functions/article_validation
pip install -r requirements.txt
```

2. **Start local server**:
```bash
cd functions
./run_local.sh
```

3. **Test with curl**:
```bash
curl -X POST http://localhost:8080 \
  -H 'Content-Type: application/json' \
  -d '{
    "article": {
      "headline": "Test Article",
      "content": "This is a test article."
    },
    "article_type": "team_article",
    "llm": {
      "api_key": "YOUR_GEMINI_API_KEY"
    }
  }'
```

### Cloud Deployment

1. **Configure gcloud**:
```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

2. **Deploy function**:
```bash
cd src/functions/article_validation/functions
./deploy.sh
```

3. **Test deployed function**:
```bash
curl -X POST https://FUNCTION_URL \
  -H 'Content-Type: application/json' \
  -d @../test_requests/sample_validation.json
```

## API Reference

### Endpoint

**POST** `/` - Validate an article

### Request Payload

#### Required Fields

```json
{
  "article": {
    "headline": "Article Headline",
    "content": "Article content..."
  },
  "article_type": "team_article"
}
```

#### Optional Fields

```json
{
  "article": { ... },
  "article_type": "team_article",
  
  "team_context": {
    "team_id": "KC",
    "team_name": "Kansas City Chiefs",
    "season": 2024,
    "week": 13
  },
  
  "source_summaries": [
    "Summary 1",
    "Summary 2"
  ],
  
  "quality_standards": {
    "article_type": "team_article",
    "quality_rules": [ ... ]
  },
  
  "llm": {
    "api_key": "YOUR_GEMINI_API_KEY",
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
    "url": "https://your-project.supabase.co",
    "key": "your-supabase-key",
    "table": "article_validations"
  }
}
```

### Response Format

```json
{
  "status": "success",
  "decision": "release",
  "is_releasable": true,
  "article_type": "team_article",
  "validation_timestamp": "2025-11-01T12:34:56.789Z",
  "processing_time_ms": 4523,
  
  "factual": {
    "enabled": true,
    "score": 0.95,
    "confidence": 0.88,
    "passed": true,
    "issues": [],
    "details": {}
  },
  
  "contextual": {
    "enabled": true,
    "score": 0.92,
    "confidence": 0.90,
    "passed": true,
    "issues": [],
    "details": {}
  },
  
  "quality": {
    "enabled": true,
    "score": 0.87,
    "confidence": 0.85,
    "passed": true,
    "issues": [
      {
        "severity": "warning",
        "category": "quality",
        "message": "Article could be more concise",
        "location": "paragraph 3",
        "suggestion": "Consider removing redundant phrases",
        "source_url": null
      }
    ],
    "details": {}
  },
  
  "rejection_reasons": [],
  "review_reasons": []
}
```

### Decision Values

- **`release`**: Article meets all criteria and can be published
- **`reject`**: Article has critical issues and should be regenerated
- **`review_required`**: Article has warnings that may need human review

### Status Values

- **`success`**: Validation completed successfully
- **`partial`**: Validation timed out but returned partial results
- **`error`**: Validation failed due to an error

## Configuration

### Request-Scoped Credentials

Credentials are provided in the request payload (not environment variables):

```json
{
  "llm": {
    "api_key": "YOUR_GEMINI_API_KEY"
  },
  "supabase": {
    "url": "https://your-project.supabase.co",
    "key": "your-supabase-key"
  }
}
```

### Environment Variables (Optional Fallbacks)

If credentials are not in the request, the module will check these environment variables:

```bash
# Gemini API
GEMINI_API_KEY=your-api-key
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_ENABLE_WEB_SEARCH=true
GEMINI_TIMEOUT_SECONDS=60

# Validation
VALIDATION_TIMEOUT_SECONDS=90

# Supabase (optional)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-key
SUPABASE_TABLE=article_validations

# Logging
LOG_LEVEL=INFO
```

## Validation Standards

### Standards File Format

Each article generation module can maintain its own validation standards file:

```
src/functions/team_article_generation/
└── validation_standards.json
```

Example structure:

```json
{
  "article_type": "team_article",
  "version": "1.0",
  "quality_rules": [
    {
      "rule_id": "tone",
      "description": "Professional AP-style tone",
      "weight": 0.3,
      "validation_prompt": "Does this maintain professional AP-style tone?"
    }
  ],
  "contextual_requirements": {
    "team_mention_required": true,
    "player_team_verification": true,
    "event_team_verification": true
  },
  "factual_verification": {
    "verify_statistics": true,
    "verify_game_results": true,
    "verify_player_names": true,
    "verify_roster_info": true
  }
}
```

### Custom Standards

You can override standards in the request payload:

```json
{
  "article": { ... },
  "quality_standards": {
    "quality_rules": [ ... ]
  }
}
```

## CLI Tool

Use the CLI for testing and debugging:

```bash
cd scripts

# Validate with payload file
python validate_cli.py \
  --payload ../test_requests/sample_validation.json \
  --pretty

# Validate with inline article
python validate_cli.py \
  --article-type team_article \
  --article '{"headline": "Test", "content": "Test content"}' \
  --api-key $GEMINI_API_KEY
```

## Article Structure Support

The module supports flexible article structures:

### Team Article Format
```json
{
  "headline": "Article Headline",
  "sub_header": "Sub-header text",
  "introduction_paragraph": "Introduction...",
  "content": [
    "Paragraph 1",
    "Paragraph 2"
  ]
}
```

### Generic Format
```json
{
  "title": "Article Title",
  "body": "Article body text...",
  "metadata": { ... }
}
```

The validator extracts text content from any structure for analysis.

## Error Handling

### Timeout Handling
- Individual LLM calls: 60 seconds (configurable)
- Total validation: 90 seconds (configurable)
- Returns partial results on timeout

### API Failures
- Implements exponential backoff for retries
- Gracefully degrades when APIs are unavailable
- Returns error status with details

### Rate Limiting
- Built-in rate limiter for LLM API calls
- Prevents hitting API rate limits
- Configurable requests per minute

## Performance

### Parallel Validation
All three validation dimensions (factual, contextual, quality) run in parallel using `asyncio.gather()` to minimize total processing time.

### Typical Processing Times
- Simple article: 3-5 seconds
- Complex article with many claims: 8-15 seconds
- Timeout threshold: 90 seconds

### Optimization Tips
- Enable only needed validation types
- Provide source summaries for faster fact-checking
- Use shorter timeout for quick validation

## Integration with Article Generation Pipeline

### Basic Integration

```python
from src.functions.article_validation.core.factory import request_from_payload
from src.functions.article_validation.core.service import ArticleValidationService
import asyncio

# Generate article
article = generate_team_article(...)

# Validate article
payload = {
    "article": article,
    "article_type": "team_article",
    "llm": {"api_key": gemini_api_key}
}

request = request_from_payload(payload)
service = ArticleValidationService(request)
report = asyncio.run(service.validate())

# Check decision
if report.is_releasable:
    publish_article(article)
elif report.decision == "reject":
    regenerate_article()
else:
    queue_for_review(article, report)
```

### Pipeline Integration

```python
async def generate_and_validate_article(team_id, week):
    # Generate article
    article = await generate_article(team_id, week)
    
    # Validate
    validation_request = request_from_payload({
        "article": article,
        "article_type": "team_article",
        "team_context": {"team_id": team_id, "week": week},
        "llm": {"api_key": os.getenv("GEMINI_API_KEY")}
    })
    
    service = ArticleValidationService(validation_request)
    report = await service.validate()
    
    # Handle decision
    if report.decision == "release":
        await publish_article(article)
    elif report.decision == "reject":
        logger.warning(f"Article rejected: {report.rejection_reasons}")
        await regenerate_article(team_id, week)
    else:
        logger.info(f"Article needs review: {report.review_reasons}")
        await queue_for_review(article, report)
    
    return article, report
```

## Security Considerations

### API Key Handling
- API keys provided in request payload (not logged)
- Keys never stored or persisted
- Not visible in Cloud Function environment

### Input Validation
- All request fields validated before processing
- Article content sanitized
- File path validation for standards files

### Output Sanitization
- Validation reports sanitized before storage
- No sensitive data in logs
- CORS headers properly configured

## Troubleshooting

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'flask'`
**Solution**: Install dependencies: `pip install -r requirements.txt`

**Issue**: `ValueError: Gemini API key must be provided`
**Solution**: Provide API key in request payload or set `GEMINI_API_KEY` environment variable

**Issue**: Validation times out
**Solution**: Increase `timeout_seconds` in `validation_config` or disable some validation types

**Issue**: Low confidence scores
**Solution**: Provide `source_summaries` for better fact-checking context

### Debug Logging

Enable debug logging for detailed information:

```bash
export LOG_LEVEL=DEBUG
./run_local.sh
```

## Module Independence

This module follows function-based isolation principles:

✅ **Complete Independence**: Can be deleted without affecting other modules  
✅ **Isolated Dependencies**: Own `requirements.txt` and virtualenv  
✅ **Separate Deployment**: Deploys independently to Cloud Functions  
✅ **Minimal Shared Code**: Only uses `src.shared` utilities  
✅ **No Cross-Module Imports**: Only imports from own `core/` and `src.shared`  

## Testing

### Run All Tests
```bash
pytest tests/article_validation/
```

### Test Individual Components
```bash
# Test fact checker
pytest tests/article_validation/test_fact_checker.py

# Test context validator
pytest tests/article_validation/test_context_validator.py

# Test quality validator
pytest tests/article_validation/test_quality_validator.py
```

### Integration Tests
```bash
pytest tests/integration/test_validation_pipeline.py
```

## Dependencies

- `google-generativeai>=0.8.3` - Gemini API client
- `aiohttp>=3.9.0` - Async HTTP client
- `pydantic>=2.5.0` - Data validation
- `flask>=3.0.0` - Local development server
- `functions-framework>=3.5.0` - Cloud Functions framework

## License

This module is part of the Tackle 4 Loss Intelligence platform.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the test request payloads in `test_requests/`
3. Enable debug logging for detailed information
4. Consult the architecture documentation in `docs/architecture/`
