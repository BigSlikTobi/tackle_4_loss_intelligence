# article_knowledge_extraction

Stateless on-demand service that extracts **topics** and **resolved NFL entities** from a full article.

Complements the fact-level `knowledge_extraction` module, which remains unchanged and continues to serve the batch content pipeline. This module is aimed at a new agentic consumer that operates at the article level and drives article grouping by topic/entity. The function itself never writes to domain tables — callers own persistence.

## Architecture at a glance

```
caller (agent) ──POST /submit──▶ [write queued row] ──fire-and-forget──▶ /worker
                                                                          │
                                                                          ▼
                                                             [run pipeline, write result]
                   ◀──POST /poll── [peek or consume-on-read] ◀──────────────┘
```

- **Submit** returns `202 {job_id}` immediately after queuing the job.
- **Worker** (internal, token-protected) executes extraction + entity resolution.
- **Poll** returns non-terminal statuses without deletion, and *atomically deletes* terminal results on first read. A 24h hard TTL expires abandoned rows.
- **Reliability backstop**: a cleanup cron (`scripts/cleanup_expired_jobs_cli.py --requeue-stale`, wired up via `.github/workflows/article-knowledge-cleanup.yml`) re-POSTs stale queued/running jobs to the worker so dropped self-invokes don't leave work orphaned.
- **Model**: small cheap real-time OpenAI model (default `gpt-5.4-mini`). No Batch API.

## Key decisions

- Stateless: callers decide whether to persist the result. The function deletes on read + TTL.
- Async only — no synchronous response mode.
- Backwards compatible with the fact-level `knowledge_extraction` pipeline (untouched).
- Fuzzy entity matching reuses `src/shared/nlp/entity_resolver.py` (moved out of `knowledge_extraction` in this change).

## HTTP API

### POST /submit → 202

```json
{
  "article": {"article_id": "optional", "text": "...", "title": "optional", "url": "optional"},
  "options": {"max_topics": 5, "max_entities": 15, "resolve_entities": true, "confidence_threshold": 0.6},
  "llm":      {"provider": "openai", "model": "gpt-5.4-mini", "api_key": "..."},
  "supabase": {"url": "https://...", "key": "..."}
}
```

Response: `{"status": "queued", "job_id": "<uuid>", "expires_at": "..."}`

### POST /poll

```json
{"job_id": "<uuid>", "supabase": {"url": "...", "key": "..."}}
```

Responses:
- `queued` / `running` → 200 with `{status, job_id}`, row retained.
- `succeeded` / `failed` → 200 with `{status, job_id, result|error}`, row **atomically deleted**.
- missing / expired → 404.

### POST /worker (internal)

Protected by shared header `X-Worker-Token` matching `WORKER_TOKEN` env var. Idempotent: no-op if the job is already terminal.

## Result shape

```json
{
  "article_id": "...",
  "topics":   [{"topic": "...", "confidence": 0.95, "rank": 1}],
  "entities": [{"entity_type": "player", "entity_id": "00-0034796", "mention_text": "Josh Allen", "matched_name": "Josh Allen", "confidence": 0.98, "rank": 1, "position": "QB", "team_abbr": "BUF"}],
  "unresolved_entities": [ ... ],
  "metrics": {"topic_extraction_ms": 1234, "entity_extraction_ms": 2345, "resolution_ms": 678, "total_ms": 4567, "model": "gpt-5.4-mini"}
}
```

Topic vocabulary is kept identical to the fact-level path so downstream grouping sees a uniform namespace — enforced by `tests/article_knowledge_extraction/test_prompts.py`.

## Local development

```bash
cd src/functions/article_knowledge_extraction
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Apply schema.sql to your Supabase instance (see below).

# Local end-to-end without the job store (prompt tuning, smoke test)
python scripts/extract_article_knowledge_cli.py --input sample.txt

# Run the HTTP stack locally (bundles /submit /poll /worker on one port)
cd functions && ./run_local.sh

# In another terminal
python scripts/submit_job_cli.py --url http://localhost:8080 --text "Josh Allen..."
python scripts/poll_job_cli.py --url http://localhost:8080 --job-id <id> --wait
```

## Schema

Jobs are stored in the **shared** `extraction_jobs` table — one row per job
across every extraction service in the platform. Rows from this service are
tagged `service = 'article_knowledge_extraction'`. The atomic delete-on-read
RPC is the generic `consume_extraction_job(p_job_id uuid)`.

Apply the migration at
`supabase/migrations/20260422120000_extraction_jobs_shared_table.sql`
via the repo's standard Supabase migration path.

## Deployment

```bash
# Set a stable token (or let the script generate one and print it for you)
export WORKER_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

cd functions && ./deploy.sh
```

The script deploys three Gen2 Cloud Functions (worker, poll, submit) from a single source zip, wires `WORKER_URL` + `WORKER_TOKEN` into submit, and only sets generic env vars — credentials stay per-request.

Configure the GitHub Actions secret `ARTICLE_KNOWLEDGE_WORKER_URL` and `ARTICLE_KNOWLEDGE_WORKER_TOKEN` (plus `SUPABASE_URL` / `SUPABASE_KEY`) to enable the cleanup cron.

## Scaling path

The async mechanism is HTTP self-invoke plus a 5-minute requeue cron — zero new GCP primitives. If volume grows to the point where dropped self-invokes become load-bearing, migrate the submit-to-worker edge to Cloud Tasks with idempotent delivery. The rest of the service (handlers, pipeline, job store) is unchanged by that move.

## Non-goals

- Sourcing or storing articles upstream.
- Persisting extraction results into domain tables.
- Any modification to the fact-level `knowledge_extraction` module.
- The downstream grouping workflow itself.
