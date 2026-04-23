# Changelog — 2026-04-23

## Summary
Short session focused on unblocking Cloud Function deployment: resolved a git merge conflict in `result_processor.py` that left unresolved conflict markers and dead code in place, preventing the `knowledge_extraction` Cloud Function from deploying. PR #129 (4 Codex review fixes across `url_content_extraction_service` and `article_knowledge_extraction`) was also merged earlier in the session.

## Changes
- **Merge conflict resolution** (`knowledge_extraction`): Removed unresolved `<<<<<<< Updated upstream / ======= / >>>>>>> Stashed changes` markers from `src/functions/knowledge_extraction/core/fact_batch/result_processor.py` (lines 242–383 of the pre-fix file). Accepted the "Updated upstream" side (deletion of two private methods).
  - Removed `_update_url_timestamps` — fetched `news_url_ids` for processed facts and set `knowledge_extracted_at` on `news_urls`. Was never called from anywhere outside its own class after the upstream refactor superseded it.
  - Removed `_filter_fully_processed_urls` — checked whether all facts for a URL had at least one topic row before marking the URL complete. Same situation: orphaned by upstream changes and unreachable from any caller.
- **PR #129 merged** (earlier in session, pre-compaction): Backported 4 Codex-review findings into `url_content_extraction_service` and `article_knowledge_extraction` — WORKER_URL import ordering, missing `raise_for_status()` calls, `load_env()` invoked before `argparse` in CLI entrypoints.

## Files Modified
- `src/functions/knowledge_extraction/core/fact_batch/result_processor.py` — removed 144 lines of orphaned dead code and conflict markers; file now parses cleanly.

## Code Quality Notes
- Syntax check: `result_processor.py` parses cleanly with `ast.parse` after the fix.
- Tests run (scoped to modules touched this session): `tests/knowledge_extraction/`, `tests/article_knowledge_extraction/`, `tests/url_content_extraction/`, `tests/story_embeddings/`.
  - **54 passed**, 2 deprecation warnings (`datetime.utcnow()` in `story_embeddings`).
  - **6 pre-existing failures** in `tests/knowledge_extraction/test_extraction_pipeline.py`: `FakeKnowledgeWriter` mock lacks a `.client` attribute that `ExtractionPipeline.__init__` now requires (introduced by `KnowledgeCompletionTracker` addition in an earlier commit). These failures pre-date today's session and are unrelated to the `result_processor.py` fix.
  - `tests/story_grouping/` skipped — `numpy` not installed in the project venv.
  - Several other test modules (data_loading, gemini_tts_batch, image_selection, news_extraction, news_extraction_service) error at collection due to missing optional deps (`yaml`, `numpy`); these are pre-existing environment gaps.

## Open Items / Carry-over
- **Fix `test_extraction_pipeline.py` (6 failures)**: `FakeKnowledgeWriter` in the test file needs a `.client` attribute (can be `None` or a `MagicMock`) to satisfy `KnowledgeCompletionTracker(client=self.writer.client)`. Low-effort fix.
- **`datetime.utcnow()` deprecation** in `story_embeddings/core/pipelines/embedding_pipeline.py`: replace with `datetime.now(timezone.utc)` before Python 3.14 removes the deprecated call.
- Untracked files left untouched per session scope: `src/functions/article_knowledge_extraction/`, `src/shared/contracts/knowledge.py`, `src/shared/nlp/`, `tests/article_knowledge_extraction/`, `tests/knowledge_extraction/test_entity_resolver_shim.py`, `.github/workflows/article-knowledge-cleanup.yml` — these belong to a prior feature branch and should be reviewed/committed in a dedicated session.
- Several `deploy.sh` files and `entity_resolver.py` shim have unstaged modifications (pre-existing from earlier work) — not included in today's commit.
