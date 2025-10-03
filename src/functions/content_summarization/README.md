# Content Summarization Function

**Production-ready AI-powered content summarization** for NFL news articles using Google Gemini's URL context API with intelligent fallback strategies.

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Quick Start](#-quick-start)
- [Architecture](#-architecture)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Production Features](#-production-features)
- [Database Schema](#-database-schema)
- [Deployment](#-deployment)
- [Troubleshooting](#-troubleshooting)

---

## 🎯 Overview

This module generates comprehensive, fact-based summaries of NFL news articles from the `news_urls` table and stores structured results in the `context_summaries` table.

**What It Does:**
1. Fetches unsummarized URLs from database
2. Uses Google Gemini API to analyze content
3. Extracts structured information (players, teams, injuries, sentiment)
4. Stores summaries for downstream analysis

**Processing Approach:**
- **Primary**: Google Gemini URL Context API (fast, efficient)
- **Fallback**: Intelligent HTML scraping with BeautifulSoup (resilient)
- **Anti-Hallucination**: Explicit prompts to ensure factual accuracy

---

## ⚡ Key Features

### Production-Ready Components
✅ **Rate Limiting**: Token bucket algorithm prevents API throttling  
✅ **Retry Logic**: Exponential backoff for failed requests  
✅ **Circuit Breaker**: Automatic protection for problematic domains  
✅ **Connection Pooling**: Efficient HTTP session management  
✅ **Batch Processing**: Optimized database operations  
✅ **Metrics Collection**: Track performance and costs  
✅ **Health Checks**: Database connection verification  
✅ **Context Managers**: Proper resource cleanup  

### Intelligent Content Fetching
🌐 **Multi-Tier Strategy**: URL Context → HTTP → Browser Headers → HTML Parsing  
🛡️ **Circuit Breaker**: Skip failing domains after threshold  
📊 **Smart Extraction**: Prioritized HTML selectors for article content  
🔄 **Automatic Fallback**: Seamless switching between methods  

### AI Processing
🤖 **Anti-Hallucination Prompts**: Explicit instructions for factual content  
📝 **Structured Extraction**: Players, teams, games, injuries, sentiment  
🎯 **Low Temperature**: Deterministic, factual responses  
✅ **Optional Grounding**: Google Search verification  

---

## 🚀 Quick Start

### Installation

```bash
cd src/functions/content_summarization

# Create isolated environment
python -m venv venv
source venv/bin/activate  # or: venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### Configuration

Add to **central `.env` file** at project root:

```bash
# Google Gemini API (Required)
GEMINI_API_KEY=your-api-key  # Get from https://aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.5-flash

# Supabase (Should already exist)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# Optional Performance Tuning
MAX_REQUESTS_PER_MINUTE=60
MAX_RETRIES=3
BATCH_SIZE=10
LOG_LEVEL=INFO
```

### Run

```bash
# Dry-run: Preview without writing to database
python scripts/summarize_cli.py --dry-run --limit 5 --verbose

# Process 10 URLs
python scripts/summarize_cli.py --limit 10

# Process all unsummarized URLs
python scripts/summarize_cli.py

# Process specific publisher
python scripts/summarize_cli.py --publisher "ESPN" --limit 20
```

---

## 🏗️ Architecture

```
content_summarization/
├── core/
│   ├── contracts/          # Data models
│   │   └── __init__.py    # ContentSummary, NewsUrlRecord
│   ├── db/                 # Database operations
│   │   ├── reader.py      # Fetch URLs (with pagination)
│   │   └── writer.py      # Write summaries (with retry)
│   ├── llm/                # AI processing
│   │   ├── __init__.py    # GeminiClient + RateLimiter
│   │   └── content_fetcher.py  # Multi-strategy HTTP fetcher
│   └── pipelines/          # Orchestration
│       └── __init__.py    # SummarizationPipeline
├── scripts/
│   ├── summarize_cli.py   # Main CLI entry point
│   └── fix_encoded_urls.py  # Utility script
├── functions/              # Cloud Function deployment
│   ├── main.py
│   └── deploy.sh
├── requirements.txt
└── README.md              # This file
```

### Component Interaction

```
┌─────────────────┐
│   CLI/API       │
│  Entry Point    │
└────────┬────────┘
         ↓
┌─────────────────┐
│  Pipeline       │  ← Orchestrates workflow
│  Orchestrator   │
└─────┬───┬───┬───┘
      ↓   ↓   ↓
   ┌──────┴────────┐
   ↓               ↓
┌──────────┐  ┌──────────┐
│ Database │  │   LLM    │
│ Reader   │  │  Client  │
│          │  │          │
│ • Paging │  │ • Rate   │
│ • Filter │  │   Limit  │
└──────────┘  │ • Retry  │
              │ • Circuit│
              └────┬─────┘
                   ↓
              ┌──────────┐
              │ Content  │
              │ Fetcher  │
              │          │
              │ • Pool   │
              │ • Fallbk │
              └──────────┘
```

---

## ⚙️ Configuration

### Environment Variables

All configuration in **central `.env`** file at project root:

```bash
# ===== Required =====

# Google Gemini API
GEMINI_API_KEY=AI...              # Get from https://aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.5-flash     # or gemini-2.5-pro

# Supabase Database
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-service-role-key

# ===== Optional Performance Tuning =====

# Rate Limiting
MAX_REQUESTS_PER_MINUTE=60        # API calls per minute (default: 60)

# Retry Logic
MAX_RETRIES=3                     # Failed request retries (default: 3)

# Batch Processing
BATCH_SIZE=10                     # URLs per batch (default: 10)

# Logging
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### Model Selection

| Model | Speed | Cost (per 1M tokens) | Use Case |
|-------|-------|---------------------|----------|
| **gemini-2.5-flash** | ⚡ Fast | $0.075 input / $0.30 output | **Recommended** - Production use |
| **gemini-2.5-pro** | 🐌 Slow | $1.25 input / $5.00 output | High-value content requiring extra accuracy |

**Cost Example** (typical article: 5k input, 1k output tokens):
- Flash: ~$0.00067 per article ($6.70 per 10k articles)
- Pro: ~$0.01125 per article ($112.50 per 10k articles)

---

## 💻 Usage

### CLI Commands

```bash
# ===== Basic Usage =====

# Dry-run (preview, no database writes)
python scripts/summarize_cli.py --dry-run --limit 5 --verbose

# Process 10 URLs
python scripts/summarize_cli.py --limit 10

# Process all unsummarized URLs
python scripts/summarize_cli.py

# ===== Filtering =====

# Specific publisher
python scripts/summarize_cli.py --publisher "ESPN" --limit 20
python scripts/summarize_cli.py --publisher "CBS Sports"

# Specific URL IDs
python scripts/summarize_cli.py --url-ids "uuid1,uuid2,uuid3"

# ===== Model Options =====

# Use Pro model (higher quality)
python scripts/summarize_cli.py --model gemini-2.5-pro --limit 10

# Enable Google Search grounding
python scripts/summarize_cli.py --enable-grounding --limit 5

# ===== Error Handling =====

# Stop on first error (default: continue)
python scripts/summarize_cli.py --stop-on-error

# Verbose logging
python scripts/summarize_cli.py --verbose

# ===== Utility Scripts =====

# Fix URL-encoded URLs in database
python scripts/fix_encoded_urls.py
```

### Python API

```python
from src.functions.content_summarization.core.db import NewsUrlReader, SummaryWriter
from src.functions.content_summarization.core.llm import GeminiClient
from src.functions.content_summarization.core.pipelines import SummarizationPipeline

# Initialize with production settings
with GeminiClient(
    api_key="your-api-key",
    model="gemini-2.5-flash",
    enable_grounding=False,
    max_retries=3,
    max_requests_per_minute=60,
) as gemini_client:
    
    url_reader = NewsUrlReader()
    summary_writer = SummaryWriter(dry_run=False, max_retries=3)
    
    pipeline = SummarizationPipeline(
        gemini_client=gemini_client,
        url_reader=url_reader,
        summary_writer=summary_writer,
        continue_on_error=True
    )
    
    # Process URLs
    stats = pipeline.process_unsummarized_urls(limit=10)
    
    # Get metrics
    metrics = gemini_client.get_metrics()
    print(f"Success Rate: {metrics['success_rate_percent']:.1f}%")
    print(f"Avg Tokens: {metrics['average_tokens']:.0f}")
    print(f"Avg Time: {metrics['average_time_seconds']:.1f}s")
```

### HTTP API (Cloud Function)

```bash
# Process with limit
curl -X POST https://us-central1-PROJECT.cloudfunctions.net/content-summarization \
  -H 'Content-Type: application/json' \
  -d '{"limit": 10}'

# Specific publisher
curl -X POST https://us-central1-PROJECT.cloudfunctions.net/content-summarization \
  -H 'Content-Type: application/json' \
  -d '{"publisher": "ESPN", "limit": 20}'
```

---

## 🔧 Production Features

> **📚 For comprehensive production documentation, see [PRODUCTION_FEATURES.md](./PRODUCTION_FEATURES.md)**

This module includes enterprise-grade features for production deployments.

### 1. Rate Limiting

**Token Bucket Algorithm** prevents API throttling:
- Configurable: `MAX_REQUESTS_PER_MINUTE=60`
- Automatic waiting when limit reached
- Smooth, controlled API usage

### 2. Retry Logic with Exponential Backoff

- Automatic retries: 2s, 4s, 8s delays
- Configurable: `MAX_RETRIES=3`
- Handles transient errors gracefully

### 3. Circuit Breaker

- Skips failing domains after 5 failures
- Auto-reset after 5 minutes
- Saves API costs on consistently failing URLs

### 4. Connection Pooling

- Reuses HTTP connections (10 pools, 20 connections each)
- 3-5x faster than creating new connections
- Better resource utilization

### 5. Intelligent Fallback

**Multi-Strategy Content Fetching:**
1. URL Context API (Gemini)
2. Simple HTTP Request
3. Browser-Like Headers (anti-bot bypass)
4. BeautifulSoup HTML Parsing
5. Circuit Breaker (skip temporarily)

### 6. Database Optimization

- **Pagination**: Handles 6,530+ records in 1000-record batches
- **Batch Writing**: 100 records per batch with retry
- **Health Checks**: Connection verification on startup
- **Upsert Operations**: Idempotent writes

### 7. Metrics Collection

```python
metrics = gemini_client.get_metrics()
{
    "success_rate_percent": 95.0,
    "average_tokens": 4458,
    "average_time_seconds": 8.9,
    "total_requests": 100,
    "successful_requests": 95,
    "fallback_requests": 23
}
```

### 8. Resource Cleanup

- Context managers for automatic cleanup
- HTTP sessions closed properly
- No resource leaks

---

## 🗄️ Database Schema

### `context_summaries` Table

```sql
CREATE TABLE context_summaries (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    news_url_id UUID NOT NULL REFERENCES news_urls(id) UNIQUE,
    
    -- Complete structured summary (formatted text)
    summary_text TEXT NOT NULL,
    
    -- Processing metadata
    llm_model TEXT,
    fallback_used BOOLEAN DEFAULT FALSE,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_context_summaries_news_url_id ON context_summaries(news_url_id);
CREATE INDEX idx_context_summaries_generated_at ON context_summaries(generated_at DESC);
```

### Summary Format

The `summary_text` field contains structured sections:

```
═══════════════════════════════════════════════════
SUMMARY
═══════════════════════════════════════════════════
[3-5 paragraph comprehensive summary]

═══════════════════════════════════════════════════
KEY POINTS
═══════════════════════════════════════════════════
• [Point 1]
• [Point 2]
...

═══════════════════════════════════════════════════
PLAYERS MENTIONED
═══════════════════════════════════════════════════
• Player Name 1
• Player Name 2
...

[Additional sections: TEAMS, GAMES, INJURIES, METADATA]
```

---

## 🚀 Deployment

### Cloud Function Setup

1. **Prerequisites:**
   ```bash
   # Enable APIs
   gcloud services enable cloudfunctions.googleapis.com
   gcloud services enable secretmanager.googleapis.com
   ```

2. **Create Secrets:**
   ```bash
   # Store API keys in Secret Manager
   echo -n "your-gemini-api-key" | gcloud secrets create GEMINI_API_KEY --data-file=-
   echo -n "your-supabase-url" | gcloud secrets create SUPABASE_URL --data-file=-
   echo -n "your-supabase-key" | gcloud secrets create SUPABASE_KEY --data-file=-
   ```

3. **Deploy:**
   ```bash
   cd functions
   
   # Edit deploy.sh with your project ID
   nano deploy.sh
   
   # Deploy to Cloud Functions
   ./deploy.sh
   ```

4. **Verify:**
   ```bash
   # Test endpoint
   curl -X POST https://us-central1-PROJECT.cloudfunctions.net/content-summarization \
     -H 'Content-Type: application/json' \
     -d '{"limit": 2}'
   
   # View logs
   gcloud functions logs read content-summarization \
     --region=us-central1 \
     --limit=50
   ```

---

## 🐛 Troubleshooting

### Common Issues

#### 1. No URLs Found

**Problem:** "Found 0 URLs to process"

**Solutions:**
```bash
# Check news_urls table has data
# Check if already summarized
python scripts/summarize_cli.py --dry-run --verbose
```

#### 2. API Authentication Errors

**Problem:** "Invalid API key"

**Solutions:**
```bash
# Get new key
open https://aistudio.google.com/apikey

# Update .env
nano .env  # Add: GEMINI_API_KEY=AI...
```

#### 3. Rate Limit Errors

**Problem:** "429 Too Many Requests"

**Solutions:**
```bash
# Reduce request rate
export MAX_REQUESTS_PER_MINUTE=30
python scripts/summarize_cli.py --limit 10
```

#### 4. Content Fetch Failures

**Problem:** "All fallback methods failed"

**Common Causes:**
- ESPN/NFL.com: JavaScript-heavy, anti-bot protection
- Paywalls: Requires login
- Geo-blocking: Content restricted by region

**Solutions:**
```bash
# Check circuit breaker status
python scripts/summarize_cli.py --verbose

# Skip problematic domains
python scripts/summarize_cli.py --publisher "NBC Sports"
```

### Performance Issues

#### Slow Processing

**Solutions:**
- Use `gemini-2.5-flash` instead of Pro
- Increase `MAX_REQUESTS_PER_MINUTE`
- Reduce `MAX_RETRIES`
- Skip problematic publishers

---

## 📚 Resources

### Documentation
- [Project Architecture](../../../docs/architecture/function_isolation.md)
- [Main Project README](../../../README.md)
- [Agent Guidelines](../../../AGENTS.md)

### External Resources
- [Google Gemini URL Context API](https://ai.google.dev/gemini-api/docs/url-context)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Get API Key](https://aistudio.google.com/apikey)

### Related Modules
- **news_extraction**: Provides `news_urls` table (source data)
- **data_loading**: NFL data for entity validation
- **shared**: Database connection and logging utilities

---

## 🤝 Development Guidelines

Following function-based isolation (see [`AGENTS.md`](../../../AGENTS.md)):

✅ **Self-contained**: Can be deleted without affecting other modules  
✅ **Independent dependencies**: Own `requirements.txt` and virtualenv  
✅ **Separate deployment**: Deploy to Cloud Functions independently  
✅ **Minimal shared code**: Only uses generic utilities from `src/shared/`  

---

**Questions?** Check [Troubleshooting](#-troubleshooting) or review the [Architecture Documentation](../../../docs/architecture/function_isolation.md).
