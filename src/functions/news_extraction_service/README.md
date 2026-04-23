# news_extraction_service

Async wrapper around `news_extraction.NewsExtractionPipeline` using the
**submit / poll / worker** pattern (mirrors `article_knowledge_extraction`
and `url_content_extraction_service`).

**This service is pure extraction — it never writes to the database.**
The legacy module's `NewsUrlWriter` is never instantiated, and watermark
reads/writes are stubbed by a `_NullWatermarkStore`. Extracted items are
returned in the `/poll` response under `result.items`; downstream
consumers are responsible for any persistence (deduplication against
`news_urls`, watermark advancement, etc.).

## Architecture

```
┌────────┐   POST /submit   ┌──────────┐   fire-and-forget   ┌──────────┐
│ Client │ ───────────────▶ │  Submit  │ ──────────────────▶ │  Worker  │
└────────┘                  └────┬─────┘                     └────┬─────┘
     │                           │ INSERT row (queued)            │
     │                           ▼                                │
     │                  ┌──────────────────┐                      │
     │                  │  extraction_jobs │ ◀────────────────────┘
     │                  │   (shared table) │   UPDATE → terminal
     │                  └────────▲─────────┘     (worker invokes legacy
     │   POST /poll              │                NewsExtractionPipeline
     └───────────────────────────┘                which writes to news_urls)
```

The worker delegates the actual extraction to the legacy module's
`NewsExtractionPipeline`, which still owns:

- Loading `feeds.yaml`
- Per-source RSS / sitemap extraction (concurrent)
- Per-source dedup, validation, and date filtering
- Transforming items to the canonical record shape

The new service runs the pipeline in **stateless mode** (`dry_run=True`
+ null watermark store + no writer) and surfaces the extracted items in
the response. **It does not touch `news_urls` or `news_source_watermarks`.**

## Endpoints

- `POST /submit` → 202 with `{job_id, expires_at}`. Fires worker async.
- `POST /poll`  → returns status (queued/running) or atomically delete-and-return on terminal.
- `POST /worker` (internal, `X-Worker-Token` required when configured) → runs the pipeline.
- `GET /health` → `{status: "healthy"}`.

## Submit body

```jsonc
{
  "options": {
    "source_filter": "ESPN",                 // optional substring filter
    "since": "2026-04-22T10:00:00+00:00",    // optional ISO 8601 watermark
                                              // (must be tz-aware, in the past)
    "max_articles": 100,                     // optional cap (1..1000)
    "max_workers": 4                         // optional thread pool (1..20)
  },
  "supabase": {
    "url": "...",
    "key": "...",
    "jobs_table": "extraction_jobs"          // optional, defaults to extraction_jobs
  }
}
```

All `options.*` fields are optional. `since` is the canonical "give me
items published on or after this instant" knob — pass your downstream
system's last-seen watermark (e.g. the `MAX(publication_date)` you've
already persisted). The service post-filters on `publication_date >= since`
and drops items without a parseable date when `since` is set.

Omit `since` to get every item currently in the feed (no date filter).
`dry_run` and `clear` from the legacy module are not accepted — this
service never writes to `news_urls`.

## Poll terminal response

```jsonc
{
  "status": "succeeded",
  "job_id": "...",
  "result": {
    "sources_processed": 5,
    "items_extracted": 150,
    "items_filtered": 20,
    "items_count": 130,
    "items": [
      {
        "url": "https://example.com/article",
        "title": "...",
        "description": "...",
        "publication_date": "2026-04-22T10:30:00+00:00",
        "source_name": "ESPN - NFL News",
        "publisher": "ESPN"
      }
      // ...
    ],
    "metrics": { ... },
    "performance": { ... },
    "errors": []
  }
}
```

`result.items` is the canonical handoff. Downstream services dedupe
against `news_urls`, advance watermarks, and persist as needed.

## Schema

Jobs live in the shared `extraction_jobs` table tagged
`service = 'news_extraction'`. Schema:
`supabase/migrations/20260422120000_extraction_jobs_shared_table.sql`.
RPC: `consume_extraction_job(uuid)`.

## Local dev

```bash
cd src/functions/news_extraction_service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

./functions/run_local.sh

# In another shell:
python -m src.functions.news_extraction_service.scripts.submit_job_cli \
  --url http://localhost:8080/submit --source-filter ESPN \
  --since 2026-04-22T00:00:00+00:00
python -m src.functions.news_extraction_service.scripts.poll_job_cli \
  --url http://localhost:8080/poll --job-id <id> --wait
```

## Deploy

```bash
export WORKER_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
./functions/deploy.sh
```

Save the printed token into the `NEWS_EXTRACTION_WORKER_TOKEN` GitHub
secret (and the deployed worker URL into `NEWS_EXTRACTION_WORKER_URL`)
for the cleanup workflow.

## Cleanup

`.github/workflows/news-extraction-cleanup.yml` runs every 5 minutes:
deletes rows past `expires_at`, resets stale `running` rows back to
`queued`, and re-POSTs stale jobs to the worker.

## Migration phasing

- **Phase A** (this PR): new module ships next to the legacy
  `news_extraction`. Legacy CLI/HTTP untouched. Workflows still call
  `extract_news_cli.py` (which still writes to `news_urls`).
- **Phase B**: introduce a downstream consumer (a workflow step or a
  small CLI) that reads `result.items` from the new service and
  performs the persistence the legacy pipeline did internally —
  upsert into `news_urls` and advance `news_source_watermarks`.
- **Phase C**: switch `content-pipeline-create.yml` and
  `content-facts-entities-realtime.yml` to call the new service +
  downstream persistence step instead of `extract_news_cli.py`.
- **Phase D**: delete the legacy module + its GCP function.
