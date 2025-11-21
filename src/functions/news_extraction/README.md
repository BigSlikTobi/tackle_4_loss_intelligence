# News Extraction Function

This module handles NFL news URL extraction from RSS feeds and sitemaps with production-grade reliability.

## 🎯 Purpose

Extract NFL news URLs from multiple sources (ESPN, CBS Sports, Yahoo Sports, NFL.com) and store them in Supabase for downstream content analysis. Features concurrent processing, HTTP caching, circuit breaker pattern, and comprehensive monitoring.

## 🚀 Quick Start

### Local Development

```bash
cd src/functions/news_extraction
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your Supabase credentials

# Run extraction (dry-run first to preview)
python scripts/extract_news_cli.py --dry-run --verbose

# Run for real
python scripts/extract_news_cli.py

# Clear and reload
python scripts/extract_news_cli.py --clear

# Extract from specific source only
python scripts/extract_news_cli.py --source "ESPN" --dry-run

# Filter by recency
python scripts/extract_news_cli.py --days-back 7

# Production with metrics
python scripts/extract_news_cli.py --environment prod --max-workers 6 --output-format json --metrics-file metrics.json
```

### Deploy to Cloud Functions

```bash
cd functions
./deploy.sh
```

### Testing & Deployment Notes

- **Local validation:**
  - `python scripts/extract_news_cli.py --dry-run --max-articles 2 --verbose` exercises all sources without Supabase writes.
  - `python scripts/extract_news_cli.py --environment prod --max-workers 6 --timeout 20 --output-format json --metrics-file metrics.json --dry-run` mirrors production concurrency while keeping writes disabled.
  - Manual smoke test:

    ```bash
    python - <<'PY'
    from src.functions.news_extraction.core.pipelines.news_pipeline import NewsPipeline
    from src.functions.news_extraction.core.config.loader import load_config
    from src.shared.utils.logging import setup_logging
    setup_logging()
    pipeline = NewsPipeline(load_config())
    result = pipeline.run(dry_run=True)
    print(result)
    PY
    ```

- **Cloud deployment flow:** create `functions/.env.yaml` with Supabase credentials, ensure it’s gitignored, then run `functions/deploy.sh`. The script validates that `main.py` and `.env.yaml` exist, jumps to the repo root, and deploys with `gcloud functions deploy news-extraction --gen2 --runtime python310 --source=. --entry-point extract_news --trigger-http --allow-unauthenticated --memory 512MB --timeout 540s --env-vars-file=src/functions/news_extraction/functions/.env.yaml --set-env-vars=PYTHONPATH=/workspace/src`.
- **Post-deploy tests:**

  ```bash
  FUNCTION_URL=$(gcloud functions describe news-extraction --region=us-central1 --gen2 --format="value(serviceConfig.uri)")
  curl -X POST "$FUNCTION_URL" -H 'Content-Type: application/json' -d '{}'
  curl -X POST "$FUNCTION_URL" -H 'Content-Type: application/json' -d '{"source":"ESPN","max_articles":10}'
  ```

  Watch logs with `gcloud functions logs read news-extraction --region=us-central1 --limit=50 --follow`.
- **Troubleshooting:**
  - `ModuleNotFoundError: src` → ensure `export PYTHONPATH="$(pwd):$PYTHONPATH"` before running scripts.
  - Connection errors → re-check `.env`/`.env.yaml` Supabase keys via `python -c "from src.shared.db import get_supabase_client; print(get_supabase_client())"`.
  - HTTP timeouts → increase `--timeout` or lower `--max-articles`; verify caching logs show hits (`Cached response for ...`).
  - `gcloud` not found → install the Google Cloud SDK (`brew install google-cloud-sdk`).
- **Performance expectations:** cold starts: 2–4 s, warm invocations: ~1–2 s for four sources (~20 items). Throughput improves by raising `--max-workers` (watch memory) and leaving HTTP `cache_ttl_seconds` at 300 to avoid redundant fetches.

## 📦 Structure

