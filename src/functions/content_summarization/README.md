# Content Summarization Module

## Module Boundaries

> ⚠️ **Important:** This module is responsible **only for summary generation**. It consumes facts that were extracted by upstream modules and produces summaries for downstream consumption.

### Pipeline Position

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           UPSTREAM MODULES                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│  1. news_extraction        → Discovers news URLs → inserts into `news_urls`     │
│  2. url_content_extraction → Fetches article text → sets `content_extracted_at` │
│  3. url_content_extraction → Extracts atomic facts → writes to `news_facts`     │
│                              → sets `facts_extracted_at`                        │
│  4. knowledge_extraction   → Extracts topics/entities from facts                │
│                            → writes to `news_fact_topics`, `news_fact_entities` │
│                            → sets `knowledge_extracted_at`                      │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      THIS MODULE: content_summarization                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│  5. Summary Generation     → Reads facts from `news_facts`                      │
│                            → Generates summaries using GPT-5-nano               │
│                            → Writes to `context_summaries` or `topic_summaries` │
│                            → Creates summary embeddings in `story_embeddings`   │
│                            → Sets `summary_created_at`                          │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          DOWNSTREAM MODULES                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│  6. story_embeddings       → Uses summaries for similarity search               │
│  7. story_grouping         → Clusters similar stories into groups               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Prerequisites

Before running this module, articles must have:
- ✅ `facts_extracted_at IS NOT NULL` — Facts exist in `news_facts`
- ✅ `knowledge_extracted_at IS NOT NULL` — Topics/entities extracted
- ❌ `summary_created_at IS NULL` — Summary not yet generated

### What This Module Does NOT Do

| Task | Responsible Module |
|------|-------------------|
| Fetch article content | `url_content_extraction` |
| Extract atomic facts | `url_content_extraction` |
| Extract topics/entities from facts | `knowledge_extraction` |
| Group similar stories | `story_grouping` |

---

## Overview

This module generates **factual summaries** from pre-extracted facts. It reads atomic facts from the `news_facts` table and produces concise summaries using GPT-5-nano with the OpenAI Batch API for cost efficiency (~50% savings).

**Article Classification:**
- **Easy articles** (single topic, ≤3 teams, ≤50 facts) → One summary in `context_summaries`
- **Hard articles** (multiple topics/entities) → Topic-scoped summaries in `topic_summaries`

---

## Quick Start Guide

### Step 1: Set Up Environment
```bash
cd src/functions/content_summarization
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Verify Prerequisites
```sql
-- Check for articles ready for summarization
SELECT COUNT(*) 
FROM news_urls 
WHERE knowledge_extracted_at IS NOT NULL 
  AND summary_created_at IS NULL;
```

### Step 3: Choose Processing Method

| Method | Best For | Cost | Speed |
|--------|----------|------|-------|
| **Batch API** | 100+ articles | ~50% cheaper | 24h window |
| **Synchronous** | 1-100 articles | Standard | Immediate |

---

## Step-by-Step: Batch API Processing (Recommended)

The OpenAI Batch API provides ~50% cost savings with a 24-hour completion window. Use this for bulk processing of 100+ articles.

### Step 1: Create and Submit a Batch
```bash
# Process up to 500 pending articles (newest first)
python scripts/summary_batch_cli.py --task all --limit 500
```

**Output:** `Batch created: batch_692770acb77481908762f13c2779ed61`

### Step 2: Check Batch Status (Wait for Completion)
```bash
python scripts/summary_batch_cli.py --status batch_692770acb77481908762f13c2779ed61
```

**Status progression:** `validating` → `in_progress` → `completed`

### Step 3: Process Completed Results
```bash
python scripts/summary_batch_cli.py --process batch_692770acb77481908762f13c2779ed61
```

### Batch CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--task` | `all` | Article type to process: `easy` (single-topic), `hard` (multi-topic), or `all` |
| `--limit` | `500` | Maximum articles to include in batch (fetches newest first) |
| `--model` | `gpt-5-nano` | OpenAI model for summary generation |
| `--output-dir` | `./batch_files` | Directory to store batch JSONL files |
| `--status` | - | Check status for a specific batch ID |
| `--process` | - | Download and process results for a completed batch |
| `--skip-existing` | `false` | Skip articles that already have summaries |
| `--no-embeddings` | `false` | Skip creating summary embeddings (faster processing) |
| `--dry-run` | `false` | Preview what would be processed without writing to database |
| `--no-submit` | `false` | Generate JSONL file only, don't submit to OpenAI |

---

## Step-by-Step: Synchronous Processing (Small Batches)

Use synchronous processing for testing, manual corrections, or small batches under 100 articles.

### Basic Usage
```bash
# Generate summaries for 20 articles
python scripts/content_pipeline_cli.py --stage summary --limit 20
```

### Loop Mode (Continuous Processing)
```bash
# Process continuously until queue is empty or limit reached
python scripts/content_pipeline_cli.py --stage summary --loop --max-total 500 --batch-delay 5
```

### Synchronous CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--stage` | `facts` | Pipeline stage to run: `content`, `facts`, `knowledge`, `summary`, or `full` |
| `--limit` | `25` | Number of articles to fetch per batch iteration |
| `--loop` | `false` | Enable loop mode - keeps processing batches until no pending URLs remain |
| `--max-total` | unlimited | Maximum total URLs to process across all loop iterations (prevents runaway processing) |
| `--batch-delay` | `2` | Seconds to wait between batch iterations (protects API rate limits) |

### Flag Details

