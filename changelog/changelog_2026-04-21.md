# Changelog — 2026-04-21

## Summary
Full-day code-excellence review arc: completed a deep correctness + performance pass on `news_extraction` (PRs #119, #120) and then carried the same discipline into a 5-phase refactor of `url_content_extraction` (PRs #121–#123). The combined effort eliminated silent data-loss bugs, fixed concurrency issues, unified a fragmented DB layer, added Playwright browser reuse, and deleted ~900 lines of dead/duplicate code — all with 34/34 tests green at day's end.

## Changes

### Correctness Fixes

- **`core/utils/client.py`**
  - Deleted duplicate `CircuitBreaker` class that was silently overriding the richer enum-based implementation
  - Converted `RateLimiter.acquire()` tail recursion to an iterative loop to avoid stack overflow under sustained rate limiting
  - Made `SimpleCache` thread-safe with a `threading.Lock`; added real hit/miss counters (previously hardcoded `"N/A"`)
  - Fixed `.seconds` → `.total_seconds()` bug in circuit-breaker timeout (`.seconds` truncates; sub-60-second timeouts were always zero)
  - Removed cache-clear on `close()` (broke cross-request cache reuse in warm Cloud Function instances)
  - Replaced `datetime.utcnow()` with `datetime.now(timezone.utc)` throughout

- **`core/pipelines/news_pipeline.py`**
  - Rewrote watermark advancement: previously could permanently skip a source's entire backlog if its items were deduped by another source; now only advances per-source if that source contributed a surviving record
  - Hoisted `HttpClient` to pipeline scope for connection pooling, real cache reuse, and correct shared-host rate limiting
  - Added `close()` + context-manager (`__enter__`/`__exit__`) support
  - ThreadPool now sized to `min(max_workers, len(sources))` to avoid idle threads

- **`core/processors/url_processor.py`**
  - `seen_urls` moved from instance state to local-per-call — instance state leaked across Cloud Function warm starts and silently dropped valid new URLs as "duplicates"

- **`core/config/loader.py`**
  - Split the misleading `max_parallel_fetches` into two distinct settings: `max_workers` (thread-pool concurrency) and `max_requests_per_minute_per_source` (HTTP rate cap)
  - Retained `max_parallel_fetches` as a deprecated alias with a deprecation warning and correct mapping to `max_workers`
  - Added env var overrides: `NEWS_MAX_WORKERS`, `NEWS_MAX_RPM_PER_SOURCE`, `NEWS_MAX_PARALLEL` (deprecated)

- **`core/db/watermarks.py`**
  - Paginated `fetch_watermarks()` via `.range()` — was unpaginated, violating the project's pagination rule for Supabase queries
  - Added optional `client` injection for request-scoped credentials
  - Replaced `datetime.utcnow()`

- **`core/db/writer.py`**
  - Replaced N batched `in_()` dedup queries with one upfront query (chunked at 200 URLs for PostgREST URL-length safety)
  - Added optional `client` injection for request-scoped credentials
  - Simplified per-batch retry logic

- **`core/extractors/rss.py` + `core/extractors/sitemap.py`**
  - Unified date handling via new `parse_feed_date()` helper: all feed dates now normalised to tz-aware UTC at parse time (previously RSS yielded naive datetimes, sitemap yielded tz-aware, and the pipeline stripped tzinfo — meaning watermark comparisons were unreliable)
  - Applied `MAX_ENTRIES_TO_PROCESS=1000` cap in RSS extractor (was declared but never used)

- **`core/data/transformers/news_transformer.py`**
  - Removed dead defensive `try/except` around a code path with no failure mode

- **`core/monitoring.py`**
  - Deleted dead `StructuredLogger` class (zero callers anywhere in the codebase)

- **`scripts/extract_news_cli.py`**
  - Replaced `logging.basicConfig` with shared `setup_logging()` for consistency with sibling modules
  - Stripped emoji from CLI output (for log-grep consistency)
  - Removed unused `print_progress_update` function
  - Pipeline now closed in `finally` block

### Architectural Fixes

- **`functions/main.py`**
  - Replaced 501 stub with a real HTTP handler
  - Accepts optional `supabase` credentials block (mirrors `image_selection` pattern documented in AGENTS.md)
  - Returns pipeline result JSON

- **NEW: `functions/local_server.py`**, **`functions/run_local.sh`**, **`functions/deploy.sh`**
  - Copied and adapted from `url_content_extraction/functions/`
  - `deploy.sh` uses `mktemp -d` + `trap` cleanup; passes `--clear-secrets`; credentials supplied per-request

### New Utilities

- **NEW: `core/utils/dates.py`**
  - `parse_feed_date()` — parses RSS/sitemap date strings to tz-aware UTC datetimes
  - `ensure_utc()` — promotes naive datetimes to UTC

### Tests

- **NEW: `tests/news_extraction/test_regressions.py`**
  - 5 regression tests:
    1. Watermark not advanced when source is fully deduped
    2. Watermark advances when source contributes records
    3. `UrlProcessor` does not leak state across pipeline calls
    4. `parse_feed_date()` normalises all inputs to UTC
    5. `SimpleCache` reports real hit/miss counters (not hardcoded "N/A")
  - All 5 pass; full `tests/news_extraction` suite: **7 passed**

### Documentation Updates

- **`CLAUDE.md`**
  - Added full inventory of all modules under `src/functions/`
  - Clarified stage-5 vs stage-6 embeddings (summary embeddings vs story embeddings)
  - Added `batch_jobs` table tracking + workflow trigger knobs to pipeline section
  - Added pointer to AGENTS.md → "Cloud Function Build Workflow (Image Selection Pattern)"

## Files Modified

### Session 1 — `news_extraction` (PRs #119, #120)

| File | Change |
|------|--------|
| `CLAUDE.md` | Added module inventory, clarified pipeline stages 5/6, documented batch_jobs table |
| `src/functions/news_extraction/core/config/loader.py` | Split `max_parallel_fetches` into `max_workers` + `max_requests_per_minute_per_source`; env var overrides |
| `src/functions/news_extraction/core/data/transformers/news_transformer.py` | Removed dead try/except |
| `src/functions/news_extraction/core/db/watermarks.py` | Paginated fetch; optional client injection; UTC fix |
| `src/functions/news_extraction/core/db/writer.py` | Upfront dedup query; optional client injection |
| `src/functions/news_extraction/core/extractors/rss.py` | Unified date handling via `parse_feed_date()`; apply MAX_ENTRIES cap |
| `src/functions/news_extraction/core/extractors/sitemap.py` | Unified date handling via `parse_feed_date()` |
| `src/functions/news_extraction/core/monitoring.py` | Deleted dead `StructuredLogger` class |
| `src/functions/news_extraction/core/pipelines/news_pipeline.py` | Watermark advancement fix; hoisted HttpClient; context-manager support |
| `src/functions/news_extraction/core/processors/url_processor.py` | `seen_urls` made call-local |
| `src/functions/news_extraction/core/utils/__init__.py` | Exported new `dates` module |
| `src/functions/news_extraction/core/utils/client.py` | Dedup CircuitBreaker; loop RateLimiter; thread-safe cache; UTC fix |
| `src/functions/news_extraction/functions/main.py` | Replaced 501 stub with real handler; request-scoped credentials |
| `src/functions/news_extraction/scripts/extract_news_cli.py` | Use `setup_logging`; strip emoji; remove dead function; close in finally |
| **NEW** `src/functions/news_extraction/core/utils/dates.py` | `parse_feed_date()` + `ensure_utc()` helpers |
| **NEW** `src/functions/news_extraction/functions/deploy.sh` | Deployment script (mktemp + trap pattern) |
| **NEW** `src/functions/news_extraction/functions/local_server.py` | Local dev server |
| **NEW** `src/functions/news_extraction/functions/run_local.sh` | Shell wrapper to start local server |
| **NEW** `tests/news_extraction/test_regressions.py` | 5 regression tests |

### Session 2 — `url_content_extraction` (PRs #121–#123)

| File | Change |
|------|--------|
| **NEW** `src/functions/url_content_extraction/core/db/__init__.py` | Package exports for reader + writer |
| **NEW** `src/functions/url_content_extraction/core/db/reader.py` | `FactsReader` with paginated Supabase reads |
| **NEW** `src/functions/url_content_extraction/core/db/writer.py` | `FactsWriter`: bulk insert, pooled embed, bucketed mark-complete, force-delete |
| `src/functions/url_content_extraction/core/facts/__init__.py` | Trimmed to prompt/parser/filter surface; storage API removed; docstring updated |
| **DELETED** `src/functions/url_content_extraction/core/facts/storage.py` | 345 lines removed; all callers migrated to `core/db` |
| `src/functions/url_content_extraction/core/pipelines/content_batch_processor.py` | Integrated `extract_many` pre-fetch loop; shared `is_heavy_url` reference |
| `src/functions/url_content_extraction/core/pipelines/realtime_post_processor.py` | Migrated from inline storage calls to `FactsWriter` |
| `src/functions/url_content_extraction/core/extractors/playwright_extractor.py` | Added `extract_many` for browser reuse; single-URL path routes through `_extract_one` |
| `src/functions/url_content_extraction/core/extractors/light_extractor.py` | Shared module-level `httpx.Client`; `is_heavy_url` extracted to module scope |
| `src/functions/url_content_extraction/scripts/extract_facts_cli.py` | Migrated to `FactsReader`/`FactsWriter`; request-scoped `OpenAI` client; eliminated redundant DB round-trips |
| **NEW** `tests/url_content_extraction/test_regressions.py` | 25 regression tests covering DB layer, extractors, CLI, and deletion invariants |

---

## Session 2 — `url_content_extraction` refactor arc (PRs #121–#123)

### Phase 3 — Unified DB layer (PR #121)

- **NEW `core/db/reader.py`** — `FactsReader`: paginated reads for `news_facts`, `facts_embeddings`, `story_embeddings`; every multi-row path uses `.range()` pagination per project convention
- **NEW `core/db/writer.py`** — `FactsWriter`: bulk inserts, pooled embedding upsert, bucketed `mark_completed` (small/medium/large article buckets), force-delete for re-extraction
- **NEW `core/db/`** replaces three parallel fact-storage implementations that had independently drifted: realtime post-processor, batch result processor, and the older `core/facts/storage` module; all now route through one layer
- `insert_facts` returns `(ids_by_article, texts_by_id)` so downstream embedding creation skips a redundant `SELECT`
- `mark_facts_extracted` buckets updates by article size (avoids single-row updates for large articles)
- Writer supports optional `client` injection for request-scoped credentials (mirrors `image_selection` pattern)
- Net: +966 / -620 across 6 files; 28/28 tests passing at merge

### Phase 4 — Playwright browser reuse + shared httpx client (PR #122)

- **`PlaywrightExtractor.extract_many(urls)`** — new batch-extraction method that launches Chromium once, walks the URL list on a shared browser + context, and closes one page per URL; single-URL `extract()` preserved and routed through the same `_extract_one` helper
- **`content_batch_processor`** pre-extracts the entire heavy-URL batch via `extract_many` before the processing loop; net effect: one Chromium launch per run instead of one per heavy URL (~2–3 s saved per heavy URL)
- Per-URL errors in a batch surface as `ExtractedContent(error=...)` and fall through to standard failure tracking; a complete batch failure is caught and re-raised
- **`LightExtractor`** now uses a module-level shared `httpx.Client` (persistent connection pool) instead of constructing one per URL; `is_heavy_url()` extracted to module scope so both extractors and the batch processor share the same decision function
- `content_batch_processor` passes `is_heavy_url` as a parameter rather than re-declaring it
- Net: +511 / -256 across 4 files; 31/31 tests passing at merge

### Phase 5 — CLI migration + storage.py deletion (PR #123)

- **`scripts/extract_facts_cli.py`** migrated to `FactsReader`/`FactsWriter`; the 50-line force-delete block collapses to `writer.delete_fact_data`; `create_fact_embeddings_sync` now accepts a pre-built `texts_by_id` from the insert step, eliminating a redundant DB round-trip; `create_pooled_embedding` accepts `known_vectors` for the same reason
- `extract_facts_from_content` uses a request-scoped `OpenAI(api_key=...)` client instead of mutating the module-global `openai.api_key` (fixes a thread-safety hazard in warm Cloud Function instances)
- **`core/facts/storage.py` deleted** (345 lines); `core/facts/__init__.py` trimmed to the prompt/parser/filter surface; docstring directs new callers to `core/db`
- 3 new regression tests: `core/facts` no longer exports storage API; `storage.py` module is fully deleted; CLI imports `FactsWriter` not the old storage functions
- Net: +174 / -529 across 4 files (net −355 lines); 34/34 tests passing at merge

---

## Code Quality Notes

- Tests: **34 passed, 0 failed** (`tests/url_content_extraction tests/news_extraction -v`); confirmed clean at EOD
- Full repo tests: pre-existing `tests/knowledge_extraction` failures present (verified not caused by today's changes — confirmed by running against the stashed working tree before changes)
- No linting step configured for Python modules (no flake8/ruff config found at project root)
- No new TODO/FIXME/HACK comments introduced; the one pre-existing TODO in `core/contracts/__init__.py` dates to the initial commit
- `print()` calls in `scripts/extract_news_cli.py` and `functions/local_server.py` are intentional user-facing CLI/startup output — not debug artifacts
- End-to-end dry-run: 4/4 sources SUCCESS, tz-aware watermark filtering working, shared `HttpClient` confirmed active, context manager closes cleanly

## Open Items / Carry-over

- **PR merge order**: PRs #119–#123 are a stacked series; merge in order (#119 first, #123 last) or retarget each to `main` after the predecessor merges. No conflicts expected.
- **PR #115** (`fix/pipeline-knowledge-backlog`) has been open since 2026-03-05 — pre-dates today's arc; needs separate review.
- **`news_extraction/core/contracts/__init__.py`**: pre-existing TODO "Add NewsExtractionRequest, NewsItem, ExtractionResult contracts" — not addressed in this session.
- **`tests/knowledge_extraction`** failures are pre-existing and unrelated to today's changes; investigate in a future session.
- **`news_extraction/README.md`** has a TODO section at the bottom (pre-existing); could be cleaned up.
- **`feeds.yaml` `max_parallel_fetches`** key: operators should migrate to `max_workers` — a deprecation warning is emitted at runtime until it is updated.
- **`url_content_extraction` README**: may need an update to document the new `core/db/` layer and `extract_many` API; not addressed today.
