# Changelog — 2026-04-22

## Summary
Built the new `article_knowledge_extraction` module — a self-contained, on-demand HTTP service for extracting topics and entities from individual articles, following the stateless async job pattern (submit → poll → worker). Also refactored `EntityResolver` and `ResolvedEntity` into `src/shared/nlp/` to avoid future cross-module duplication, and extended `url_content_extraction` with an ephemeral content handoff layer (phase 6a).

## Changes

### New module: `src/functions/article_knowledge_extraction/`
- Stateless async job pattern: three HTTP entry points (`/submit`, `/poll`, `/worker`) exposed via a single Cloud Function
- Ephemeral job store backed by Supabase (`article_knowledge_jobs` table) with atomic delete-on-read and 24-hour TTL
- `ArticleExtractionPipeline` orchestrates topic extraction → entity extraction → entity resolution in a single pass
- `ResolverAdapter` bridges the new module to the shared `EntityResolver`, accepting a request-scoped Supabase client
- Four CLI scripts: `submit_job_cli.py`, `poll_job_cli.py`, `extract_article_knowledge_cli.py`, `cleanup_expired_jobs_cli.py`
- Deployed to GCP; end-to-end tested with a real article — confirmed working
- Late fix: `EntityResolver` updated to accept injected Supabase client instead of reading env creds at construction time; adapter, pipeline, and worker threaded through accordingly; redeployed

### Shared refactor: `src/shared/nlp/` + `src/shared/contracts/knowledge.py`
- Moved `EntityResolver` (full ~850-line implementation) from `knowledge_extraction/core/resolution/` to `src/shared/nlp/entity_resolver.py`
- Moved `NFL_TEAM_ALIASES` to `src/shared/nlp/team_aliases.py`
- Added `ResolvedEntity` dataclass to `src/shared/contracts/knowledge.py`
- Left a re-export shim at the original location (`knowledge_extraction/core/resolution/entity_resolver.py`) preserving all existing import paths
- `src/shared/contracts/__init__.py` created alongside `knowledge.py`

### New GitHub Actions workflow: `.github/workflows/article-knowledge-cleanup.yml`
- Runs every 5 minutes to delete expired or consumed job rows from `article_knowledge_jobs`
- Calls `cleanup_expired_jobs_cli.py` with Supabase secrets from GitHub secrets

### `url_content_extraction` — ephemeral handoff layer (phase 6a, feature-flagged off)
- New `core/db/ephemeral.py` — `EphemeralContentStore` for reading/writing `news_url_content_ephemeral` rows
- New `scripts/ephemeral_sweep_cli.py` — deletes consumed/expired rows
- New `schema.sql` — DDL for `news_url_content_ephemeral` table (48h TTL, `consumed_at` guard)
- `functions/main.py` extended: stage 2 (fetch) optionally writes to ephemeral table; stage 3 (facts) optionally reads from there instead of re-fetching
- `core/facts_batch/request_generator.py` and `result_processor.py` updated to honour ephemeral reads
- `content_batch_processor.py` updated accordingly
- `core/db/__init__.py` re-exports `EphemeralContentStore`
- All three pipeline GitHub Actions workflows (`content-pipeline-create.yml`, `content-pipeline-poll.yml`, `content-facts-entities-realtime.yml`) gain `EPHEMERAL_CONTENT_ENABLED: 'false'` env var — ready to flip in phase 6b/6c
- `content-pipeline-poll.yml` adds a sweep step that always runs after polling
- `README.md` updated to document the ephemeral handoff design
- `.env.example` documents `WORKER_TOKEN` and `EPHEMERAL_CONTENT_ENABLED`

### Tests
- 21 new tests in `tests/article_knowledge_extraction/` — all passing
  - `test_article_extraction_pipeline.py` — pipeline integration with fake extractors
  - `test_factory.py` — request validation for submit/poll/worker entry points
  - `test_job_store.py` — full job lifecycle + expiry cleanup
  - `test_prompts.py` — prompt content and category coverage assertions
- 2 new shim regression tests in `tests/knowledge_extraction/test_entity_resolver_shim.py` — confirm original import paths still work
- New `tests/url_content_extraction/test_ephemeral.py` — covers `EphemeralContentStore`

## Files Modified

