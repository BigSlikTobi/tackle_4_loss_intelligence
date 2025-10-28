# Article Summarization Module

A production-ready AI-powered summarization service that converts extracted article content into concise, team-focused summaries using Google's Gemini models. This module is designed for both library and Cloud Function deployment, following function-based isolation principles.

## Features

- **AI-Powered Summarization**: Uses Google Gemini (Gemma-3n or Gemini 2.5 Flash)
- **Team-Focused**: Generates summaries specific to NFL teams
- **Boilerplate Removal**: Automatically removes ads, promotional content, and unrelated text
- **Rate Limiting**: Token bucket algorithm prevents API quota exhaustion
- **Retry Logic**: Exponential backoff for transient failures
- **Metrics Collection**: Tracks token usage and processing time
- **Structured Output**: Strongly typed data contracts for reliable integration
- **Flexible Configuration**: Supports temperature, token limits, and custom patterns

## Installation

```bash
cd src/functions/article_summarization
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Configure via the central project `.env` file:

```bash
# Required
GEMINI_API_KEY="your-gemini-api-key-here"

# Optional
GEMINI_MODEL="gemini-2.5-flash"  # Options: gemini-2.5-flash, gemini-2.5-pro, gemma-3n-e4b-it
LOG_LEVEL=INFO
```

See `.env.example` at project root for complete configuration template.

## Usage

### Command Line Interface

Summarize an article from extracted content:

```bash
cd scripts
python summarize_cli.py path/to/extracted_content.json --team-name "Kansas City Chiefs"
```

With options:

```bash
# Verbose output with debug logging
python summarize_cli.py content.json --team-name "Chiefs" --verbose

# Custom model
python summarize_cli.py content.json --team-name "Chiefs" --model gemini-2.5-pro

# Save to file
python summarize_cli.py content.json --team-name "Chiefs" --output summary.json

# Pretty-print JSON
python summarize_cli.py content.json --team-name "Chiefs" --pretty

# Dry run (validate input only)
python summarize_cli.py content.json --team-name "Chiefs" --dry-run
```

### Python API

```python
from src.functions.article_summarization.core.llm.gemini_client import GeminiSummarizationClient
from src.functions.article_summarization.core.contracts.summary import SummarizationRequest

# Create client
client = GeminiSummarizationClient(model="gemini-2.5-flash")

# Create request
request = SummarizationRequest(
    article_id="article-123",
    content="Full article text here...",
    team_name="Kansas City Chiefs",
    url="https://example.com/article"
)

# Summarize
summary = client.summarize(request)

# Check for errors
if summary.error:
    print(f"Summarization failed: {summary.error}")
else:
    print(f"Summary: {summary.content}")
    print(f"Length: {summary.word_count} words")
```

With custom options:

```python
from src.functions.article_summarization.core.contracts.summary import SummarizationOptions

options = SummarizationOptions(
    model="gemini-2.5-pro",
    temperature=0.3,
    max_output_tokens=250,
    min_word_count=120,
    max_word_count=180,
    remove_patterns=["subscribe", "newsletter", "advertisement"]
)

summary = client.summarize(request, options=options)
```

### Cloud Function Deployment

Deploy to Google Cloud Functions:

```bash
cd functions
./deploy.sh
```

Run locally for testing:

```bash
cd functions
./run_local.sh
```

HTTP API usage:

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{
    "article_id": "123",
    "content": "Article text...",
    "team_name": "Kansas City Chiefs",
    "url": "https://example.com/article"
  }'
```

## Architecture

### Summarization Pipeline

```
1. Receive Article Content
   ↓
2. Build Team-Focused Prompt
   ↓
3. Call Gemini API (with rate limiting)
   ↓
4. Extract Response Text
   ↓
5. Format & Validate Summary
   ↓
6. Return Structured Output
```

### Rate Limiting

The module uses a token bucket algorithm to prevent API quota exhaustion:

- **Default**: 60 requests per minute
- **Configurable**: Adjust via `MAX_REQUESTS_PER_MINUTE`
- **Blocking**: Waits when quota is exhausted
- **Thread-safe**: Works with concurrent requests

### Retry Logic

Exponential backoff for transient failures:

- **Attempts**: 3 retries by default
- **Wait**: 1s → 2s → 4s → 8s (max 10s)
- **Errors**: Retries on `GoogleAPIError` and network issues

## Data Models

```python
@dataclass
class SummarizationRequest:
    article_id: str
    content: str                    # Full article text
    team_name: Optional[str]        # Focus on this team
    url: Optional[str]              # Source URL
    metadata: Dict[str, Any]        # Additional context

@dataclass
class ArticleSummary:
    content: str                    # Summarized text
    source_article_id: str
    word_count: int
    key_quotes: List[str]
    topics: List[str]
    processing_time_ms: int
    tokens_used: int
    error: Optional[str]

@dataclass
class SummarizationOptions:
    model: str = "gemini-2.5-flash"
    temperature: float = 0.3
    max_output_tokens: int = 200
    min_word_count: int = 120
    max_word_count: int = 180
    remove_patterns: List[str]      # Phrases to never include
```

