# Content Summarization – Fact-First Pipeline

## Overview
The content_summarization module now runs a multi-step, fact-first workflow for NFL news URLs. Each batch pulls pending IDs from the Supabase Edge Function `get-pending-news-urls`, retrieves article text from the Cloud Run content extractor, and uses Gemma 3n to derive atomic one-sentence facts. Facts are inserted into `news_facts`, embedded individually with `text-embedding-3-small`, averaged into a URL-level vector, and then fed back into Gemma 3n to create concise factual summaries. No raw article text or hashes are persisted; only structured outputs derived from the facts are stored.

The workflow is modular so that facts, embeddings, and summaries can be recomputed independently. All configuration is sourced from the project-wide `.env` via `src.shared.utils.env.load_env`, and Supabase access is handled by `src.shared.db.get_supabase_client`.

## Database Tables
- `news_facts`: Atomic statements produced by the fact extractor (one factual clause per row). Each record captures the LLM model and prompt version used.
- `facts_embeddings`: Vector embeddings for every fact using `text-embedding-3-small`; downstream services can query them directly.
- `context_summaries`: Stores the Gemma 3n factual summary text generated strictly from the stored facts.
- `story_embeddings`: Holds derived embeddings. Records with `embedding_type = 'fact_pooled'` contain the mean vector across the fact embeddings for a URL, while `embedding_type = 'summary'` contains the embedding of the final summary text.

## Running the Pipeline Locally
```bash
cd src/functions/content_summarization
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run fact extraction + embeddings
python scripts/content_pipeline_cli.py --stage facts --limit 20

# Generate summaries and summary embeddings
python scripts/content_pipeline_cli.py --stage summary --limit 20

# Execute both stages sequentially
python scripts/content_pipeline_cli.py --stage full --limit 20
```

