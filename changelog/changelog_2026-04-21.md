# Changelog — 2026-04-21

## Summary
Completed a code-excellence and performance review of the `news_extraction` module, landing correctness fixes across 14 files, 4 new files, and a new regression test suite. The changes eliminate a class of silent data-loss bugs (watermark skipping, warm-start URL deduplication leakage), fix several concurrency and thread-safety issues, and bring the module's Cloud Function handler from a 501 stub to production-ready.

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

## Code Quality Notes

- Tests: **7 passed, 0 failed** (`tests/news_extraction -v`)
- Full repo tests: pre-existing `tests/knowledge_extraction` failures present (verified not caused by today's changes — confirmed by running against the stashed working tree before changes)
- No linting step configured for Python modules (no flake8/ruff config found at project root)
- No new TODO/FIXME/HACK comments introduced; the one pre-existing TODO in `core/contracts/__init__.py` dates to the initial commit
- `print()` calls in `scripts/extract_news_cli.py` and `functions/local_server.py` are intentional user-facing CLI/startup output — not debug artifacts
- End-to-end dry-run: 4/4 sources SUCCESS, tz-aware watermark filtering working, shared `HttpClient` confirmed active, context manager closes cleanly

## Open Items / Carry-over

- `core/contracts/__init__.py` has a pre-existing TODO: "Add NewsExtractionRequest, NewsItem, ExtractionResult contracts" — not addressed in this session
- `AGENTS.md` Testing Guidelines section still says "No automated test suite exists yet" — now stale; updated in today's docs pass
- `tests/knowledge_extraction` failures are pre-existing and unrelated to this module; investigate in a future session
- `README.md` for `news_extraction` has a TODO section at the bottom (pre-existing) that could be cleaned up
- The `max_parallel_fetches` deprecation warning will surface on first run with the old config key; operators should migrate `feeds.yaml` to `max_workers`