```
news_extraction/
├── core/                       # Core functionality
│   ├── config/                # YAML configuration & loader
│   │   ├── feeds.yaml        # Source definitions
│   │   └── loader.py         # Config loader with validation
│   ├── contracts/            # Data contracts
│   │   └── news_url.py       # NewsUrl model
│   ├── data/transformers/    # Data transformation
│   │   └── news_transformer.py
│   ├── db/                   # Database operations
│   │   └── writer.py         # Batch writer with retry logic
│   ├── extractors/           # Source extractors
│   │   ├── base.py          # Base extractor interface
│   │   ├── rss.py           # RSS feed extraction
│   │   ├── sitemap.py       # XML sitemap extraction
│   │   └── factory.py       # Extractor factory
│   ├── pipelines/            # Orchestration
│   │   └── news_pipeline.py # Main extraction pipeline
│   ├── processors/           # Data processing
│   │   └── url_processor.py # URL filtering & validation
│   ├── utils/                # Utilities
│   │   └── client.py        # HTTP client with caching
│   └── monitoring.py         # Metrics & structured logging
├── scripts/                   # CLI tools
│   └── extract_news_cli.py   # Main extraction script
├── functions/                 # Cloud Function deployment
│   └── main.py               # Entry point
├── requirements.txt           # Module dependencies
├── .env.example              # Example environment config
├── README.md                 # This file
└── DEPLOYMENT.md             # Testing & deployment guide
```

## 🔧 Configuration

### Environment Variables

Required in `.env`:
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### Source Configuration

Edit `core/config/feeds.yaml` to manage sources:

```yaml
sources:
  - name: ESPN
    type: rss
    url: https://www.espn.com/espn/rss/nfl/news
    enabled: true
    priority: high
    rate_limit: 60
    timeout: 10
    max_articles: 50
```

**Supported Types**: `rss`, `sitemap`

## 📊 CLI Usage

### Basic Commands

```bash
# Dry-run (preview without writing)
python scripts/extract_news_cli.py --dry-run

# Verbose output with debug logs
python scripts/extract_news_cli.py --verbose

# Clear existing data before loading
python scripts/extract_news_cli.py --clear

# Filter to specific source
python scripts/extract_news_cli.py --source "ESPN"

# Limit to recent articles
python scripts/extract_news_cli.py --days-back 7

# Limit articles per source
python scripts/extract_news_cli.py --max-articles 10
```

### Production Commands

```bash
# Production with full metrics
python scripts/extract_news_cli.py \
  --environment prod \
  --max-workers 6 \
  --timeout 20 \
  --output-format json \
  --metrics-file metrics.json

# Pretty JSON output (dry-run)
python scripts/extract_news_cli.py --dry-run --pretty --max-articles 3
```

### All Options

```bash
python scripts/extract_news_cli.py --help

Options:
  --dry-run              Preview without writing to database
  --clear                Clear existing records before loading
  --verbose, -v          Enable DEBUG logging
  --log-level LEVEL      Set logging level (DEBUG|INFO|WARNING|ERROR|CRITICAL)
  --source SOURCE        Filter to specific source (substring match)
  --days-back N          Only extract articles from last N days
  --max-articles N       Maximum articles per source
  --config PATH          Custom feeds.yaml path
  --environment ENV      Environment: dev|staging|prod
  --max-workers N        Concurrent workers (default: 4)
  --timeout SECONDS      HTTP timeout (default: from config)
  --output-format FMT    Output format: text|json
  --metrics-file PATH    Save detailed metrics to JSON file
  --pretty               Pretty-print JSON output
```

## 🌐 API

### POST /extract-news

Cloud Function endpoint for triggered extractions.

**Request:**
```json
{
  "source": "ESPN",
  "days_back": 7,
  "max_articles": 50
}
```

**Response:**
```json
{
  "success": true,
  "sources_processed": 1,
  "items_extracted": 45,
  "items_filtered": 2,
  "records_written": 43,
  "metrics": {
    "duration_seconds": 2.3,
    "items_per_second": 19.6
  }
}
```

## 🏗️ Architecture

### Production Features

- **Concurrent Processing**: ThreadPoolExecutor with configurable workers (default: 4)
- **HTTP Caching**: 300-second TTL reduces redundant requests by ~50%
- **Circuit Breaker**: Prevents cascading failures with CLOSED/OPEN/HALF_OPEN states
- **Batch Database Operations**: Configurable batch sizes for optimal throughput
- **Structured Monitoring**: JSON-formatted metrics with operation timings
- **Graceful Degradation**: Continues on partial failures

### Performance

**Typical Metrics** (4 sources, 20 items):
- Total time: ~0.9s
- Throughput: ~22 items/second
- Success rate: 100%
- HTTP requests: ~50% reduced via caching

## 🧪 Testing

