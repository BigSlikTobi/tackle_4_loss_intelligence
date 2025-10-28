# URL Content Extraction Module

A production-ready, standalone content extraction service that retrieves structured article data from arbitrary web URLs using Python-based headless browsing with Playwright. This module follows the platform's function-based isolation principles and is designed to be used both as a library and as a deployed Cloud Function.

## Features

- **Dual Extraction Strategies**: Intelligent selection between Playwright (full browser) and lightweight HTTP extraction
- **Smart Content Detection**: Automatically identifies article scope and removes boilerplate
- **Consent Handling**: Detects and handles GDPR cookie banners and consent walls
- **AMP Support**: Automatically follows AMP pages to canonical URLs
- **Content Cleaning**: Removes ads, promotional content, video transcripts, and navigation elements
- **Paragraph Deduplication**: Eliminates repeated content common in news articles
- **Metadata Extraction**: Captures structured metadata (author, publish date, tags)
- **Watchdog Timeout**: Protects against long-running extractions
- **Structured Output**: Strongly typed data contracts for reliable integration

## Installation

```bash
cd src/functions/url_content_extraction
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Install Playwright browsers (required for full extraction)
playwright install chromium
```

## Configuration

All configuration is managed through the central project `.env` file. The module requires minimal configuration:

```bash
# Required
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# Optional (for Cloud Function deployment)
PORT=8080
```

No API keys or additional configuration needed for basic operation.

## Usage

### Command Line Interface

Extract content from a URL:

```bash
cd scripts
python extract_content_cli.py "https://example.com/article"
```

With options:

```bash
# Verbose output with debug logging
python extract_content_cli.py "https://example.com/article" --verbose

# Force Playwright (bypass light extractor)
python extract_content_cli.py "https://example.com/article" --force-playwright

# Pretty-print JSON output
python extract_content_cli.py "https://example.com/article" --pretty

# Save to file
python extract_content_cli.py "https://example.com/article" --output result.json
```

### Python API

```python
from src.functions.url_content_extraction.core.extractors.extractor_factory import ExtractorFactory

# Create extractor (automatically selects strategy)
extractor = ExtractorFactory.create()

# Extract content
result = extractor.extract("https://example.com/article")

# Check for errors
if result.error:
    print(f"Extraction failed: {result.error}")
else:
    print(f"Title: {result.title}")
    print(f"Content: {result.content}")
    print(f"Paragraphs: {len(result.paragraphs)}")
```

With options:

```python
from src.functions.url_content_extraction.core.extractors.playwright_extractor import PlaywrightExtractor

# Force Playwright extraction
extractor = PlaywrightExtractor()
result = extractor.extract(
    "https://example.com/article",
    handle_consent=True,  # Handle cookie banners
    follow_amp=True,      # Follow AMP to canonical
    watchdog_seconds=30   # Timeout after 30 seconds
)
```

### Cloud Function Deployment

The module can be deployed as a Cloud Function:

```bash
cd functions
./deploy.sh
```

Or run locally for testing:

```bash
cd functions
./run_local.sh
```

HTTP API usage:

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article"}'
```

## Architecture

### Extraction Strategies

The module uses two extraction strategies:

1. **PlaywrightExtractor** (Full Browser)
   - Handles JavaScript-heavy sites
   - Manages consent banners and cookie walls
   - Follows AMP pages to canonical URLs
   - Best for: ESPN, Yahoo Sports, complex news sites

2. **LightExtractor** (HTTP Only)
   - Fast async HTTP requests with httpx
   - BeautifulSoup4 parsing
   - Minimal overhead
   - Best for: Simple blogs, static content

The `ExtractorFactory` automatically selects the appropriate strategy based on:
- Known heavy hosts (Yahoo, ESPN, etc.)
- URL characteristics
- User preferences (force-playwright flag)

### Content Processing Pipeline

```
1. Extract Raw HTML
   ↓
2. Detect Article Scope (main content area)
   ↓
3. Clean Boilerplate (ads, navigation, footers)
   ↓
4. Extract Paragraphs & Metadata
   ↓
5. Deduplicate Paragraphs
   ↓
