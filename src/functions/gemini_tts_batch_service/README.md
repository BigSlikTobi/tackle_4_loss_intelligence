# gemini_tts_batch_service

Async Gemini TTS batch service using the **submit / poll / worker** pattern
from `article_knowledge_extraction` and `url_content_extraction_service`.

This module is **self-contained**: the TTS batch implementation lives in
`core/tts/` and is owned by this module. It does not import from the
legacy `gemini_tts_batch` package — that constraint is what keeps the
function-isolation rule intact (each function module must be independently
deployable and deletable).

Three job types correspond one-to-one to the legacy actions:

- `action=create`  → submits a Gemini batch (returns `batch_id` + initial state).
- `action=status`  → reads the current Gemini batch state.
- `action=process` → downloads the completed batch output and uploads MP3s
                     to a Supabase Storage bucket the **caller** chooses.

The downstream caller orchestrates the lifecycle: submit a `create` job →
poll until terminal → submit a `status` job (repeating until the Gemini
batch state is `JOB_STATE_SUCCEEDED`) → submit a `process` job with the
target storage `bucket` and `path_prefix`.

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

- `POST /submit` → 202 with `{job_id, action, expires_at}`. Fires the worker async.
- `POST /poll`  → returns status (queued/running) or atomically delete-and-return on terminal.
- `POST /worker` (internal, `X-Worker-Token` required when configured) → runs the legacy `TTSBatchService`.
- `GET /health` → `{status: "healthy"}`.

## Request payloads

`/submit` is action-discriminated. Every payload also requires
`supabase.url` (the jobs DB) and Authorization bearer auth.

### action=create

```json
{
  "action": "create",
  "model_name": "gemini-2.5-pro-preview-tts",
  "voice_name": "Charon",
  "items": [
    {"id": "story-1", "text": "...", "title": "..."}
  ],
  "supabase": {"url": "https://JOBS-PROJECT.supabase.co"}
}
```

### action=status

```json
{
  "action": "status",
  "batch_id": "batches/abc123",
  "supabase": {"url": "https://JOBS-PROJECT.supabase.co"}
}
```

### action=process

The caller picks the destination bucket and path prefix. The storage
project's URL+key are read from the worker's env (`STORAGE_SUPABASE_URL` /
`STORAGE_SUPABASE_KEY`, falling back to `SUPABASE_URL` /
`SUPABASE_SERVICE_ROLE_KEY`) so secrets never travel in payloads.

```json
{
  "action": "process",
  "batch_id": "batches/abc123",
  "storage": {"bucket": "audio", "path_prefix": "gemini-tts-batch"},
  "supabase": {"url": "https://JOBS-PROJECT.supabase.co"}
}
```

The terminal `/poll` response carries the legacy module's full result dict
under `result`, with an `action` field added so callers can route on a
single key (e.g. `result.action == "process"` carries `items`, `failures`,
`token_usage`, `manifest_public_url`, etc.).

## Schema

Jobs live in the shared `extraction_jobs` table tagged
`service = 'gemini_tts_batch'`. Schema lives at
`supabase/migrations/20260422120000_extraction_jobs_shared_table.sql`. The
atomic delete-on-read RPC is `consume_extraction_job(uuid)`.

## Local development

```bash
cd src/functions/gemini_tts_batch_service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run all four routes locally on port 8080.
./functions/run_local.sh

# In another shell:
python -m src.functions.gemini_tts_batch_service.scripts.submit_job_cli \
  --url http://localhost:8080/submit \
  --action create --payload-file request.json
python -m src.functions.gemini_tts_batch_service.scripts.poll_job_cli \
  --url http://localhost:8080/poll --job-id <id> --wait
```

## Deployment

```bash
export WORKER_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
export TTS_BATCH_FUNCTION_AUTH_TOKEN=...
export GEMINI_API_KEY=...
export SUPABASE_SERVICE_ROLE_KEY=...
./functions/deploy.sh
```

The script deploys three entry points (`tts-batch-submit`, `tts-batch-poll`,
`tts-batch-worker`) and wires `WORKER_URL`/`WORKER_TOKEN` across them.

## Cleanup

The cleanup workflow at `.github/workflows/gemini-tts-batch-cleanup.yml`
runs every 5 minutes and:
- deletes rows past `expires_at`,
- re-POSTs stale queued/running jobs to the worker (handles dropped self-invokes).

## Migration phasing

Phase A (this PR): the new service ships and deploys alongside the legacy
`gemini_tts_batch` Cloud Function. The TTS implementation in `core/tts/`
is a deliberate copy of the legacy module's `core/` so the new service is
independently deployable; the legacy module is **not** modified or imported.

Phase B: switch downstream callers (workflows, other modules) over to the
async submit/poll surface one at a time.

Phase C: once nothing references the legacy module, delete its directory
in one shot — `core/tts/` here is the authoritative implementation.
