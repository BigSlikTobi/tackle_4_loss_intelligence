# Content Pipeline - Quick Reference

## 🚀 Quick Start

### 1. Clean Database
```sql
-- Run in Supabase SQL Editor
TRUNCATE facts_embeddings CASCADE;
TRUNCATE news_facts CASCADE;
TRUNCATE story_embeddings CASCADE;
TRUNCATE context_summaries CASCADE;

UPDATE news_urls SET facts_extracted_at = NULL, summary_created_at = NULL
WHERE facts_extracted_at IS NOT NULL OR summary_created_at IS NOT NULL;
```

### 2. Process 5000 Most Recent URLs
```bash
cd src/functions/content_summarization
source venv/bin/activate

python scripts/content_pipeline_cli.py \
  --stage full \
  --limit 100 \
  --batch-mode \
  --max-total 5000 \
  --batch-delay 5
```

## 📊 Common Commands

### Process All URLs (No Limit)
```bash
python scripts/content_pipeline_cli.py --stage full --limit 50 --batch-mode
```

### Process Facts Only (Skip Content Extraction)
```bash
python scripts/content_pipeline_cli.py --stage facts --limit 100 --batch-mode --max-total 5000
```

### Single Batch (Test Run)
```bash
python scripts/content_pipeline_cli.py --stage full --limit 10
```

### Resume Interrupted Processing
```bash
# Just run the same command again - skips completed URLs automatically
python scripts/content_pipeline_cli.py --stage full --limit 100 --batch-mode --max-total 5000
```

## 🔍 Monitoring

### Check Progress
```sql
SELECT 
    COUNT(*) FILTER (WHERE facts_extracted_at IS NULL) as pending,
    COUNT(*) FILTER (WHERE summary_created_at IS NOT NULL) as completed,
    COUNT(*) as total
FROM news_urls;
```

### Check Processing Rate
```sql
SELECT 
    COUNT(*) FILTER (WHERE facts_extracted_at > NOW() - INTERVAL '1 hour') as processed_last_hour
FROM news_urls;
```

### Check Most Recent Processed
```sql
SELECT url, title, facts_extracted_at, summary_created_at
FROM news_urls
WHERE facts_extracted_at IS NOT NULL
ORDER BY facts_extracted_at DESC
LIMIT 10;
```

## ⚙️ Command Options

| Option | Description | Example |
|--------|-------------|---------|
| `--stage` | `content`, `facts`, `summary`, or `full` | `--stage full` |
| `--limit` | URLs per batch | `--limit 100` |
| `--batch-mode` | Loop until done | `--batch-mode` |
| `--max-total` | Stop after N total URLs | `--max-total 5000` |
| `--batch-delay` | Seconds between batches | `--batch-delay 5` |

## 💰 Cost Estimate

**For 5000 URLs:**
- Gemini API: ~$0.50
- OpenAI Embeddings: ~$10.00
- **Total: ~$10.50**

## 🛠️ Troubleshooting

### No URLs Found
```sql
-- Reset timestamps to reprocess
UPDATE news_urls SET facts_extracted_at = NULL;
```

### Too Many Timeouts
```bash
# Increase delay between batches
--batch-delay 10
```

### Rate Limit Errors
```bash
# Reduce batch size and increase delay
--limit 25 --batch-delay 10
```

## 📈 Expected Performance

- **Processing Rate**: ~15-20 URLs/minute
- **Time for 5000 URLs**: ~4-6 hours
- **Facts per URL**: 80-120 on average
- **Embeddings per URL**: Same as facts count

## 🔄 URL Ordering

URLs are automatically sorted by `published_date DESC` (most recent first).

Verify:
```sql
SELECT id, url, published_date FROM news_urls 
WHERE facts_extracted_at IS NULL 
ORDER BY published_date DESC LIMIT 5;
```

## ⚡ Pro Tips

1. Start with small test batch: `--limit 10` (no batch-mode)
2. Monitor first 100 URLs: check logs and database
3. Use reasonable delays: 3-5 seconds between batches
4. Save logs: `python script.py 2>&1 | tee pipeline.log`
5. Process during off-peak hours to maximize API quotas

## 📞 Need Help?

See full documentation: `BATCH_PROCESSING_GUIDE.md`
