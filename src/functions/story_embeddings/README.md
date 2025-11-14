# Story Embeddings Module

Production-ready vector embeddings for NFL news story summaries using OpenAI's text-embedding-3-small model. Enables similarity search and story clustering.

---

## Overview

**What it does:** Generates 1536-dimensional vector embeddings for content summaries, enabling similarity search and story grouping for NFL news analysis.

### Fact-First Enhancements
- `facts_embeddings`: Stores per-fact vectors created by the content_summarization pipeline.
- `story_embeddings` with `embedding_type = 'fact_pooled'`: Mean vector across all fact embeddings for a URL, giving downstream modules a dense representation before a summary exists.
- `story_embeddings` with `embedding_type = 'summary'`: Embedding of the fact-grounded summary text.

**Status:** ✅ Production Ready

**Key Features:**
- Smart processing (only embeds new summaries via LEFT JOIN)
- Production-grade OpenAI API integration
- Rate limiting and timeout handling  
- Comprehensive error recovery
- Batch operations and cost tracking
- Dry-run and progress monitoring

---

## Quick Start

### 1. Install

```bash
cd src/functions/story_embeddings
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

Add to **central `.env`** file at project root:

```bash
OPENAI_API_KEY=sk-proj-...your-key
```

Get your key: https://platform.openai.com/api-keys

### 3. Create Database Table

Run `schema.sql` in Supabase SQL Editor. **Important:** Ensure the UNIQUE constraint on `news_url_id` is added:

```sql
ALTER TABLE story_embeddings 
ADD CONSTRAINT story_embeddings_news_url_id_unique 
UNIQUE (news_url_id);
```

### 4. Run

```bash
# Check progress
python scripts/generate_embeddings_cli.py --progress

# Test (no changes)
python scripts/generate_embeddings_cli.py --dry-run --limit 5

# Generate embeddings
python scripts/generate_embeddings_cli.py --limit 50 --verbose
```

---

## Usage

### Commands

```bash
# Show progress statistics
python scripts/generate_embeddings_cli.py --progress

# Dry-run test
python scripts/generate_embeddings_cli.py --dry-run --limit 10

# Generate specific count
python scripts/generate_embeddings_cli.py --limit 100

# Generate all with verbose logging
python scripts/generate_embeddings_cli.py --verbose

# Use different model
python scripts/generate_embeddings_cli.py --model text-embedding-3-large
```

### Python API

```python
from src.functions.story_embeddings.core.db import SummaryReader, EmbeddingWriter
from src.functions.story_embeddings.core.llm import OpenAIEmbeddingClient
from src.functions.story_embeddings.core.pipelines import EmbeddingPipeline

# Initialize
openai_client = OpenAIEmbeddingClient(
    timeout=30.0,
    max_tokens_per_minute=50000  # Optional rate limit
)
summary_reader = SummaryReader()
embedding_writer = EmbeddingWriter()

pipeline = EmbeddingPipeline(
    openai_client=openai_client,
    summary_reader=summary_reader,
    embedding_writer=embedding_writer,
)

# Generate
stats = pipeline.process_summaries_without_embeddings(limit=100)
print(f"Success: {stats['successful']}, Cost: ${stats['usage']['estimated_cost_usd']}")
```

---

## Architecture

### Module Structure

```
story_embeddings/
├── core/                    # Business logic
│   ├── contracts/           # Data models (SummaryRecord, StoryEmbedding)
│   ├── db/                  # Database access (reader, writer)
│   ├── llm/                 # OpenAI client with production features
│   └── pipelines/           # Orchestration pipeline
├── scripts/                 # CLI tools
├── requirements.txt         # Dependencies
├── .env.example             # Config template
├── schema.sql               # Database schema
└── README.md                # This file
```

### Data Flow

```
context_summaries (from content_summarization module)
    ↓
SummaryReader (LEFT JOIN: fetch summaries WITHOUT embeddings)
    ↓  
OpenAIEmbeddingClient (text-embedding-3-small API)
    ↓
EmbeddingWriter (batch write to DB)
    ↓