**`--stage`**: Selects which pipeline stage to run
- `summary` — Generate summaries from existing facts (most common)
- `knowledge` — Extract topics/entities from facts (rarely needed, use `knowledge_extraction` module)
- `facts` — Extract facts from content (rarely needed, use `url_content_extraction` module)
- `content` — Fetch raw article content (rarely needed)
- `full` — Run all stages sequentially

**`--limit`**: Controls batch size
- Lower values (10-25) = safer for testing, lower memory usage
- Higher values (50-100) = faster throughput, higher memory usage
- Articles are fetched newest first (ORDER BY created_at DESC)

**`--loop`**: Enables continuous processing
- Without `--loop`: Processes one batch and exits
- With `--loop`: Keeps fetching and processing batches until queue is empty
- Combine with `--max-total` to limit total processing

**`--max-total`**: Safety limit for loop mode
- Prevents processing more than N articles total
- Example: `--loop --max-total 5000` processes up to 5000 articles then stops
- Useful for controlled batch runs during off-peak hours

**`--batch-delay`**: Pause between iterations
- Prevents API rate limiting
- Default 2 seconds is conservative
- Increase to 5-10 seconds if hitting rate limits

### Example Workflows

```bash
# Test with a small batch
python scripts/content_pipeline_cli.py --stage summary --limit 10

# Process 500 articles with delays
python scripts/content_pipeline_cli.py --stage summary --loop --max-total 500 --batch-delay 5

# Overnight bulk run (processes until queue empty or 10k reached)
python scripts/content_pipeline_cli.py --stage summary --loop --max-total 10000 --batch-delay 3 | tee summary.log
```

---

## Database Tables

### Tables Written By This Module

| Table | Purpose |
|-------|---------|
| `context_summaries` | Article-level summaries for "easy" articles |
| `topic_summaries` | Topic-scoped summaries for "hard" articles |
| `story_embeddings` | Summary embeddings (`embedding_type = 'summary'`) |

### Tables Consumed (Read-Only)

| Table | Purpose |
|-------|---------|
| `news_urls` | Article metadata and pipeline timestamps |
| `news_facts` | Atomic facts (input for summarization) |
| `news_fact_topics` | Topic classification per fact |
| `news_fact_entities` | Entity references per fact |

---

## Bulk Database Operations

The batch result processor uses bulk operations for efficiency:

| Operation | Before | After |
|-----------|--------|-------|
| DB calls for 500 articles | ~2000 | ~30 |

All operations are chunked (100 records per chunk):
- Bulk clear existing summaries/embeddings
- Bulk insert context_summaries
- Bulk insert topic_summaries  
- Bulk create embeddings (100 texts per OpenAI API call)
- Bulk update news_urls.summary_created_at

---

## Model Configuration

| Task | Default Model | Provider |
|------|---------------|----------|
| Summary Generation | `gpt-5-nano` | OpenAI |
| Embeddings | `text-embedding-3-small` | OpenAI |

### Reasoning Model Handling

GPT-5-nano is a reasoning model. The pipeline automatically adjusts API parameters:

| Parameter | Standard Models | Reasoning Models (gpt-5-nano) |
|-----------|-----------------|-------------------------------|
| `temperature` | 0.1 | Not used |
| `system` message | Yes | No (user message only) |
| `max_completion_tokens` | default | 4000 (batch) / 16000 (sync) |
| `reasoning_effort` | Not used | `"low"` |

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `SUPABASE_URL` | Yes | Database connection URL |
| `SUPABASE_KEY` | Yes | Database service role key |
| `OPENAI_API_KEY` | Yes | OpenAI Batch API and embeddings |
| `SUMMARY_LLM_MODEL` | No | Override summary model (default: `gpt-5-nano`) |
| `OPENAI_EMBEDDING_MODEL` | No | Override embedding model (default: `text-embedding-3-small`) |
| `BATCH_LIMIT` | No | Default batch size for synchronous processing |
| `LLM_TIMEOUT_SECONDS` | No | Timeout for LLM requests (default: 60) |

---

## Monitoring

### Progress Check
```sql
SELECT 
  COUNT(*) FILTER (WHERE summary_created_at IS NULL AND knowledge_extracted_at IS NOT NULL) AS pending,
  COUNT(*) FILTER (WHERE summary_created_at IS NOT NULL) AS completed
FROM news_urls;
```

### Recent Summaries
```sql
SELECT url, title, summary_created_at 
FROM news_urls 
WHERE summary_created_at IS NOT NULL 
ORDER BY summary_created_at DESC 
LIMIT 10;
```

### Hourly Throughput
```sql
SELECT COUNT(*) 
FROM news_urls 
WHERE summary_created_at > NOW() - INTERVAL '1 hour';
```

---

## Cost Guidance

| Method | Cost per 500 Articles |
|--------|----------------------|
| Batch API (gpt-5-nano) | ~$0.25 |
| Synchronous (gpt-5-nano) | ~$0.50 |
| Embeddings (text-embedding-3-small) | ~$2.00 |

**Pro tip:** Use Batch API for anything over 100 articles to save ~50% on LLM costs.

---

## Troubleshooting

### "No pending URLs found"
Articles must have `knowledge_extracted_at IS NOT NULL` and `summary_created_at IS NULL`. Check upstream modules.

### "Batch status: failed"
Check the batch error output. Common issues:
- Invalid JSON in facts
- Token limits exceeded
- API key permissions

### Rate limiting
Increase `--batch-delay` or reduce `--limit` for synchronous processing.

---

## Architecture Notes

- Follows **function-based isolation** (see `AGENTS.md`)
- Imports only from `src/shared/` for logging, env, and DB connection
- Does NOT import from upstream modules (`url_content_extraction`, `knowledge_extraction`)
- Can be deleted without affecting other modules