### New files (untracked → added)
- `src/functions/article_knowledge_extraction/` — entire new module (see above)
- `src/shared/nlp/entity_resolver.py` — canonical EntityResolver (moved from knowledge_extraction)
- `src/shared/nlp/team_aliases.py` — NFL team aliases dict
- `src/shared/contracts/knowledge.py` — `ResolvedEntity` dataclass
- `src/shared/contracts/__init__.py` — package init
- `tests/article_knowledge_extraction/` — 4 new test files
- `tests/knowledge_extraction/test_entity_resolver_shim.py` — shim regression tests
- `tests/url_content_extraction/test_ephemeral.py` — ephemeral store tests
- `.github/workflows/article-knowledge-cleanup.yml` — new cleanup cron workflow
- `src/functions/url_content_extraction/core/db/ephemeral.py` — ephemeral store
- `src/functions/url_content_extraction/schema.sql` — DDL for ephemeral table
- `src/functions/url_content_extraction/scripts/ephemeral_sweep_cli.py` — sweep CLI

### Modified files
- `src/functions/knowledge_extraction/core/resolution/entity_resolver.py` — replaced with re-export shim
- `src/functions/url_content_extraction/functions/main.py` — ephemeral handoff support (feature-flagged)
- `src/functions/url_content_extraction/core/contracts/extracted_content.py` — ephemeral fields
- `src/functions/url_content_extraction/core/db/__init__.py` — re-exports EphemeralContentStore
- `src/functions/url_content_extraction/core/facts_batch/request_generator.py` — ephemeral read path
- `src/functions/url_content_extraction/core/facts_batch/result_processor.py` — ephemeral consume path
- `src/functions/url_content_extraction/scripts/content_batch_processor.py` — ephemeral integration
- `src/functions/url_content_extraction/functions/local_server.py` — minor update
- `src/functions/url_content_extraction/README.md` — ephemeral handoff documentation
- `.env.example` — documents WORKER_TOKEN and EPHEMERAL_CONTENT_ENABLED
- `.github/workflows/content-pipeline-create.yml` — adds EPHEMERAL_CONTENT_ENABLED env var
- `.github/workflows/content-pipeline-poll.yml` — adds EPHEMERAL_CONTENT_ENABLED + sweep step
- `.github/workflows/content-facts-entities-realtime.yml` — adds EPHEMERAL_CONTENT_ENABLED env var

### Pre-existing modifications (not this session — unrelated deploy.sh standardization)
- `src/functions/article_summarization/functions/deploy.sh`
- `src/functions/article_translation/functions/deploy.sh`
- `src/functions/article_validation/functions/deploy.sh`
- `src/functions/daily_team_update/functions/deploy.sh`
- `src/functions/fuzzy_search/scripts/deploy.sh`
- `src/functions/game_analysis_package/functions/deploy.sh`
- `src/functions/news_extraction/functions/deploy.sh`
- `src/functions/team_article_generation/functions/deploy.sh`

## Code Quality Notes
- Tests run: `venv/bin/python -m pytest tests/article_knowledge_extraction/ tests/knowledge_extraction/ tests/url_content_extraction/ -v`
- Result: **60 passed, 6 failed** — the 6 failures are in `tests/knowledge_extraction/test_extraction_pipeline.py` and are **pre-existing** (confirmed by running on the pre-change committed state)
- New module tests: 21/21 passed
- Shim regression tests: 2/2 passed
- No linting toolchain configured at project root (no ruff/flake8/mypy)
- No debug print statements or stray TODO/FIXME comments observed in new files
- `__pycache__/` directories present in module tree — excluded from commit via `.gitignore`

## Open Items / Carry-over
- `EPHEMERAL_CONTENT_ENABLED` is `false` in all three workflows. Phase 6b: flip to `true` in `content-facts-entities-realtime.yml` (lowest volume) once `news_url_content_ephemeral` schema migration has been applied to Supabase
- Phase 6c: flip `EPHEMERAL_CONTENT_ENABLED` in the main pipeline workflows once phase 6b is validated
- The 8 pre-existing deploy.sh modifications across other modules (article_summarization, article_translation, article_validation, daily_team_update, fuzzy_search, game_analysis_package, news_extraction, team_article_generation) are uncommitted — review and commit separately if intentional
- `tests/knowledge_extraction/test_extraction_pipeline.py` has 6 pre-existing failures (`FakeKnowledgeWriter` missing `.client` attribute) — investigate in a future session
- PRs #119–#123 stacked series from prior day; merge in order or retarget to main