story_embeddings table (1536-dim vectors)
```

### Production Features

**OpenAI Client:**
- Timeout handling (30s default)
- Connection pooling
- Automatic retry with exponential backoff
- Rate limiting (token-based throttling)
- Comprehensive error recovery (timeout, connection, API errors)
- Cost tracking

**Database Operations:**
- Efficient pagination (1000 records/batch)
- Upsert with UNIQUE constraint
- Fallback to insert if constraint missing
- Batch operations for performance
- Connection health checks

**Pipeline:**
- Continue-on-error for resilience
- Progress tracking
- Dry-run support
- Detailed statistics and metrics

---

## Database Schema

### Input: `context_summaries`
Created by `content_summarization` module:

| Column | Type | Description |
|--------|------|-------------|
| `news_url_id` | UUID | Foreign key to news_urls |
| `summary_text` | TEXT | Text content to embed |
| `created_at` | TIMESTAMP | When summary was created |

### Output: `story_embeddings`
Created by this module:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key (auto-generated) |
| `news_url_id` | UUID | Foreign key (UNIQUE constraint) |
| `embedding_vector` | VECTOR(1536) | 1536-dimensional embedding |
| `model_name` | TEXT | Model used |
| `generated_at` | TIMESTAMP | When embedding was generated |
| `created_at` | TIMESTAMP | Database creation timestamp |

**Key Design:**
- `news_url_id` UNIQUE constraint prevents duplicates
- LEFT JOIN logic ensures only new summaries are processed
- pgvector extension required for VECTOR type

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | OpenAI API key |
| `SUPABASE_URL` | Yes | - | Supabase project URL |
| `SUPABASE_KEY` | Yes | - | Supabase service role key |
| `LOG_LEVEL` | No | INFO | Logging level |

### Cost Estimation

**Model:** text-embedding-3-small  
**Cost:** $0.00002 per 1K tokens (~$0.02 per million tokens)

| Summaries | Est. Tokens | Cost |
|-----------|-------------|------|
| 100 | 20,000 | $0.0004 |
| 1,000 | 200,000 | $0.004 |
| 10,000 | 2,000,000 | $0.04 |
| 100,000 | 20,000,000 | $0.40 |

**Very affordable!** The CLI shows estimated costs after each run.

---

## Module Independence

This module follows **function-based isolation** principles:

✅ **Complete Independence**
- Can be deleted without affecting other modules
- No imports from `data_loading`, `news_extraction`, or `content_summarization`

✅ **Isolated Dependencies**  
- Own `requirements.txt` with `openai>=1.0.0`
- Own virtual environment

✅ **Shared Utilities Only**
- Uses `src.shared.utils.logging` (generic)
- Uses `src.shared.utils.env` (generic)
- Uses `src.shared.db.connection` (generic)

✅ **Separate Deployment**
- Can be deployed independently to Cloud Functions (future)
- Own configuration with `.env.example`

---

## Troubleshooting

### "OpenAI API key not found"
→ Add `OPENAI_API_KEY=your-key` to central `.env` at project root

### "story_embeddings table not accessible"
→ Run `schema.sql` in Supabase SQL Editor  
→ Verify `SUPABASE_URL` and `SUPABASE_KEY` are correct

### "no unique or exclusion constraint" error
→ Add UNIQUE constraint: `ALTER TABLE story_embeddings ADD CONSTRAINT story_embeddings_news_url_id_unique UNIQUE (news_url_id);`

### Rate limit errors
→ Client automatically retries with exponential backoff  
→ Use `--limit` for smaller batches  
→ Consider setting `max_tokens_per_minute` parameter

### Import errors
→ Activate virtualenv: `source venv/bin/activate`  
→ Install deps: `pip install -r requirements.txt`

---

## Monitoring

### Progress Tracking

```bash
python scripts/generate_embeddings_cli.py --progress
```

Output:
```
============================================================
EMBEDDING PROGRESS
============================================================
Total Summaries:                250
With Embeddings:                100
Without Embeddings:             150
Completion:                     40.0%
============================================================
```

### Cost Tracking

Automatically displayed after each run:
```
OpenAI API Usage:
  Total Requests:         100
  Total Tokens:           20000
  Estimated Cost:         $0.0004
```

### Verbose Logging

```bash
LOG_LEVEL=DEBUG python scripts/generate_embeddings_cli.py --limit 5 --verbose
```

---

## Files Reference

- **`schema.sql`** - Database schema with indexes and constraints
- **`.env.example`** - Configuration template
- **`requirements.txt`** - Python dependencies  
- **`scripts/generate_embeddings_cli.py`** - CLI tool
- **`core/`** - Business logic (contracts, db, llm, pipelines)

---

## Next Steps

### Immediate
1. ✅ Follow Quick Start above
2. ✅ Test with `--dry-run` first
3. ✅ Start with small batches (`--limit 50`)

### Future Enhancements
- [ ] Cloud Function deployment for automated processing
- [ ] Webhook integration for real-time embedding generation
- [ ] Similarity search utilities (find related stories)
- [ ] Story clustering based on embeddings
- [ ] Re-embedding strategy for updated summaries

---

**Production-ready and following all architecture guidelines!** 🚀

For questions about the architecture, see `docs/architecture/function_isolation.md` in the project root.
