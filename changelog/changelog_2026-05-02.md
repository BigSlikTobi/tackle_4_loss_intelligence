# Changelog — 2026-05-02

## Summary
Fixed issue #136 where Yahoo articles were silently dropped by the `nfl_only` filter after Yahoo restructured article URLs from `/nfl/article/...` to `/articles/...`. The fix trusts the feed-level URL context when the source's own feed URL is NFL-specific, so per-article URL restructuring by publishers cannot silently drop valid NFL content.

## Changes
- **Bug fix (issue #136): Yahoo NFL articles silently dropped by `nfl_only` filter**
  - Root cause: Yahoo restructured article URLs; the per-item `_looks_nfl(url)` regex no longer matched `/articles/...` paths, causing every Yahoo article to be filtered out even when sourced from `https://sports.yahoo.com/nfl/rss/`.
  - Fix: `_create_news_item` now also accepts an item as NFL when the source's own feed URL is NFL-specific (`_looks_nfl(source.url)`). Uses `getattr` so stub configs without a `url` attribute remain safe.
  - Applied identically to both the legacy `news_extraction` module and the production `news_extraction_service` module (the latter is what the editorial cycle calls).
- **Regression test added** to `tests/news_extraction/test_regressions.py`
  - `test_extractor_trusts_nfl_specific_feed_url`: covers the Yahoo `/articles/...` case (now accepted) and a general ESPN feed (per-item URL filter still applies; non-NFL item still rejected).
  - `Optional` import added to test file.

## Files Modified
- `src/functions/news_extraction/core/extractors/base.py` — `_create_news_item`: added feed-URL trust logic with `getattr`-safe access and inline comment.
- `src/functions/news_extraction_service/core/extraction/extractors/base.py` — identical fix applied to the async-job service copy.
- `tests/news_extraction/test_regressions.py` — added `test_extractor_trusts_nfl_specific_feed_url` (covers Yahoo accept + ESPN general-feed reject); added `Optional` import.

## Code Quality Notes
- Tests: 11/11 passed (`pytest tests/news_extraction/test_regressions.py` — 0.13s). 1 new test added today.
- Linting: not run (no UI changes; Python linting not configured as a project-level command).
- No debug print statements, TODO/FIXME/HACK comments, or commented-out code blocks introduced.
- `news_extraction_service` successfully redeployed to GCP Cloud Functions by the developer.
- Legacy `news_extraction` module was patched in source but NOT redeployed (production editorial cycle uses `news_extraction_service`; this is intentional).

## Open Items / Carry-over
- Legacy `news_extraction` Cloud Function still runs the old code — if it is ever called directly it will have the pre-fix behaviour. Redeploy when convenient.
- `news_extraction_service` and `news_extraction` contain near-identical `base.py` files. Long-term de-duplication (e.g., move `BaseExtractor` into `src/shared/`) would prevent future divergence, but is not blocking.
- AGENTS.md test count for `tests/news_extraction/` was updated from "7 tests" to "11 tests" (had been stale since a previous session).