## Required Environment Variables
All configuration lives in the root `.env` file and is loaded via `load_env()` before execution. The module uses standard environment variables shared across the platform.

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_KEY` | Supabase connection (service role key recommended). Edge function URL is automatically derived from SUPABASE_URL. |
| `GEMINI_API_KEY` | Gemini API key for LLM calls (fact extraction, summarization) and embeddings (`text-embedding-3-small`). |
| `CONTENT_EXTRACTION_URL` | Optional: Cloud Run HTTP endpoint that returns raw article text for a URL. If not configured, content extraction stage will be skipped. |
| `BATCH_LIMIT` | Optional default batch size pulled from the Edge Function. |
| `LLM_TIMEOUT_SECONDS`, `EMBEDDING_TIMEOUT_SECONDS`, `CONTENT_TIMEOUT_SECONDS` | Optional request timeouts for each service. |
| `FACT_LLM_MODEL` | Optional: Override the default model for fact extraction (default: `gemma-3n`). |
| `SUMMARY_LLM_MODEL` | Optional: Override the default model for summary generation (default: `gemma-3n`). |
| `OPENAI_EMBEDDING_MODEL` | Optional: Override the default embedding model (default: `text-embedding-3-small`). |

## Operational Quick Reference

- **Reset pipeline state** (use when reprocessing an entire dataset):

	```sql
	TRUNCATE facts_embeddings CASCADE;
	TRUNCATE news_facts CASCADE;
	TRUNCATE story_embeddings CASCADE;
	TRUNCATE context_summaries CASCADE;
	UPDATE news_urls
		 SET facts_extracted_at = NULL,
				 summary_created_at = NULL
	 WHERE facts_extracted_at IS NOT NULL
			OR summary_created_at IS NOT NULL;
	```

- **High-volume batch run (5000 most recent URLs):**

	```bash
	python scripts/content_pipeline_cli.py \
		--stage full \
		--limit 100 \
		--batch-mode \
		--max-total 5000 \
		--batch-delay 5
	```

- **Facts-only or summary-only runs:** supply `--stage facts` or `--stage summary` with the same batching flags.
- **Monitoring snippets:**
	- Progress snapshot: `SELECT COUNT(*) FILTER (WHERE facts_extracted_at IS NULL) AS pending, COUNT(*) FILTER (WHERE summary_created_at IS NOT NULL) AS completed FROM news_urls;`
	- Hourly throughput: `SELECT COUNT(*) FILTER (WHERE facts_extracted_at > NOW() - INTERVAL '1 hour') AS processed_last_hour FROM news_urls;`
	- Latest processed URLs: `SELECT url, title, facts_extracted_at FROM news_urls WHERE facts_extracted_at IS NOT NULL ORDER BY facts_extracted_at DESC LIMIT 10;`
- **CLI flag refresher:** `--limit` controls batch size, `--batch-mode` keeps looping, `--max-total` stops after N URLs, and `--batch-delay` (seconds) protects API quotas.
- **Cost guidance:** ~5000 URLs costs ≈$0.50 in Gemini usage plus ≈$10 in OpenAI embeddings assuming ~100 facts per article.
- **Pro tips:** start with `--limit 10` when validating new configs, keep logs via `... | tee pipeline.log`, and run during off-peak hours to maximize API quotas.

## Backlog Processor Facts Model Override

Bulk backlog runs use `scripts/backlog_processor.py`, which now accepts `--facts-llm-model` to override the fact extraction model without touching other stages. By default the script uses `FACT_LLM_MODEL` (or `gemma-3n-e4b-it`).

```bash
python scripts/backlog_processor.py --stage facts --facts-llm-model gemini-2.5-flash-lite --limit 200
```

Only backlog runs launched with this flag switch to Gemini 2.5 Flash Lite; all other tools and stages continue using their configured defaults.

## Pending URL Cache for Bulk Runs

Large backlog runs previously stalled because the Supabase edge function kept returning the same failing IDs (the first `limit` rows) every time a batch finished. The backlog processor now caches pending IDs locally so each article is only enqueued once per run. The script fetches a large window of pending rows up front and serves every batch from the cached queue, which means failed IDs no longer block the queue and you can run 10k+ articles in one pass.

- Use `--prefetch-size` to control how many pending URLs are fetched per refill (default auto-scales to `max(--limit, batch_size * 5)`).
- Cached IDs are deduplicated and respect the retry/skip tracker, so once an article hits the local failure limit it will not be requeued again.
- When you need to run a very large backlog, pass a bigger prefetch size so the cache captures the entire set:

```bash
# Cache 13k pending facts in memory and process them without re-querying Supabase
python scripts/backlog_processor.py --stage facts --limit 13000 --prefetch-size 13000
```

If `--prefetch-size` is omitted the script automatically uses `max(--limit, batch_size * 5)`, which is enough to keep the pipeline fed for most daily runs.

### Watchdog timeout tuning

Every worker emits heartbeat pings while it runs. If a task goes longer than `--ping-timeout` seconds without a heartbeat the watchdog cancels it so the backlog keeps moving. The default is now 90 s, which works better for heavy facts runs. Increase the flag further (e.g., `--ping-timeout 180`) if you have especially slow content extraction or LLM calls; decrease it if you prefer more aggressive cancellation.

## Backlog Processor Overview

Use `scripts/backlog_processor.py` when you need to chew through 1K+ pending articles with full concurrency, adaptive memory limits, and checkpoint/resume support.

- **Key features:** ThreadPoolExecutor (default 15 workers), adaptive `MemoryMonitor` that scales workers between 5–20 based on RAM, token-bucket rate limiting (30 req/min Gemini default) with exponential backoff, Playwright browser pool (max 5, auto-cleaned), 100-item embedding batches, and per-stage checkpoints stored in `.backlog_checkpoint.json`.
- **Common flags:**
	- `--stage {content,facts,knowledge,summary,full}` – process only one portion of the pipeline.
	- `--workers`, `--batch-size`, `--max-memory-percent`, `--max-browsers` – performance tuning knobs.
	- `--resume`, `--retry-failures`, `--archive`, `--checkpoint-file`, `--facts-llm-model`, `--prefetch-size`, `--ping-timeout` – control restarts and overrides.
- **Performance expectations:** 500–800 articles/hour on an M3 Air once the cache is warmed versus ~60/hour sequential. Progress logs emit every 10 articles with rate, memory, worker count, and ETA.
- **Workflow tips:**
	1. `python scripts/backlog_processor.py --stage facts --workers 15 --batch-size 100` to kick things off.
	2. Use `--resume` after interruptions; checkpoints record per-article stage completion.
	3. `--retry-failures` processes only the items captured in `.backlog_failures.json`.
	4. `--archive` snapshots checkpoint/failure files with timestamps so you can refer back later.
- **Monitoring:** the processor logs rate limit hits, memory events, browser utilization, and stage transitions. Keep `tail -f backlog.log` running or redirect stdout with `... | tee backlog.log` during long runs.
- **Monitoring:** the processor logs rate limit hits, memory events, browser utilization, and stage transitions. Keep `tail -f backlog.log` running or redirect stdout with `... | tee backlog.log` during long runs.

## Knowledge & Summary Stage Validation

- **Knowledge stage** (`process_article_knowledge_stage`) now wires the backlog processor directly into the knowledge_extraction module: `EntityExtractor`, `TopicExtractor`, and `EntityResolver` run for each fact set, results are written to `news_fact_topics` / `news_fact_entities`, and `news_urls.knowledge_extracted_at` is stamped on success. The stage automatically skips work when a URL lacks facts.
- **Summary stage** routes difficult articles to `handle_hard_article_summary` (topic-scoped outputs) and everything else to `handle_easy_article_summary`, then validates completion via `summary_stage_completed()` before marking `summary_created_at`.
- **Testing:**
	```bash
	python scripts/backlog_processor.py --stage facts --limit 5
	python scripts/backlog_processor.py --stage knowledge --limit 5
	python scripts/backlog_processor.py --stage summary --limit 5
	```
	or run `python scripts/test_stages.py` to assert that both stages depend on the proper helpers.
- **Database checks:**
	- Verify topics/entities via joins on `news_facts` → `news_fact_topics/news_fact_entities` for a sample `news_url_id`.
	- Confirm summary rows in `context_summaries` or `topic_summaries` plus the associated `story_embeddings`.
- **Edge function filters:** knowledge stage processes URLs with `facts_extracted_at IS NOT NULL AND knowledge_extracted_at IS NULL`; summary stage requires `knowledge_extracted_at IS NOT NULL AND summary_created_at IS NULL`.

## Production Hardening Features

- **HTTP efficiency:** `ContentFetcher` reuses `requests` sessions with configurable connection pools (`pool_connections`, `pool_maxsize`) and urllib3 retry adapters (`status_forcelist=[429,500,502,503,504]`).
- **Rate limiting:** `RateLimiter` implements a token-bucket to cap Gemini/OpenAI calls (default 60 req/min) and blocks until tokens replenish, avoiding throttling.
- **Resilience patterns:**
	- Circuit breaker skips domains after N consecutive failures for `circuit_breaker_timeout` seconds.
	- Exponential backoff around Gemini calls, Supabase writes, and HTTP fetches (2s → 4s → 8s) smooths transient outages.
- **Observability:** `GeminiClient.get_metrics()` surfaces success rate, average tokens, processing time, fallback counts, and total usage. Extensive INFO/DEBUG logs track batch progress, retries, and cost signals. Reset metrics between batches when gathering clean numbers.
- **Resource hygiene:** both `GeminiClient` and `ContentFetcher` expose context managers so connection pools close cleanly; Supabase writers run a health check on init to fail fast if credentials are wrong.
- **Scalability hooks:** batch writes (default 100 rows), Supabase pagination in every reader, and defensive JSON-safe writers (for downstream NaN cleanup) allow arbitrarily large datasets without exhausting memory.

## Architecture Notes
- All orchestration code for the new pipeline lives under `core/` and `scripts/` within this module; no cross-module imports are used.
- Shared behaviour (logging, env loading, Supabase connection) comes exclusively from `src/shared` utilities, keeping the module replaceable.
- The script paginates Supabase reads to avoid hitting default row limits, and timestamps (`content_extracted_at`, `facts_extracted_at`, `summary_created_at`) are set only after their respective stages succeed.