## Project Structure

```
article_summarization/
├── core/
│   ├── contracts/
│   │   └── summary.py                # Data models
│   ├── llm/
│   │   ├── gemini_client.py          # Gemini API client
│   │   └── rate_limiter.py           # Token bucket rate limiting
│   └── processors/
│       └── summary_formatter.py      # Output formatting & validation
├── scripts/
│   └── summarize_cli.py              # Command-line tool
├── functions/
│   ├── main.py                       # Cloud Function entry
│   ├── local_server.py               # Local testing server
│   ├── deploy.sh                     # Deployment script
│   └── run_local.sh                  # Local execution
├── requirements.txt                  # Dependencies
└── README.md                         # This file
```

## Dependencies

- **google-generativeai**: Gemini API client
- **tenacity**: Retry logic with exponential backoff
- **pydantic**: Data validation

See `requirements.txt` for complete list with versions.

## Error Handling

Graceful error handling with structured responses:

- **API failures**: Return `ArticleSummary` with `error` field set
- **Rate limiting**: Automatically waits and retries
- **Invalid input**: Validates and rejects early
- **Timeout**: Configurable timeout per request

Example:

```python
summary = client.summarize(request)
if summary.error:
    if "quota" in summary.error.lower():
        print("API quota exceeded - retry later")
    else:
        print(f"Summarization failed: {summary.error}")
```

## Performance

Typical performance metrics:

- **Processing time**: 2-5s per article
- **Token usage**: 150-300 tokens per summary (input + output)
- **Rate limit**: 60 requests/minute (default)
- **Batch size**: 5 articles recommended for optimal throughput

Optimization tips:

- Batch multiple articles in parallel (up to rate limit)
- Use `gemini-2.5-flash` for faster responses
- Pre-filter content to reduce input tokens
- Cache summaries for repeated articles

## Prompt Engineering

The summarization prompt is optimized for:

1. **Team Focus**: Prioritizes information about the specified team
2. **Boilerplate Removal**: Strips ads, promotional content, transcripts
3. **Fact Preservation**: Maintains quotes, stats, and key details
4. **Conciseness**: Targets 120-180 words
5. **No Speculation**: Avoids adding analysis or commentary

Example prompt structure:

```
You are an NFL beat reporter summarizing a news article for internal editors.
Remove boilerplate, advertisements, video transcripts, promotional copy, and unrelated paragraphs.
Focus on insights about the Kansas City Chiefs.
Preserve key facts, quotes, and meaningful context without speculation.
Do not add analysis or commentary. Output a concise paragraph (120-180 words).
Never include phrases related to: subscribe, newsletter, click here.

Article Content:
[Full article text...]
```

## Testing

Manual testing with CLI:

```bash
# Test with sample article
echo '{"content": "Article text here...", "team_name": "Chiefs"}' > test.json
python scripts/summarize_cli.py test.json --verbose

# Test error handling
echo '{"content": ""}' > empty.json
python scripts/summarize_cli.py empty.json --verbose
```

## Troubleshooting

**API key not found:**
```bash
export GEMINI_API_KEY="your-key-here"
# Or add to .env file
```

**Rate limit exceeded:**
- Reduce request frequency
- Increase `MAX_REQUESTS_PER_MINUTE` if you have higher quota
- Wait for quota to reset (typically 1 minute)

**Empty summaries:**
- Check input content is not empty
- Verify Gemini API is responding
- Try increasing `max_output_tokens`

**Import errors:**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Integration with Daily Team Update Pipeline

This module is used by the daily_team_update pipeline for step 3 (summarization):

```python
from src.functions.article_summarization.core.llm.gemini_client import GeminiSummarizationClient
from src.functions.article_summarization.core.contracts.summary import SummarizationRequest

client = GeminiSummarizationClient()

for content in extracted_contents:
    request = SummarizationRequest(
        article_id=content.id,
        content=content.text,
        team_name=team_name
    )
    summary = client.summarize(request)
    # Pass to article generation...
```

## Function Isolation

This module follows the platform's function-based isolation principles:

- ✅ **Complete Independence**: Can be deleted without affecting other modules
- ✅ **Isolated Dependencies**: Own `requirements.txt` and virtualenv
- ✅ **Separate Deployment**: Deploys independently to Cloud Functions
- ✅ **Minimal Shared Code**: Only uses generic utilities from `src/shared/`

No imports from other function modules.
