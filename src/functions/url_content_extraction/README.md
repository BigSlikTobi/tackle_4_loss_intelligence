# URL Content Extraction Module

This module provides the scaffolding for a standalone content extraction service that retrieves structured article data from arbitrary web URLs using Python-based headless browsing. It follows the platform's function-based isolation guidelines and will later power Task 2 of the Daily Team Update Pipeline.

## Responsibilities
- Execute Playwright-backed browser sessions for complex pages
- Offer a lightweight HTTP extractor for fast paths
- Clean, deduplicate, and normalize extracted content
- Produce strongly typed data contracts that downstream services can reuse

## Project Layout
```
core/
  contracts/           # Data models for extraction inputs and results
  extractors/          # Playwright and lightweight extractor strategies
  processors/          # Content cleaning and metadata parsing helpers
  utils/               # Cross-cutting utilities (consent handling, AMP detection)
functions/             # Cloud Function adapters (stub)
scripts/               # CLI tooling for manual extraction runs
requirements.txt       # Module-specific dependencies
```

## Configuration
All configuration values must be provided through the central project `.env`. Do not add module-specific environment files. Future work will add explicit validation helpers within `core`.

## Next Steps
- Implement data contracts that describe extraction options and results
- Build extractor strategies (Playwright and lightweight HTTP)
- Add processing pipelines for cleaning, metadata enrichment, and deduplication
- Wire up the CLI tool for manual executions and diagnostics
