# Changelog — 2026-04-22

## Summary
Three connected efforts landed today: surgically rolled back the Phase 6a ephemeral content-handoff layer that had merged in PR #125; promoted `url_content_extraction`'s extractors, processors, and utility helpers to `src/shared/` alongside a new generic async-job primitives package; and stood up a brand-new `url_content_extraction_service` module that delivers on-demand URL extraction via the shared submit/poll/worker pattern. Deployment verified end-to-end.

## Changes

### Phase 6a Rollback (`url_content_extraction`)
- Deleted `core/db/ephemeral.py`, `scripts/ephemeral_sweep_cli.py`, `schema.sql`, `tests/url_content_extraction/test_ephemeral.py`
- Restored `core/db/__init__.py`, `core/facts_batch/extracted_content.py`, `core/facts_batch/content_batch_processor.py`, `core/facts_batch/request_generator.py`, `core/facts_batch/result_processor.py`, `functions/main.py`, `functions/local_server.py`, `README.md`, `.env.example` to pre-6a state
- Restored three workflow YAMLs (`content-facts-entities-realtime.yml`, `content-pipeline-create.yml`, `content-pipeline-poll.yml`) to pre-6a state — ephemeral sweep step removed
- Surgically preserved an unrelated rsync edit in `url_content_extraction/functions/deploy.sh`

### Shared Extractors + Processors (`src/shared/`)
- Moved `core/extractors/` from `url_content_extraction` → `src/shared/extractors/`
  - `ExtractorFactory`, `PlaywrightExtractor`, `LightExtractor`
- Moved `core/processors/` from `url_content_extraction` → `src/shared/processors/`
  - `ContentCleaner`, `MetadataExtractor`, `TextDeduplicator`
- Moved `core/utils/amp_detector.py` and `core/utils/consent_handler.py` → `src/shared/utils/`
- Moved `core/contracts/extracted_content.py` → `src/shared/contracts/extracted_content.py`
- Added compat re-export shims at all original `url_content_extraction` paths so existing imports continue to work
- Updated `content_summarization/scripts/backlog_processor.py` and all affected tests to use new shared paths

### Shared Jobs Primitives (`src/shared/jobs/`)
- Created `src/shared/jobs/contracts.py`: `JobStatus` enum, `JobError` dataclass, `SupabaseConfig` dataclass
- Created `src/shared/jobs/store.py`: `JobStore` class — atomic `create`, `mark_running`, `mark_succeeded`, `mark_failed`, `consume` (delete-on-read via RPC), `delete_expired`
- Extracted from `article_knowledge_extraction/core/db/job_store.py`, which now delegates to the shared `JobStore` with `service='article_knowledge_extraction'` injected at construction

### Shared `extraction_jobs` Table + Migration
- Added `supabase/migrations/20260422120000_extraction_jobs_shared_table.sql`:
  - Renames `article_knowledge_extraction_jobs` → `extraction_jobs`
  - Adds `service TEXT NOT NULL` discriminator column
  - Renames RPC to `consume_extraction_job(uuid)`
  - Updates RLS policies and indexes to cover the new column
- Updated `article_knowledge_extraction` job_store to filter all queries by `service='article_knowledge_extraction'`
- Updated `article_knowledge_extraction/schema.sql` with a pointer comment to the shared migration
- Updated `article_knowledge_extraction/scripts/cleanup_expired_jobs_cli.py` to accept `--service` flag
- Updated `article_knowledge_extraction/README.md`, tests, and `.github/workflows/article-knowledge-cleanup.yml` accordingly

### New Module: `url_content_extraction_service`
- `core/config.py` — `ServiceConfig`, `SubmitRequest`, `PollRequest`, `WorkerRequest` dataclasses with full validation
- `core/factory.py` — parses HTTP payloads into config structs; reuses `src/shared/jobs/` and `src/shared/extractors/`
- `core/contracts/result.py` — `ExtractionResult` dataclass
- `core/worker/job_runner.py` — `JobRunner`: loads job, runs `ExtractorFactory`, writes `ExtractionResult` to `extraction_jobs`
- `functions/main.py` — Flask HTTP handler with `/submit`, `/poll`, `/worker` routes
- `functions/local_server.py` — local dev server
- `functions/deploy.sh` — Cloud Function deployment (mktemp pattern, no secrets in env)
- `functions/run_local.sh`
- `scripts/submit_job_cli.py`, `scripts/poll_job_cli.py`, `scripts/cleanup_expired_jobs_cli.py`
- `requirements.txt`, `.env.example`, `schema.sql` (pointer to shared migration), `README.md`
- `.github/workflows/url-content-extraction-cleanup.yml` — daily cron to sweep expired jobs
- 18 new tests across `tests/url_content_extraction_service/`: `test_factory.py` (9), `test_worker.py` (7), `test_auth.py` (2)

## Files Modified

### Deleted
- `src/functions/url_content_extraction/core/db/ephemeral.py`
- `src/functions/url_content_extraction/scripts/ephemeral_sweep_cli.py`
- `src/functions/url_content_extraction/schema.sql`
- `tests/url_content_extraction/test_ephemeral.py`