```bash
# Quick test (2 articles per source)
python scripts/extract_news_cli.py --dry-run --max-articles 2 --verbose

# Full test with metrics
python scripts/extract_news_cli.py --dry-run --metrics-file test_metrics.json --pretty

# Validate specific source
python scripts/extract_news_cli.py --source "NFL" --dry-run --verbose
```

## 📚 Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Local testing & Cloud deployment
- **[Package Contract](../../../docs/package_contract.md)** - Request/response specification
- **[Architecture](../../../docs/architecture/function_isolation.md)** - Function isolation pattern

## 🔍 Monitoring

### Structured Logs

```json
{
  "run_id": "extraction_1759500993",
  "duration_seconds": 0.916,
  "sources": {"total": 4, "successful": 4, "failed": 0},
  "items": {"extracted": 20, "processed": 20, "filtered": 0},
  "performance": {"items_per_second": 21.8}
}
```

### Metrics Export

```bash
python scripts/extract_news_cli.py --metrics-file metrics.json
```

**Metrics File** (`metrics.json`):
```json
{
  "run_id": "extraction_1759500993",
  "start_time": "2025-10-03T14:16:33.149096+00:00",
  "end_time": "2025-10-03T14:16:34.065017+00:00",
  "duration_seconds": 0.916,
  "sources_total": 4,
  "sources_successful": 4,
  "items_extracted": 20,
  "items_per_second": 21.8,
  "errors": [],
  "warnings": []
}
```

## 🆘 Troubleshooting

### Import Errors

**Problem**: `ModuleNotFoundError: No module named 'src'`

**Solution**: Set PYTHONPATH from project root:
```bash
export PYTHONPATH="/path/to/T4L_data_loaders:$PYTHONPATH"
```

### Database Connection Issues

**Problem**: `SupabaseException: Invalid API key`

**Solution**: Verify `.env` has correct credentials:
```bash
# Check credentials
cat .env | grep SUPABASE

# Test connection
python -c "from src.shared.db import get_supabase_client; print(get_supabase_client())"
```

### Performance Issues

**Problem**: Slow extraction

**Solutions**:
- Increase workers: `--max-workers 8`
- Reduce timeout: `--timeout 10`
- Limit articles: `--max-articles 20`
- Check cache hits in logs (should see "Cached response")

---

**Production-ready with enterprise-grade reliability, monitoring, and performance.** 🚀

## � Adding New Sources

### RSS/Sitemap (No Code Required)
Simply edit `core/config/feeds.yaml`:

```yaml
sources:
  - name: New Source - NFL News
    type: rss  # or 'sitemap'
    url: https://newsource.com/rss/nfl
    publisher: New Source
    nfl_only: true
    enabled: true
```

### HTML/Custom Extractors (Requires Code)
1. Create extractor in `core/extractors/`:
```python
# core/extractors/html_extractor.py
from .base import BaseExtractor

class HtmlExtractor(BaseExtractor):
    def extract(self, source, **kwargs):
        # Custom extraction logic
        pass
```

2. Register in factory:
```python
# core/extractors/factory.py
EXTRACTOR_MAP = {
    'rss': RssExtractor,
    'sitemap': SitemapExtractor,
    'html': HtmlExtractor,  # Add this line
}
```

3. Add to config:
```yaml
- name: Custom HTML Source
  type: html
  url: https://example.com/nfl
  publisher: Example
  enabled: true
```

## 🧪 Testing

```bash
# Test with dry-run
python scripts/extract_news_cli.py --dry-run --verbose

# Test specific source
python scripts/extract_news_cli.py --source "ESPN" --dry-run --pretty

# Test date filtering
python scripts/extract_news_cli.py --days-back 1 --dry-run
```

## 🚨 Troubleshooting

**Import errors:** Make sure dependencies are installed
```bash
pip install -r requirements.txt
```

**Rate limiting:** Adjust `max_parallel_fetches` in `feeds.yaml` defaults

**Parse errors:** Check RSS/sitemap URL validity with `--verbose`

**No records:** Verify `enabled: true` in config and check date filters

## 📚 Related Documentation

- See `AGENTS.md` for repository architecture guidelines
- Cloud Function API: `../../docs/cloud_function_api.md`
- Shared utilities: `../../shared/`

### Environment Variables (.env)

```bash
# Supabase Configuration (REQUIRED)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key-here

# Logging (optional)
LOG_LEVEL=INFO
```

