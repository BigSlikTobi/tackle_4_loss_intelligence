# Content Summarization Pipeline - Batch Processing Guide

## Overview

The content summarization pipeline now supports batch processing mode, allowing you to process large volumes of URLs efficiently in controlled batches.

## Quick Start

### 1. Cleanup Database (Fresh Start)

Run this SQL in Supabase SQL Editor to reset everything:

```sql
-- Delete all fact-related data
TRUNCATE facts_embeddings CASCADE;
TRUNCATE news_facts CASCADE;
TRUNCATE story_embeddings CASCADE;
TRUNCATE context_summaries CASCADE;

-- Reset timestamps so URLs will be picked up again
UPDATE news_urls 
SET 
    facts_extracted_at = NULL,
    summary_created_at = NULL
WHERE facts_extracted_at IS NOT NULL 
   OR summary_created_at IS NOT NULL;

-- Verify the reset
SELECT 
    COUNT(*) FILTER (WHERE content_extracted_at IS NOT NULL) as with_content,
    COUNT(*) FILTER (WHERE facts_extracted_at IS NOT NULL) as with_facts,
    COUNT(*) FILTER (WHERE summary_created_at IS NOT NULL) as with_summaries,
    COUNT(*) as total
FROM news_urls;
```

**Expected Result:**
- `with_facts`: 0 (all reset)
- `with_summaries`: 0 (all reset)
- `total`: Your total URL count

### 2. Process Most Recent 5000 URLs

```bash
cd src/functions/content_summarization
source venv/bin/activate

# Process 5000 most recent URLs in batches of 100
python scripts/content_pipeline_cli.py \
  --stage full \
  --limit 100 \
  --batch-mode \
  --max-total 5000 \
  --batch-delay 5
```

## Command-Line Options

### Basic Options (Works in Both Modes)

| Option | Description | Example |
|--------|-------------|---------|
| `--stage` | Pipeline stage: `content`, `facts`, `summary`, or `full` | `--stage full` |
| `--limit` | Number of URLs per batch | `--limit 100` |

### Batch Mode Options

| Option | Description | Example |
|--------|-------------|---------|
| `--batch-mode` | Enable batch processing (loops until done) | `--batch-mode` |
| `--max-total` | Stop after processing this many URLs total | `--max-total 5000` |
| `--batch-delay` | Seconds to wait between batches (default: 2) | `--batch-delay 5` |

## Usage Examples

### Process Most Recent 5000 URLs (Recommended for 12K Dataset)

```bash
python scripts/content_pipeline_cli.py \
  --stage full \
  --limit 100 \
  --batch-mode \
  --max-total 5000 \
  --batch-delay 5
```

**What happens:**
- Fetches 100 URLs at a time (most recent first, DESC order)
- Processes: content → facts → embeddings → summary
- Waits 5 seconds between batches (rate limit protection)
- Stops after 5000 total URLs
- Progress logged for each batch

**Estimated time:** ~5-6 hours for 5000 URLs (assuming ~4-5s per URL)

### Process All Pending URLs (No Limit)

```bash
python scripts/content_pipeline_cli.py \
  --stage full \
  --limit 50 \
  --batch-mode \
  --batch-delay 3
```

**What happens:**
- Processes ALL URLs with NULL `facts_extracted_at`
- Continues until no more pending URLs
- Good for complete processing of entire dataset

### Process Only Facts Stage (Skip Content Extraction)

```bash
python scripts/content_pipeline_cli.py \
  --stage facts \
  --limit 100 \
  --batch-mode \
  --max-total 5000 \
  --batch-delay 3
```

**What happens:**
- Only processes facts extraction (assumes content already extracted)
- Faster if content extraction is already complete

### Single Batch (Original Behavior)

```bash
# Just process one batch of 50 URLs and stop
python scripts/content_pipeline_cli.py --stage full --limit 50
```

## Progress Tracking

Batch mode provides detailed logging:

```
2025-11-14 [INFO] Starting batch mode: stage=full, batch_size=100, max_total=5000, batch_delay=5
2025-11-14 [INFO] === Batch 1 ===: batch_size=100, total_processed=0, remaining=5000
2025-11-14 [INFO] Processing 100 URLs in batch 1
2025-11-14 [INFO] Processing content stage: count=100
2025-11-14 [INFO] Processing facts stage: count=100
2025-11-14 [INFO] Processing summary stage: count=100
2025-11-14 [INFO] Batch 1 complete: processed_this_batch=100, total_processed=100, max_total=5000
2025-11-14 [INFO] Waiting 5s before next batch...

2025-11-14 [INFO] === Batch 2 ===: batch_size=100, total_processed=100, remaining=4900
...

2025-11-14 [INFO] Reached max_total limit of 5000, stopping
2025-11-14 [INFO] Batch mode complete: total_batches=50, total_urls_processed=5000
```

## URL Ordering

**Important:** URLs are automatically sorted by `published_date DESC` (most recent first) by the edge function.

Verify ordering in Supabase SQL:

