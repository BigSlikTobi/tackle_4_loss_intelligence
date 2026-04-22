# url_content_extraction_service

Async URL content extraction service using the **submit / poll / worker**
pattern from `article_knowledge_extraction`. Callers POST one or more URLs;
the service runs Playwright/light extraction in the background; callers poll
to retrieve the extracted content. The job row is deleted on the first
terminal poll.

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
     │                  └────────▲─────────┘
     │   POST /poll              │
     └───────────────────────────┘
```

Endpoints (deployed as separate Cloud Functions, share the same source zip):

- `POST /submit` → 202 with `{job_id, expires_at}`. Fires the worker async.
- `POST /poll`  → returns status (queued/running) or atomically delete-and-return on terminal.
- `POST /worker` (internal, `X-Worker-Token` required when configured) → runs the extraction pipeline.
- `GET /health` → `{status: "healthy"}`.

## Schema

Jobs live in the shared `extraction_jobs` table tagged
`service = 'url_content_extraction'`. Schema lives at
`supabase/migrations/20260422120000_extraction_jobs_shared_table.sql`. The
atomic delete-on-read RPC is `consume_extraction_job(uuid)`.

## Local development

```bash
cd src/functions/url_content_extraction_service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Run all four routes locally on port 8080.
./functions/run_local.sh

# In another shell:
python -m src.functions.url_content_extraction_service.scripts.submit_job_cli \
  --url http://localhost:8080/submit \
  --target-url https://example.com/article
python -m src.functions.url_content_extraction_service.scripts.poll_job_cli \
  --url http://localhost:8080/poll --job-id <id> --wait
```

## Deployment

```bash
export WORKER_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
./functions/deploy.sh
```

The script deploys three entry points (`url-content-submit`,
`url-content-poll`, `url-content-worker`) and wires `WORKER_URL`/`WORKER_TOKEN`
across them.

## Cleanup

The cleanup workflow at `.github/workflows/url-content-extraction-cleanup.yml`
runs every 5 minutes and:
- deletes rows past `expires_at`,
- re-POSTs stale queued/running jobs to the worker (handles dropped self-invokes).