### Feed Sources (core/config/feeds.yaml)

Add or modify news sources in `feeds.yaml`:

```yaml
sources:
  - name: ESPN - NFL News
    type: rss
    url: https://www.espn.com/espn/rss/nfl/news
    publisher: ESPN
    nfl_only: true
    enabled: true

  - name: NFL.com - Articles Monthly Sitemap
    type: sitemap
    url_template: https://www.nfl.com/sitemap/html/articles/{YYYY}/{MM}
    publisher: NFL.com
    nfl_only: true
    enabled: true
    max_articles: 30
    days_back: 7
```

**Configuration Options:**
- `type`: `rss`, `sitemap`, or `html`
- `url`: Direct URL for RSS/HTML sources
- `url_template`: Template URL for sitemaps (supports `{YYYY}`, `{MM}` placeholders)
- `enabled`: Toggle source on/off
- `nfl_only`: If true, marks all items as NFL content
- `max_articles`: Limit per source
- `days_back`: Only process articles from last N days

## 📝 CLI Commands

### Basic Usage
```bash
# Dry run (preview without writing)
python scripts/extract_news_cli.py --dry-run

# Run with verbose logging
python scripts/extract_news_cli.py --verbose

# Clear existing data and reload
python scripts/extract_news_cli.py --clear
```

### Filtering Options
```bash
# Extract from specific source
python scripts/extract_news_cli.py --source "ESPN"

# Only articles from last 7 days
python scripts/extract_news_cli.py --days-back 7

# Limit articles per source
python scripts/extract_news_cli.py --max-articles 20

# Combine filters
python scripts/extract_news_cli.py --source "CBS" --days-back 3 --dry-run
```

### Output Options
```bash
# Pretty-print records in dry-run
python scripts/extract_news_cli.py --dry-run --pretty

# Custom config file
python scripts/extract_news_cli.py --config /path/to/feeds.yaml
```

## 🗄️ Database Schema

### news_urls Table

| Column          | Type      | Description                        |
|-----------------|-----------|----------------------------------- |
| url             | text (PK) | Article URL (unique)               |
| publisher       | text      | Source publisher name              |
| source_type     | text      | Type: rss, sitemap, html           |
| title           | text      | Article title (optional)           |
| published_date  | timestamp | Publication date (optional)        |
| extracted_date  | timestamp | When URL was extracted             |
| source_name     | text      | Specific source name               |
| description     | text      | Article description (optional)     |
| author          | text      | Article author (optional)          |
| tags            | text[]    | Tags/categories (optional)         |
| is_nfl_content  | boolean   | NFL relevance flag                 |

## 🏗️ Architecture

### Pipeline Flow
1. **Load Config** → Parse `feeds.yaml` and filter enabled sources
2. **Extract** → Fetch from RSS/sitemaps using appropriate extractors
3. **Process** → Validate URLs, deduplicate, filter by date/relevance
4. **Transform** → Convert to `NewsUrl` schema format
5. **Write** → Upsert to Supabase with conflict resolution on `url`

### Key Design Patterns
- **Extractor Factory**: Automatically routes to RSS/Sitemap/HTML extractor based on `type`
- **Configuration-Driven**: Add new sources via YAML without code changes
- **Rate Limiting**: Built-in rate limiter prevents API throttling
- **Deduplication**: URL-based dedup within extraction session
- **Upsert Logic**: Handles conflicts gracefully on re-runs

## 🔄 Adding New Sources

Required environment variables:
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_KEY`: Supabase API key
- `LOG_LEVEL`: Logging level (default: INFO)

## 🌐 API

### POST /news-extractor

Extract news URLs from specified sources.

**Request:**
```json
{
  "sources": ["espn", "nfl_com"],
  "date_range": {
    "start": "2024-01-01",
    "end": "2024-01-07"
  }
}
```

**Response:**
```json
{
  "urls": ["https://...", "https://..."],
  "count": 42,
  "source": "espn",
  "timestamp": "2024-01-07T10:30:00Z"
}
```

## ⚠️ Status

**This module is a placeholder and not yet implemented.**

TODO:
- [ ] Implement base extractor interface
- [ ] Add ESPN news extractor
- [ ] Add NFL.com news extractor
- [ ] Implement URL validation
- [ ] Add content parsing
- [ ] Create extraction pipeline
- [ ] Add CLI scripts
- [ ] Write unit tests