```sql
-- Check that most recent URLs will be processed first
SELECT id, url, title, published_date, content_extracted_at, facts_extracted_at
FROM news_urls
WHERE facts_extracted_at IS NULL
ORDER BY published_date DESC
LIMIT 10;
```

## Monitoring Progress

### Check How Many URLs Remain

```sql
-- Total pending for each stage
SELECT 
    COUNT(*) FILTER (WHERE content_extracted_at IS NULL) as pending_content,
    COUNT(*) FILTER (WHERE content_extracted_at IS NOT NULL AND facts_extracted_at IS NULL) as pending_facts,
    COUNT(*) FILTER (WHERE facts_extracted_at IS NOT NULL AND summary_created_at IS NULL) as pending_summary,
    COUNT(*) FILTER (WHERE summary_created_at IS NOT NULL) as completed
FROM news_urls;
```

### Check Processing Rate

```sql
-- URLs processed in last hour
SELECT 
    COUNT(*) FILTER (WHERE facts_extracted_at > NOW() - INTERVAL '1 hour') as facts_last_hour,
    COUNT(*) FILTER (WHERE summary_created_at > NOW() - INTERVAL '1 hour') as summaries_last_hour
FROM news_urls;
```

### Find Failed URLs

```sql
-- URLs with extraction errors (if retry tracking is enabled)
SELECT url, content_extraction_retries, content_extraction_error, last_attempt_at
FROM news_urls
WHERE content_extraction_retries >= 3
ORDER BY last_attempt_at DESC
LIMIT 20;
```

## Error Handling

### Timeouts and Failures

- URLs that fail (timeout, extraction error) will **keep their NULL timestamp**
- Next batch will automatically retry them
- Set `SKIP_FAILED_URLS=true` in `.env` to skip after `MAX_RETRIES` failures

### Interrupted Processing

If you stop the pipeline (Ctrl+C):
- Already processed URLs have timestamps set (won't be reprocessed)
- Incomplete URLs remain with NULL timestamps (will be picked up next run)
- Just restart with same command to continue

### Rate Limits

If you hit API rate limits:
- Increase `--batch-delay` (e.g., from 5 to 10 seconds)
- Decrease `--limit` (e.g., from 100 to 50 URLs per batch)
- Check Gemini API quotas: https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas

## Cost Estimation

### API Costs for 5000 URLs

**Gemini API (gemini-2.5-flash-lite):**
- Facts extraction: ~5000 requests × $0.0001 = **$0.50**
- Average 1000 tokens input + 500 tokens output per article

**OpenAI API (text-embedding-3-small):**
- Embeddings: ~5000 URLs × 100 facts/URL × $0.00002 = **$10.00**
- Average 100 facts per article, each fact embedded

**Total estimated cost: ~$10.50 for 5000 URLs**

### Actual costs may vary based on:
- Article length (longer = more facts = more embeddings)
- Fact extraction quality (more facts = more embeddings)
- API pricing changes

## Configuration

### Environment Variables

Add to `.env`:

```bash
# Batch Processing
MAX_RETRIES=3                 # Retry failed URLs up to 3 times
SKIP_FAILED_URLS=false       # false = always retry, true = skip after MAX_RETRIES

# Rate Limiting
MAX_REQUESTS_PER_MINUTE=60   # API rate limit

# Logging
LOG_LEVEL=INFO               # DEBUG for verbose output
```

## Troubleshooting

### "No more pending URLs" immediately

**Cause:** All URLs already have `facts_extracted_at` set

**Solution:** Run the cleanup SQL to reset timestamps

### "Failed to parse Gemini response"

**Cause:** Gemini API returned incomplete JSON (hitting token limit)

**Solution:** Already fixed with `maxOutputTokens: 8192` in latest code

### "No fact embeddings available for pooling"

**Cause:** Old data with NULL embedding vectors

**Solution:** Run cleanup SQL to truncate and reset

### Too many timeouts

**Cause:** Content extraction service timing out (>45 seconds)

**Solutions:**
1. Increase timeout in config (not recommended - indicates site blocking)
2. Skip problematic URLs: they'll be retried next run
3. Manual review: check which domains are timing out consistently

## Best Practices

1. **Start with smaller batches** (50-100 URLs) to test
2. **Monitor first few batches** to ensure quality
3. **Use reasonable delays** (3-5 seconds) to avoid rate limits
4. **Process most recent content** (more relevant for NFL season)
5. **Check costs** periodically in API consoles
6. **Save logs** for debugging: `python script.py > pipeline.log 2>&1`

## Advanced: Parallel Processing

For even faster processing, run multiple pipelines in parallel on different stages:

**Terminal 1 (Facts):**
```bash
python scripts/content_pipeline_cli.py --stage facts --limit 100 --batch-mode --max-total 5000
```

**Terminal 2 (Summaries):**
```bash
python scripts/content_pipeline_cli.py --stage summary --limit 100 --batch-mode --max-total 5000
```

This works because each stage depends on the previous stage's timestamp, so they won't conflict.

## Support

For issues or questions:
- Check logs: `tail -f pipeline.log`
- Query database: Use SQL queries above
- Review API quotas: Check Google Cloud Console and OpenAI dashboard