### Renamed / Moved (with compat shims left at original paths)
- `url_content_extraction/core/extractors/` → `src/shared/extractors/`
- `url_content_extraction/core/processors/` → `src/shared/processors/`
- `url_content_extraction/core/utils/amp_detector.py` → `src/shared/utils/amp_detector.py`
- `url_content_extraction/core/utils/consent_handler.py` → `src/shared/utils/consent_handler.py`
- `url_content_extraction/core/contracts/extracted_content.py` → `src/shared/contracts/extracted_content.py`

### Modified
- `.env.example` — added `url_content_extraction_service` vars
- `.github/workflows/content-facts-entities-realtime.yml` — reverted ephemeral sweep step
- `.github/workflows/content-pipeline-create.yml` — reverted ephemeral sweep step
- `.github/workflows/content-pipeline-poll.yml` — reverted ephemeral sweep step
- `.github/workflows/article-knowledge-cleanup.yml` — updated for shared table name
- `src/functions/article_knowledge_extraction/core/config.py` — re-exports from `src/shared/jobs/`
- `src/functions/article_knowledge_extraction/core/db/job_store.py` — now wraps shared `JobStore` with service filter
- `src/functions/article_knowledge_extraction/schema.sql` — pointer comment to shared migration
- `src/functions/article_knowledge_extraction/scripts/cleanup_expired_jobs_cli.py` — `--service` flag
- `src/functions/article_knowledge_extraction/README.md`
- `src/functions/content_summarization/scripts/backlog_processor.py` — import path update
- `src/functions/url_content_extraction/core/db/__init__.py` — ephemeral imports removed
- `src/functions/url_content_extraction/core/facts_batch/request_generator.py`
- `src/functions/url_content_extraction/core/facts_batch/result_processor.py`
- `src/functions/url_content_extraction/core/utils/__init__.py` — shim update
- `src/functions/url_content_extraction/functions/main.py`
- `src/functions/url_content_extraction/functions/local_server.py`
- `src/functions/url_content_extraction/scripts/content_batch_processor.py`
- `tests/article_knowledge_extraction/test_job_store.py`
- `tests/url_content_extraction/test_playwright_extractor.py`
- `tests/url_content_extraction/test_regressions.py`
- `CLAUDE.md` — updated shared utilities inventory, module list, async-job pattern note
- `AGENTS.md` — updated shared dir structure, module list, coding style notes

### New
- `src/shared/jobs/__init__.py`, `contracts.py`, `store.py`
- `src/shared/extractors/__init__.py`, `extractor_factory.py`, `light_extractor.py`, `playwright_extractor.py`
- `src/shared/processors/__init__.py`, `content_cleaner.py`, `metadata_extractor.py`, `text_deduplicator.py`
- `src/shared/contracts/extracted_content.py`
- `src/shared/utils/amp_detector.py`, `consent_handler.py`
- `src/functions/url_content_extraction_service/` (full module — core, functions, scripts, tests, docs)
- `supabase/migrations/20260422120000_extraction_jobs_shared_table.sql`
- `.github/workflows/url-content-extraction-cleanup.yml`
- `tests/url_content_extraction_service/test_factory.py`, `test_worker.py`, `test_auth.py`

## Code Quality Notes
- **Tests (today's scope)**: 61 passed, 0 failed across `tests/url_content_extraction_service/`, `tests/url_content_extraction/`, `tests/article_knowledge_extraction/`
- **Full suite** (excluding pre-existing `gemini_tts_batch` import error — `pydub` not installed in root venv): 143 passed, 6 failed
- The 6 failures are all in `tests/knowledge_extraction/test_extraction_pipeline.py` — `FakeKnowledgeWriter` does not expose a `.client` attribute that `KnowledgeCompletionTracker` now requires; this was introduced by a prior PR and is pre-existing, not caused by today's work
- `gemini_tts_batch` tests fail at collection time due to `ModuleNotFoundError: No module named 'pydub'` — also pre-existing; no linting toolchain configured at project root

## Open Items / Carry-over
- **Pre-existing test failures**: 6 `knowledge_extraction` pipeline tests need a `FakeKnowledgeWriter` update to include a `.client` attribute (or the pipeline should not access `writer.client` directly)
- **`pydub` dep**: `gemini_tts_batch` tests cannot be collected without installing `pydub` into the root venv — add to `requirements-dev.txt` if that module should be covered by the shared suite
- **Supabase migration**: `supabase/migrations/20260422120000_extraction_jobs_shared_table.sql` must be applied before deploying `url_content_extraction_service` to a new environment
- **Pre-existing deploy.sh whitespace edits**: `article_summarization`, `article_translation`, `article_validation`, `daily_team_update`, `fuzzy_search`, `game_analysis_package`, `news_extraction`, `team_article_generation` all have unstaged whitespace changes in their `deploy.sh` files — intentionally left unstaged; clean up or commit separately
- **Push and PR**: Branch `feat/url-content-extraction-service` created locally; user to push and open PR when ready