6. Format Output
```

### Data Models

```python
@dataclass
class ExtractedContent:
    url: str
    title: str
    description: str
    content: str              # Full cleaned text
    paragraphs: List[str]     # Individual paragraphs
    author: Optional[str]
    publish_date: Optional[str]
    images: List[str]
    quotes: List[str]
    tags: List[str]
    extraction_strategy: str  # "playwright" or "light"
    extraction_time_ms: int
    error: Optional[str]
```

## Project Structure

```
url_content_extraction/
├── core/
│   ├── contracts/
│   │   └── extracted_content.py      # Data models
│   ├── extractors/
│   │   ├── extractor_factory.py      # Strategy selection
│   │   ├── playwright_extractor.py   # Full browser extraction
│   │   └── light_extractor.py        # HTTP-only extraction
│   ├── processors/
│   │   ├── content_cleaner.py        # Boilerplate removal
│   │   ├── metadata_extractor.py     # Schema.org, meta tags
│   │   └── text_deduplicator.py      # Paragraph deduplication
│   └── utils/
│       ├── consent_handler.py        # Cookie banner handling
│       └── amp_detector.py           # AMP page detection
├── scripts/
│   └── extract_content_cli.py        # Command-line tool
├── functions/
│   ├── main.py                       # Cloud Function entry
│   ├── local_server.py               # Local testing server
│   ├── deploy.sh                     # Deployment script
│   └── run_local.sh                  # Local execution
├── requirements.txt                  # Dependencies
└── README.md                         # This file
```

## Dependencies

- **playwright**: Headless browser automation
- **httpx**: Async HTTP client for light extraction
- **beautifulsoup4**: HTML parsing
- **lxml**: Fast XML/HTML parser
- **trafilatura**: Article extraction and cleaning

See `requirements.txt` for complete list with versions.

## Error Handling

The module uses graceful error handling:

- **Extraction failures**: Return `ExtractedContent` with `error` field set
- **Timeouts**: Watchdog mechanism prevents indefinite hangs
- **Network errors**: Retry logic with exponential backoff
- **Invalid URLs**: Validated and rejected early

Example:

```python
result = extractor.extract("https://invalid-url.com")
if result.error:
    print(f"Failed: {result.error}")
    # Handle error appropriately
```

## Performance

Typical extraction times:

- **LightExtractor**: 200-500ms for simple pages
- **PlaywrightExtractor**: 2-5s for complex JavaScript sites
- **With consent handling**: +1-2s for cookie banner interaction

Optimization tips:

- Use LightExtractor when possible (faster, less resource-intensive)
- Configure watchdog timeout based on your needs
- Run Playwright in headless mode (default)
- Consider caching extracted content for repeated URLs

## Testing

Manual testing with CLI:

```bash
# Test different strategies
python scripts/extract_content_cli.py "https://espn.com/article" --verbose
python scripts/extract_content_cli.py "https://simple-blog.com" --verbose

# Test error handling
python scripts/extract_content_cli.py "https://invalid-url.com" --verbose
```

## Troubleshooting

**Playwright installation fails:**
```bash
playwright install chromium
```

**Extraction timeout:**
- Increase watchdog timeout: `watchdog_seconds=60`
- Check network connectivity
- Verify URL is accessible

**Empty content returned:**
- Try forcing Playwright: `--force-playwright`
- Check URL is not behind paywall
- Verify site structure hasn't changed

**Import errors:**
```bash
# Ensure you're in the correct environment
source venv/bin/activate
pip install -r requirements.txt
```

## Integration with Daily Team Update Pipeline

This module is used by the daily_team_update pipeline for step 2 (content extraction):

```python
from src.functions.url_content_extraction.core.extractors.extractor_factory import ExtractorFactory

extractor = ExtractorFactory.create()
for url in team_urls:
    content = extractor.extract(url)
    # Pass to summarization...
```

## Function Isolation

This module follows the platform's function-based isolation principles:

- ✅ **Complete Independence**: Can be deleted without affecting other modules
- ✅ **Isolated Dependencies**: Own `requirements.txt` and virtualenv
- ✅ **Separate Deployment**: Deploys independently to Cloud Functions
- ✅ **Minimal Shared Code**: Only uses generic utilities from `src/shared/`

No imports from other function modules.
